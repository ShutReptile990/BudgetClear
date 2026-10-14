"""Supabase Auth, PostgREST, and private Storage using the user's JWT and RLS.

No service-role key is required. Never return tokens through a JSON response.
"""
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from fastapi import HTTPException, Response

import config

ACCESS_COOKIE = "budgetclear_sb_access"
REFRESH_COOKIE = "budgetclear_sb_refresh"


def request(method, path, token=None, **kwargs):
    if not config.SUPABASE_URL or not config.SUPABASE_ANON_KEY:
        raise HTTPException(503, "Fill SUPABASE_URL and SUPABASE_ANON_KEY in Backend/.env, then restart both APIs.")
    headers = {"apikey": config.SUPABASE_ANON_KEY, **kwargs.pop("headers", {})}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=45) as client:
            result = client.request(method, config.SUPABASE_URL + path, headers=headers, **kwargs)
    except httpx.RequestError as exc:
        raise HTTPException(503, "Supabase is unreachable. Check the project URL and network connection.") from exc
    if result.is_error:
        try:
            body = result.json()
        except ValueError:
            body = {}
        code = body.get("error_code") or body.get("code")
        if path.startswith("/auth/"):
            message = {
                "invalid_credentials": "Email or password is incorrect.",
                "email_not_confirmed": "Confirm your email before signing in.",
                "user_already_exists": "An account with this email already exists.",
                "over_email_send_rate_limit": "Email limit reached. Please try again later.",
                "weak_password": "Choose a stronger password for this account.",
            }.get(code, "Supabase authentication failed. Check your credentials or project Auth settings.")
            raise HTTPException(429 if result.status_code == 429 else 401 if result.status_code in {400, 401, 403, 422} else 503, message)
        if path.startswith("/rest/v1/") and code == "PGRST205":
            table = path.split("?", 1)[0].removeprefix("/rest/v1/").split("/", 1)[0]
            raise HTTPException(503, f"Supabase table '{table}' is missing. Run Backend/supabase/schema.sql in this project's SQL Editor.")
        if path.startswith("/rest/v1/") and code == "PGRST204":
            if path.startswith("/rest/v1/csv_uploads") and "currency" in str(body.get("message", "")):
                raise HTTPException(503, "Supabase is missing the CSV currency column. Run Backend/supabase/schema.sql in this project's SQL Editor, then reload the PostgREST schema cache.")
            raise HTTPException(503, "Supabase could not find a requested database column. Run Backend/supabase/schema.sql in this project's SQL Editor, then reload the PostgREST schema cache.")
        if path.startswith("/storage/") and result.status_code == 404:
            raise HTTPException(503, f"Supabase CSV bucket '{config.SUPABASE_CSV_BUCKET}' or object was not found. Run Backend/supabase/schema.sql and check the bucket name.")
        if result.status_code in {401, 403}:
            raise HTTPException(403, "Supabase denied access. Check the database and Storage policies from supabase/schema.sql.")
        if result.status_code == 409:
            raise HTTPException(409, "This record already exists.")
        scope = "Storage" if path.startswith("/storage/") else "database"
        detail = f"Supabase {scope} request failed (HTTP {result.status_code}"
        if isinstance(code, str) and code.isascii() and code.replace("_", "").isalnum() and len(code) <= 40:
            detail += f", code {code}"
        raise HTTPException(502, detail + "). Check Backend/supabase/schema.sql and the project settings.")
    if result.status_code == 204 or not result.content:
        return None
    return result


def json_request(method, path, token=None, **kwargs):
    result = request(method, path, token, **kwargs)
    return result.json() if result is not None else None


def public_user(user):
    return {"id": user["id"], "email": user.get("email", ""),
            "full_name": user.get("user_metadata", {}).get("full_name", "Auditor")}


def set_cookies(response: Response, session):
    for name, value in [(ACCESS_COOKIE, session["access_token"]), (REFRESH_COOKIE, session["refresh_token"])]:
        response.set_cookie(name, value, max_age=30 * 86400, path="/", httponly=True,
                            secure=config.COOKIE_SECURE, samesite="lax")
    response.headers["Cache-Control"] = "no-store"


def signup(full_name, email, password, response):
    session = json_request("POST", "/auth/v1/signup", json={"email": email, "password": password,
                           "data": {"full_name": full_name.strip()}})
    if session.get("access_token"):
        set_cookies(response, session)
        return {"user": public_user(session["user"])}
    return {"user": None, "requires_confirmation": True,
            "message": "Check your email to confirm your account, then sign in."}


def login(email, password, response):
    session = json_request("POST", "/auth/v1/token?grant_type=password", json={"email": email, "password": password})
    set_cookies(response, session)
    return {"user": public_user(session["user"])}


def current_user(request_obj, response):
    token = request_obj.cookies.get(ACCESS_COOKIE)
    refresh = request_obj.cookies.get(REFRESH_COOKIE)
    if token:
        try:
            user = json_request("GET", "/auth/v1/user", token)
            return {**public_user(user), "_access_token": token}
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
    if refresh:
        session = json_request("POST", "/auth/v1/token?grant_type=refresh_token", json={"refresh_token": refresh})
        set_cookies(response, session)
        return {**public_user(session["user"]), "_access_token": session["access_token"]}
    raise HTTPException(401, "Sign in to continue.")


def logout(request_obj, response):
    token = request_obj.cookies.get(ACCESS_COOKIE)
    if token:
        try:
            request("POST", "/auth/v1/logout?scope=local", token)
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        response.delete_cookie(name, path="/", httponly=True, samesite="lax")


def store_csv(user, metadata, content):
    token = user["_access_token"]
    path = metadata["object_path"]
    request("POST", f"/storage/v1/object/{quote(config.SUPABASE_CSV_BUCKET)}/{quote(path, safe='/')}", token,
            content=content, headers={"Content-Type": "text/csv", "x-upsert": "false"})
    try:
        json_request("POST", "/rest/v1/csv_uploads", token, json={**metadata, "user_id": user["id"]})
    except HTTPException:
        # Best-effort cleanup of an object that never acquired metadata.
        try:
            request("DELETE", f"/storage/v1/object/{quote(config.SUPABASE_CSV_BUCKET)}", token, json={"prefixes": [path]})
        except HTTPException:
            pass
        raise


def load_csv(user, source_id):
    rows = json_request("GET", "/rest/v1/csv_uploads", user["_access_token"],
                        params={"id": f"eq.{source_id}", "user_id": f"eq.{user['id']}", "select": "*"})
    if not rows:
        raise HTTPException(404, "CSV source not found.")
    metadata = rows[0]
    result = request("GET", f"/storage/v1/object/authenticated/{quote(config.SUPABASE_CSV_BUCKET)}/{quote(metadata['object_path'], safe='/')}", user["_access_token"])
    return metadata, result.content


def save_audit(user, payload):
    snapshot = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    row = {key: payload.get(key) for key in ("budget_name", "original_filename", "record_count", "declared_total",
           "calculated_total", "difference", "discrepancy_count", "data_quality_count", "review_suggestion_count", "reconciliation_status")}
    row.update(id=f"AUD-{uuid.uuid4().hex[:16].upper()}", user_id=user["id"],
               created_at=datetime.now(timezone.utc).isoformat(), snapshot_json=snapshot,
               snapshot_sha256=hashlib.sha256(snapshot.encode()).hexdigest(), source_ids=payload.get("source_ids", []))
    json_request("POST", "/rest/v1/audits", user["_access_token"], json=row)
    return {key: value for key, value in row.items() if key != "snapshot_json"}


SUMMARY_COLUMNS = "id,user_id,budget_name,original_filename,created_at,record_count,declared_total,calculated_total,difference,discrepancy_count,data_quality_count,review_suggestion_count,reconciliation_status,snapshot_sha256,source_ids"


def list_audits(user):
    rows, offset = [], 0
    while True:
        page = json_request("GET", "/rest/v1/audits", user["_access_token"], params={
            "user_id": f"eq.{user['id']}", "select": SUMMARY_COLUMNS, "order": "created_at.desc,id.desc", "limit": 500, "offset": offset})
        rows.extend(page)
        if len(page) < 500:
            return rows
        offset += 500


def get_audit(user, audit_id):
    rows = json_request("GET", "/rest/v1/audits", user["_access_token"],
                        params={"id": f"eq.{audit_id}", "user_id": f"eq.{user['id']}", "select": "*"})
    if not rows:
        raise HTTPException(404, "Audit report not found.")
    row = rows[0]
    snapshot = row.pop("snapshot_json")
    if not hmac.compare_digest(hashlib.sha256(snapshot.encode()).hexdigest(), row["snapshot_sha256"]):
        raise HTTPException(500, "Audit evidence integrity check failed.")
    return {**row, "analysis": json.loads(snapshot)}
