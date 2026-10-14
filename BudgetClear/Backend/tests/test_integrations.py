"""Offline integration coverage. No real API keys, cloud calls, or model downloads."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

_temp = tempfile.TemporaryDirectory()
os.environ["BUDGETCLEAR_STORAGE_BACKEND"] = "local"
os.environ["BUDGETCLEAR_DB_PATH"] = str(Path(_temp.name) / "test.sqlite3")

import httpx
import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException, Response
from starlette.requests import Request

import config
import main
import analyze
import services
import supabase_store as cloud
import ai_explanations as explanations

config.BACKEND_DIR = Path(_temp.name)
config.AI_API_KEY = ""
config.AI_MODEL = ""
config.COOKIE_SECURE = False
app = FastAPI()
app.router.routes.extend(main.app.router.routes)
app.router.routes.extend(analyze.app.router.routes)

CSV = (b'transaction_id,date,vendor,category,description,amount,invoice_number\r\n'
       b'T1,2026-04-01,Acme,Office,"Paper, stationery",2000,INV001A\r\n'
       b'T1,2026-04-02,Acme,Office,Paper supplies,2000,INV001B\r\n')


def tearDownModule():
    _temp.cleanup()


class LocalWorkflow(unittest.IsolatedAsyncioTestCase):
    async def test_upload_analysis_report_history_and_ownership(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            self.assertEqual((await client.post("/api/v1/ingest", files={"file": ("ledger.csv", CSV)})).status_code, 401)
            signup = await client.post("/api/v1/auth/signup", json={"full_name": "Test Auditor", "email": "owner@example.test", "password": "strong-test-password"})
            self.assertEqual(signup.status_code, 200, signup.text)
            uploaded = await client.post("/api/v1/ingest", files={"file": ("ledger.csv", CSV, "text/csv")})
            self.assertEqual(uploaded.status_code, 200, uploaded.text)
            data = uploaded.json()
            source = data["source"]
            self.assertEqual(source["sha256"], hashlib.sha256(CSV).hexdigest())
            self.assertEqual(data["records"][1]["source_record_number"], 2)
            original = await client.get(f"/api/v1/sources/{source['id']}/download")
            self.assertEqual(original.content, CSV)
            scored = await client.post("/api/v1/analyze", json={"source_ids": [source["id"]]})
            self.assertEqual(scored.status_code, 200, scored.text)
            analysis = scored.json()
            self.assertEqual(len(analysis["results"]), 1)
            flag = analysis["results"][0]
            self.assertTrue(85 <= flag["confidence_score"] < 100)
            self.assertEqual(flag["explanation_source"], "detector")
            self.assertEqual(len(set(flag["cited_evidence_ids"])), 2)
            payload = {"budget_name": "Evidence check", "source_ids": [source["id"]], "record_count": 2,
                       "analysis_result": {"transactions": analysis["records"], "anomalies": analysis["results"]},
                       "calculated_total": "4000.00", "review_suggestion_count": 1}
            saved = await client.post("/api/v1/audits", json=payload)
            self.assertEqual(saved.status_code, 201, saved.text)
            audit_id = saved.json()["id"]
            reopened = (await client.get(f"/api/v1/audits/{audit_id}")).json()
            self.assertEqual(reopened["analysis"]["analysis_result"], payload["analysis_result"])
            altered = copy.deepcopy(payload)
            altered["analysis_result"]["transactions"][0]["amount"] = 1
            self.assertEqual((await client.post("/api/v1/audits", json=altered)).status_code, 422)
            altered = copy.deepcopy(payload)
            altered["analysis_result"]["anomalies"][0]["evidence"][0]["amount"] = 1
            self.assertEqual((await client.post("/api/v1/audits", json=altered)).status_code, 422)
            await client.post("/api/v1/auth/logout")
            self.assertEqual((await client.get("/api/v1/auth/me")).status_code, 401)
            await client.post("/api/v1/auth/signup", json={"full_name": "Another Auditor", "email": "other@example.test", "password": "strong-test-password"})
            self.assertEqual((await client.get(f"/api/v1/audits/{audit_id}")).status_code, 404)
            self.assertEqual((await client.get(f"/api/v1/sources/{source['id']}/download")).status_code, 404)
            self.assertEqual((await client.post("/api/v1/analyze", json={"source_ids": [source["id"]]})).status_code, 404)
            await client.post("/api/v1/auth/logout")
            await client.post("/api/v1/auth/login", json={"email": "owner@example.test", "password": "strong-test-password"})
            self.assertEqual(len((await client.get("/api/v1/audits")).json()["audits"]), 1)
            self.assertEqual((await client.get(f"/api/v1/audits/{audit_id}/download")).status_code, 200)


def fixture_flag():
    metadata = {"id": "11111111-1111-4111-8111-111111111111", "original_filename": "ledger.csv", "sha256": hashlib.sha256(CSV).hexdigest()}
    records = services.source_records(services.read_ledger(CSV), metadata)
    return analyze.detect(records)[0]


class ExplanationChecks(unittest.IsolatedAsyncioTestCase):
    def test_rejects_invented_or_missing_evidence(self):
        flag = fixture_flag()
        valid = {"flag_id": flag["flag_id"], "reason": "Review these similar invoices for the same vendor and amount.", "evidence_ids": flag["required_evidence_ids"]}
        self.assertIsNotNone(explanations.validate_explanation(valid, flag))
        self.assertIsNone(explanations.validate_explanation({**valid, "evidence_ids": ["invented"]}, flag))
        self.assertIsNone(explanations.validate_explanation({**valid, "evidence_ids": flag["required_evidence_ids"][:1]}, flag))
        self.assertIsNone(explanations.validate_explanation({**valid, "reason": "x" * 361}, flag))

    async def test_ai_success_and_provider_failure_fallback(self):
        flag = fixture_flag()
        original_score = flag["confidence_score"]
        original_client = httpx.AsyncClient
        def handler(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "test-model")
            self.assertEqual(request.url.path, "/v1/chat/completions")
            text = json.dumps({"explanations": [{"flag_id": flag["flag_id"], "reason": "Review both invoices: vendor and amount match, and invoice strings are similar.", "evidence_ids": flag["required_evidence_ids"]}]})
            return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})
        def factory(**kwargs):
            return original_client(transport=httpx.MockTransport(handler), **kwargs)
        with patch.object(config, "AI_API_KEY", "test-key"), patch.object(config, "AI_MODEL", "test-model"), patch.object(httpx, "AsyncClient", factory):
            result = (await explanations.explain_flags([flag]))[0]
            self.assertEqual(result["explanation_source"], "ai")
            self.assertEqual(result["confidence_score"], original_score)
        def failing_factory(**kwargs):
            return original_client(transport=httpx.MockTransport(lambda _: httpx.Response(429)), **kwargs)
        with patch.object(config, "AI_API_KEY", "test-key"), patch.object(config, "AI_MODEL", "test-model"), patch.object(httpx, "AsyncClient", failing_factory):
            result = (await explanations.explain_flags([fixture_flag()]))[0]
            self.assertEqual(result["explanation_source"], "detector")
            self.assertEqual(result["explanation_status"], "unavailable")

    def test_semantic_score_and_peer_evidence(self):
        base = fixture_flag()["evidence"][0]
        rows = [{**base, "description": f"description {i}", "evidence_id": f"source:R{i}", "source_record_number": i} for i in range(1, 5)]
        class Model:
            def encode(self, _):
                return np.array([[1, 0], [1, 0], [1, 0], [0, 1]], dtype=np.float32)
        with patch.object(analyze, "get_model", return_value=Model()):
            flags = analyze.detect_category_camouflage(pd.DataFrame(rows))
        self.assertEqual(len(flags), 1)
        self.assertAlmostEqual(flags[0]["confidence_score"], 68.38, places=2)
        self.assertEqual(len(flags[0]["evidence"]), 4)

    def test_benford_score_and_duplicate_work_limit(self):
        base = fixture_flag()["evidence"][0]
        rows = [{**base, "evidence_id": f"source:R{i}", "source_record_number": i, "amount": 9900} for i in range(1, 101)]
        flags = analyze.detect_smurfing_benfords_mad(pd.DataFrame(rows))
        self.assertEqual(len(flags), 100)
        self.assertTrue(all(0 <= flag["confidence_score"] <= 100 for flag in flags))
        self.assertEqual(flags[0]["metrics"]["cluster_records"], 100)
        self.assertEqual(len(flags[0]["evidence"]), 10)
        with self.assertRaises(HTTPException) as error:
            analyze.detect_fuzzy_duplicates(pd.DataFrame(rows * 5))
        self.assertEqual(error.exception.status_code, 413)

    def test_dwp_original_encoding_and_negative_adjustment(self):
        raw = ('Date,Vendor,Invoice Cost Centre Description,Description,Transparency Invoice Amount,Payment Number\n'
               '01-04-2026,Acme,Office,Adjustment,-25.50,P1\n'
               '02-04-2026,Acme,Office,Supplies,£26000.00,P1\n').encode('cp1252')
        df = services.read_ledger(raw)
        self.assertEqual(df['amount'].tolist(), [-25.5, 26000.0])
        self.assertTrue(df['source_format'].eq('dwp').all())
        self.assertTrue(main.invalid_rows(df).empty)


class SupabaseContract(unittest.TestCase):
    def test_auth_refresh_csv_reports_and_integrity(self):
        original_client = httpx.Client
        uploads, reports, objects, calls = {}, {}, {}, []
        uid = "22222222-2222-4222-8222-222222222222"
        raw_user = {"id": uid, "email": "cloud@example.test", "user_metadata": {"full_name": "Cloud Auditor"}}
        session = {"user": raw_user, "access_token": "user-access", "refresh_token": "user-refresh"}
        def handler(request):
            calls.append(request)
            path = request.url.path
            if path == "/auth/v1/signup":
                return httpx.Response(200, json={"user": raw_user})
            if path == "/auth/v1/token":
                return httpx.Response(200, json=session)
            if path == "/auth/v1/user":
                if request.headers["Authorization"] == "Bearer expired":
                    return httpx.Response(401, json={"error_code": "bad_jwt"})
                return httpx.Response(200, json=raw_user)
            if path == "/auth/v1/logout":
                return httpx.Response(204)
            self.assertEqual(request.headers["Authorization"], "Bearer user-access")
            self.assertEqual(request.headers["apikey"], "anon-test")
            if path.startswith("/storage/v1/object/"):
                object_id = path.rsplit("/", 1)[-1]
                if request.method == "POST":
                    objects[object_id] = request.content
                    return httpx.Response(200, json={"Key": object_id})
                return httpx.Response(200, content=objects[object_id])
            target = uploads if path == "/rest/v1/csv_uploads" else reports
            if request.method == "POST":
                row = json.loads(request.content)
                target[row["id"]] = row
                return httpx.Response(201)
            self.assertEqual(request.url.params["user_id"], f"eq.{uid}")
            ident = request.url.params.get("id", "").removeprefix("eq.")
            return httpx.Response(200, json=[target[ident]] if ident in target else list(target.values()) if not ident else [])
        def factory(**kwargs):
            return original_client(transport=httpx.MockTransport(handler), **kwargs)
        with patch.object(config, "SUPABASE_URL", "https://project.supabase.co"), patch.object(config, "SUPABASE_ANON_KEY", "anon-test"), patch.object(httpx, "Client", factory):
            response = Response()
            self.assertTrue(cloud.signup("Cloud Auditor", "cloud@example.test", "test-password", response)["requires_confirmation"])
            self.assertEqual(cloud.login("cloud@example.test", "test-password", response)["user"]["id"], uid)
            self.assertIn("HttpOnly", response.headers.get("set-cookie"))
            req = Request({"type": "http", "headers": [(b"cookie", b"budgetclear_sb_access=expired; budgetclear_sb_refresh=user-refresh")]})
            user = cloud.current_user(req, Response())
            self.assertEqual(user["_access_token"], "user-access")
            metadata = {"id": "33333333-3333-4333-8333-333333333333", "original_filename": "ledger.csv", "object_path": f"{uid}/33333333-3333-4333-8333-333333333333.csv", "sha256": hashlib.sha256(CSV).hexdigest(), "size_bytes": len(CSV), "row_count": 2}
            cloud.store_csv(user, metadata, CSV)
            self.assertEqual(cloud.load_csv(user, metadata["id"])[1], CSV)
            payload = {"budget_name": "Cloud audit", "source_ids": [metadata["id"]], "record_count": 2, "analysis_result": {"transactions": []}}
            saved = cloud.save_audit(user, payload)
            self.assertEqual(cloud.get_audit(user, saved["id"])["analysis"], payload)
            self.assertEqual(len(cloud.list_audits(user)), 1)
            reports[saved["id"]]["snapshot_json"] = '{}'
            with self.assertRaises(HTTPException) as err:
                cloud.get_audit(user, saved["id"])
            self.assertEqual(err.exception.status_code, 500)
            cloud.logout(Request({"type": "http", "headers": [(b"cookie", b"budgetclear_sb_access=user-access")]}), Response())


if __name__ == "__main__":
    unittest.main()
