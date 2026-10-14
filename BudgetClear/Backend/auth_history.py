"""Persistent user accounts, sessions, and immutable audit snapshots."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Cookie, HTTPException, Response


DB_PATH = Path(os.getenv("BUDGETCLEAR_DB_PATH", Path(__file__).with_name("budgetclear.sqlite3")))
SESSION_COOKIE = "budgetclear_session"
SESSION_DAYS = 30
PBKDF2_ROUNDS = 310_000


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def _db():
    connection = _connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with _db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS sessions_user_id ON sessions(user_id);
            CREATE TABLE IF NOT EXISTS audits (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                budget_name TEXT NOT NULL,
                original_filename TEXT,
                created_at TEXT NOT NULL,
                record_count INTEGER NOT NULL,
                declared_total TEXT,
                calculated_total TEXT,
                difference TEXT,
                discrepancy_count INTEGER NOT NULL,
                data_quality_count INTEGER NOT NULL,
                review_suggestion_count INTEGER NOT NULL,
                reconciliation_status TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                snapshot_sha256 TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS audits_user_created ON audits(user_id, created_at DESC);
            """
        )
        audit_columns = {row["name"] for row in db.execute("PRAGMA table_info(audits)")}
        if "snapshot_sha256" not in audit_columns:
            db.execute("ALTER TABLE audits ADD COLUMN snapshot_sha256 TEXT NOT NULL DEFAULT ''")
        db.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS audits_are_immutable_update
            BEFORE UPDATE ON audits BEGIN SELECT RAISE(ABORT, 'Audit records are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS audits_are_immutable_delete
            BEFORE DELETE ON audits BEGIN SELECT RAISE(ABORT, 'Audit records are immutable'); END;
            """
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(expected.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _user_payload(user: sqlite3.Row) -> dict[str, str]:
    return {"id": user["id"], "full_name": user["full_name"], "email": user["email"]}


def register_user(full_name: str, email: str, password: str) -> dict[str, str]:
    full_name, email = full_name.strip(), email.strip().lower()
    if len(full_name) < 2:
        raise HTTPException(status_code=422, detail="Enter your full name.")
    if len(password) < 10:
        raise HTTPException(status_code=422, detail="Password must be at least 10 characters.")
    user_id, created_at = secrets.token_hex(16), _now().isoformat()
    try:
        with _db() as db:
            db.execute(
                "INSERT INTO users(id, full_name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, full_name, email, _hash_password(password), created_at),
            )
            return _user_payload(db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from error


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    with _db() as db:
        db.execute(
            "INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (hashlib.sha256(token.encode()).hexdigest(), user_id, (now + timedelta(days=SESSION_DAYS)).isoformat(), now.isoformat()),
        )
    return token


def authenticate(email: str, password: str) -> tuple[dict[str, str], str]:
    with _db() as db:
        user = db.execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email.strip(),)).fetchone()
    if user is None or not _verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    return _user_payload(user), create_session(user["id"])


def get_current_user(budgetclear_session: str | None = Cookie(default=None)) -> dict[str, str]:
    if not budgetclear_session:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    token_hash = hashlib.sha256(budgetclear_session.encode()).hexdigest()
    with _db() as db:
        row = db.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?",
            (token_hash, _now().isoformat()),
        ).fetchone()
        if row is None:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
            raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.")
    return _user_payload(row)


def clear_session(response: Response, token: str | None) -> None:
    if token:
        with _db() as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=os.getenv("BUDGETCLEAR_COOKIE_SECURE", "0").lower() in {"1", "true", "yes"},
        samesite="lax",
        path="/",
    )


def save_audit(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    required = {"budget_name", "record_count", "analysis_result"}
    missing = required - payload.keys()
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing audit fields: {', '.join(sorted(missing))}")
    result = payload["analysis_result"]
    if not isinstance(result, dict):
        raise HTTPException(status_code=422, detail="analysis_result must be an object.")
    audit_id, created_at = f"AUD-{secrets.token_hex(8).upper()}", _now().isoformat()
    snapshot = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    snapshot_sha256 = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
    summary = (
        audit_id, user_id, str(payload["budget_name"])[:200], payload.get("original_filename"), created_at,
        max(0, int(payload["record_count"])), payload.get("declared_total"), payload.get("calculated_total"),
        payload.get("difference"), max(0, int(payload.get("discrepancy_count", 0))),
        max(0, int(payload.get("data_quality_count", 0))), max(0, int(payload.get("review_suggestion_count", 0))),
        str(payload.get("reconciliation_status", "completed"))[:80], snapshot, snapshot_sha256,
    )
    with _db() as db:
        db.execute(
            """INSERT INTO audits(id,user_id,budget_name,original_filename,created_at,record_count,declared_total,
               calculated_total,difference,discrepancy_count,data_quality_count,review_suggestion_count,
               reconciliation_status,snapshot_json,snapshot_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            summary,
        )
    return audit_summary_by_id(audit_id, user_id)


def _summary(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys() if key != "snapshot_json"}


def list_audits(user_id: str) -> list[dict[str, Any]]:
    with _db() as db:
        rows = db.execute("SELECT * FROM audits WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
    return [_summary(row) for row in rows]


def audit_summary_by_id(audit_id: str, user_id: str) -> dict[str, Any]:
    with _db() as db:
        row = db.execute("SELECT * FROM audits WHERE id = ? AND user_id = ?", (audit_id, user_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Audit report not found.")
    return _summary(row)


def get_audit(audit_id: str, user_id: str) -> dict[str, Any]:
    with _db() as db:
        row = db.execute("SELECT * FROM audits WHERE id = ? AND user_id = ?", (audit_id, user_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Audit report not found.")
    actual_hash = hashlib.sha256(row["snapshot_json"].encode("utf-8")).hexdigest()
    if not hmac.compare_digest(actual_hash, row["snapshot_sha256"]):
        raise HTTPException(status_code=500, detail="Audit evidence integrity check failed.")
    return {**_summary(row), "analysis": json.loads(row["snapshot_json"])}


initialize_database()
