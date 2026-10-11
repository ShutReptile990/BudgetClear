# Backend setup

The backend provides two FastAPI applications. First follow [AI and Supabase setup](INTEGRATION_SETUP.md): fill `.env` and run `supabase/schema.sql`, or set `BUDGETCLEAR_STORAGE_BACKEND=local` to use the previous local accounts. Start each from this directory in its own terminal:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

```powershell
.\.venv\Scripts\python.exe -m uvicorn analyze:app --reload --port 8001
```

The analysis app downloads `all-MiniLM-L6-v2` on its first semantic analysis if not cached. The DWP disclosure importer accepts Windows-1252 encoding and preserves negative adjustments. Because this file is selected by a £25,000 reporting threshold and has no invoice IDs, Benford and fuzzy invoice checks are skipped for it.

## Accounts and audit history

Supabase mode uses Auth for accounts, private Storage for original CSVs, and Postgres for report snapshots. Local mode uses `budgetclear.sqlite3` and `uploads/`. Source downloads, ingestion, and analysis require an authenticated owner. Signup supports Supabase email confirmation. Both modes retain per-record evidence IDs and SHA-256 checks. See `INTEGRATION_SETUP.md` for configuration, scores, AI fallback behavior, and storage locations.
