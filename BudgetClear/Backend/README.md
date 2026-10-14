# BudgetClear backend

The [main guide](../../README.md) covers the complete setup and the [live website](https://budgetclear-frontend.vercel.app/).

This FastAPI backend handles auditor authentication, CSV ingestion, private source storage, background analysis jobs, and report history. `main.py` exposes the routes used by the current React frontend. `analyze.py` contains the anomaly detectors; `ai_explanations.py` optionally produces short, cited explanations. `services.py` selects local or Supabase persistence.

## Configuration

From `BudgetClear/Backend`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `BUDGETCLEAR_STORAGE_BACKEND=local` for SQLite and local uploads. For Supabase, run [`supabase/schema.sql`](supabase/schema.sql), then fill `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `SUPABASE_CSV_BUCKET` in `.env`. AI explanations additionally require `AI_BASE_URL`, `AI_API_KEY`, and `AI_MODEL`. Keep actual keys out of Git.

## Start locally

The current Vite configuration proxies most API requests to port 8000 and analysis requests to port 8001. Start the same `main:app` application on both ports in separate terminals:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

On Render, use root directory `BudgetClear/Backend`, build command `pip install -r requirements.txt`, and start command `uvicorn main:app --host 0.0.0.0 --port $PORT`.

The original CSVs are saved in the private Supabase bucket or `uploads/`; report snapshots are saved in Postgres or SQLite. The browser creates the Word findings document when an auditor downloads a report.
