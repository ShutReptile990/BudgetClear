"""Shared configuration for both FastAPI processes. Secrets stay on the server."""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env", override=False)

STORAGE_BACKEND = os.getenv("BUDGETCLEAR_STORAGE_BACKEND", "local").lower()
if STORAGE_BACKEND not in {"local", "supabase"}:
    raise RuntimeError("BUDGETCLEAR_STORAGE_BACKEND must be local or supabase")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_CSV_BUCKET = os.getenv("SUPABASE_CSV_BUCKET", "budgetclear-csv")
COOKIE_SECURE = os.getenv("BUDGETCLEAR_COOKIE_SECURE", "0").lower() in {"1", "true", "yes"}
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024
MAX_LEDGER_ROWS = int(os.getenv("MAX_LEDGER_ROWS", "50000"))

AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
AI_MODEL = os.getenv("AI_MODEL", "")
AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "30"))
AI_TOTAL_TIMEOUT_SECONDS = float(os.getenv("AI_TOTAL_TIMEOUT_SECONDS", "120"))
AI_MAX_FLAGS = int(os.getenv("AI_MAX_FLAGS", "500"))
