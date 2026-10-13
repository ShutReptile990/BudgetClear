"""Preserve existing API routes while selecting local or Supabase persistence."""
import hashlib
import hmac
import json
import math
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, Request, Response

import config
import supabase_store as cloud
from ledger_import import read_ledger

if config.STORAGE_BACKEND == "local":
    import auth_history as local


def get_current_user(request: Request, response: Response):
    if config.STORAGE_BACKEND == "supabase":
        return cloud.current_user(request, response)
    return local.get_current_user(request.cookies.get("budgetclear_session"))


def signup(full_name, email, password, response):
    if config.STORAGE_BACKEND == "supabase":
        return cloud.signup(full_name, email, password, response)
    user = local.register_user(full_name, email, password)
    local.set_session_cookie(response, local.create_session(user["id"]))
    return {"user": user}


def login(email, password, response):
    if config.STORAGE_BACKEND == "supabase":
        return cloud.login(email, password, response)
    user, token = local.authenticate(email, password)
    local.set_session_cookie(response, token)
    return {"user": user}


def logout(request, response):
    if config.STORAGE_BACKEND == "supabase":
        return cloud.logout(request, response)
    local.clear_session(response, request.cookies.get("budgetclear_session"))


def list_audits(user):
    return cloud.list_audits(user) if config.STORAGE_BACKEND == "supabase" else local.list_audits(user["id"])


def get_audit(user, audit_id):
    return cloud.get_audit(user, audit_id) if config.STORAGE_BACKEND == "supabase" else local.get_audit(audit_id, user["id"])


def save_audit(user, payload):
    source_ids = payload.get("source_ids", [])
    if not source_ids or len(source_ids) != len(set(source_ids)):
        raise HTTPException(422, "An audit must reference distinct uploaded CSV sources.")
    records = load_records(user, source_ids)
    if payload.get("record_count") != len(records) or payload["analysis_result"].get("transactions") != records:
        raise HTTPException(422, "Report records do not match the stored CSV evidence. Run the audit again.")
    records_by_id = {record["evidence_id"]: record for record in records}
    for flag in payload["analysis_result"].get("anomalies", []):
        if not isinstance(flag, dict):
            raise HTTPException(422, "Invalid report finding.")
        score = flag.get("confidence_score")
        if not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 100:
            raise HTTPException(422, "Confidence scores must be between 0 and 100.")
        evidence = flag.get("evidence", [])
        if not isinstance(evidence, list) or not evidence:
            raise HTTPException(422, "Each finding must link to source evidence.")
        for entry in evidence:
            original = records_by_id.get(entry.get("evidence_id")) if isinstance(entry, dict) else None
            if original is None or any(entry.get(key, "") != original.get(key, "") for key in (
                    "source_file_id", "source_filename", "source_record_number", "source_sha256", "transaction_id",
                    "date", "vendor", "amount", "currency", "description", "category", "invoice_number")):
                raise HTTPException(422, "A finding's evidence does not match the stored CSV.")
        allowed = {entry["evidence_id"] for entry in evidence}
        citations = flag.get("cited_evidence_ids", [])
        if (not isinstance(citations, list) or not all(isinstance(c, str) for c in citations)
                or not set(citations).issubset(allowed) or flag.get("primary_evidence_id") not in citations):
            raise HTTPException(422, "A finding has invalid evidence citations.")
    return cloud.save_audit(user, payload) if config.STORAGE_BACKEND == "supabase" else local.save_audit(user["id"], payload)


def store_source(user, filename, content, row_count, currency=None):
    source_id = str(uuid.uuid4())
    metadata = {"id": source_id, "original_filename": filename, "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content), "row_count": row_count, "currency": currency,
                "object_path": f"{user['id']}/{source_id}.csv", "created_at": datetime.now(timezone.utc).isoformat()}
    if config.STORAGE_BACKEND == "supabase":
        cloud.store_csv(user, metadata, content)
    else:
        directory = config.BACKEND_DIR / "uploads" / user["id"]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{source_id}.csv").write_bytes(content)
        (directory / f"{source_id}.json").write_text(json.dumps(metadata), encoding="utf-8")
    return metadata


def load_source(user, source_id):
    try:
        if str(uuid.UUID(source_id)) != source_id:
            raise ValueError()
    except (ValueError, AttributeError):
        raise HTTPException(422, "Invalid CSV source ID.")
    if config.STORAGE_BACKEND == "supabase":
        metadata, content = cloud.load_csv(user, source_id)
    else:
        directory = config.BACKEND_DIR / "uploads" / user["id"]
        try:
            metadata = json.loads((directory / f"{source_id}.json").read_text(encoding="utf-8"))
            content = (directory / f"{source_id}.csv").read_bytes()
        except FileNotFoundError:
            raise HTTPException(404, "CSV source not found.")
    if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), metadata["sha256"]):
        raise HTTPException(500, "CSV evidence integrity check failed.")
    return metadata, content


def source_records(df, metadata):
    # Record ordinals are data records, not physical line numbers (quoted CSV can span lines).
    records = json.loads(df.to_json(orient="records", date_format="iso", double_precision=15))
    for index, record in enumerate(records, start=1):
        record.update(evidence_id=f"{metadata['id']}:R{index}", source_file_id=metadata["id"],
                      source_filename=metadata["original_filename"], source_record_number=index,
                      source_sha256=metadata["sha256"])
    return records


def load_records(user, source_ids):
    if not source_ids or len(source_ids) > 50 or len(source_ids) != len(set(source_ids)):
        raise HTTPException(422, "Choose between 1 and 50 distinct uploaded CSV sources.")
    records = []
    for source_id in source_ids:
        metadata, content = load_source(user, source_id)
        records.extend(source_records(read_ledger(content, metadata.get("currency")), metadata))
        if len(records) > config.MAX_LEDGER_ROWS:
            raise HTTPException(413, f"An audit can contain at most {config.MAX_LEDGER_ROWS} records.")
    if len({row["currency"] for row in records}) > 1:
        raise HTTPException(422, "Run each currency separately.")
    return records
