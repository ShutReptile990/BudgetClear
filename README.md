# BudgetClear (G-03)

BudgetClear is an evidence-led audit workspace for government spending CSVs. It validates ledger structure, flags unusual transactions for human review, and links each finding to its uploaded source record. A balanced total alone cannot establish that every payment is appropriate.

**Live website:** [budgetclear-frontend.vercel.app](https://budgetclear-frontend.vercel.app/)  
**GitHub repository:** [ShutReptile990/BudgetClear](https://github.com/ShutReptile990/BudgetClear)

Anyone can open the website. Creating an audit requires an auditor account. A confidence score measures detector signal strength, **not the probability of fraud**. Every flag requires human review.

## Features

- **CSV preparation:** Upload one or more CSVs. Common alternative headers are recognized automatically; unmatched fields can be mapped manually. Row IDs can be generated, category can be set to `Uncategorized`, and absent invoice numbers can be marked as such. DWP expenditure disclosures and Windows-1252 encoding are supported.
- **User-selected currency:** Choose USD, GBP, INR, or EUR for an audit. Run different currencies as separate audits.
- **Deterministic validation:** Reject missing required values, invalid amounts, and negative amounts outside the DWP adjustment format. Original CSV bytes are retained with a SHA-256 hash.
- **Anomaly analysis:** FastEmbed's ONNX MiniLM embeddings and FAISS find category outliers. Benford mean absolute deviation and fuzzy invoice matching run when the data supports them. A background analysis job is polled by the frontend.
- **Evidence-linked findings:** Flags include transaction IDs, confidence scores, reasons, score bases, and cited source records. An optional OpenAI-compatible model writes a short explanation from detector evidence; detector reasons remain available if AI is unavailable.
- **Private history:** Supabase Auth, Postgres, private Storage, and row-level policies can persist accounts, original CSVs, and report snapshots. Local SQLite and upload storage are available for development.
- **Word report:** The `.docx` download contains a table of flagged findings only: transaction ID, finding and score, why it was flagged, and cited source-record references. It is generated in the browser from the report snapshot.

The app does **not** currently parse Excel formulas, prove CSV truncation, or reconcile totals against an external declared budget. Its flags are review suggestions, not proof of wrongdoing.

## Repository structure

The repository and product are named **BudgetClear**. The deployed application directory has also been renamed to `BudgetClear`:

```text
BudgetClear/                         # cloned Git repository
├── README.md                        # this guide
└── BudgetClear/                     # deployed application directory
    ├── Backend/
    │   ├── main.py                  # auth, ingestion, analysis jobs, reports
    │   ├── analyze.py               # anomaly detectors
    │   ├── ai_explanations.py       # optional cited AI reasons
    │   ├── ledger_import.py         # CSV import and normalization
    │   ├── services.py              # storage selection
    │   ├── supabase_store.py        # Supabase integration
    │   ├── supabase/schema.sql      # tables, bucket, and policies
    │   ├── .env.example             # backend configuration template
    │   └── requirements.txt
    └── Frontend/
        ├── src/App.tsx              # React pages and audit flow
        ├── src/csvMapping.ts        # CSV header mapping
        ├── src/reportDownload.ts    # Word findings export
        ├── public/                  # static files and DWP example CSV
        ├── package.json
        ├── package-lock.json
        ├── vite.config.js           # local API proxies
        └── vercel.json              # production API rewrite
```

## Run locally on Windows

Use Python 3.11 or newer, Node.js 20 or newer, and PowerShell. Start from a fresh clone:

```powershell
git clone https://github.com/ShutReptile990/BudgetClear.git
cd BudgetClear
```

### 1. Configure the backend

```powershell
cd .\BudgetClear\Backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `BudgetClear/Backend/.env`. For a local run without Supabase:

```dotenv
BUDGETCLEAR_STORAGE_BACKEND=local
BUDGETCLEAR_COOKIE_SECURE=0
```

For Supabase storage, run the complete [`schema.sql`](BudgetClear/Backend/supabase/schema.sql) in **your Supabase project's SQL Editor**, enable Email authentication, then set:

```dotenv
BUDGETCLEAR_STORAGE_BACKEND=supabase
SUPABASE_URL=https://YOUR-PROJECT.supabase.co
SUPABASE_ANON_KEY=YOUR_ANON_OR_PUBLISHABLE_KEY
SUPABASE_CSV_BUCKET=budgetclear-csv
```

Confirm your email before signing in if the Supabase project requires it. Keep the bucket private. Backend keys stay in `.env` and must not be committed or placed in the frontend.

For optional generated explanations, configure an OpenAI-compatible Chat Completions provider and model that support JSON mode:

```dotenv
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=YOUR_PROVIDER_KEY
AI_MODEL=YOUR_AVAILABLE_MODEL_ID
```

Detector explanations work without these AI values. The first semantic analysis may download the MiniLM ONNX model.

### 2. Start the APIs

Open two PowerShell terminals at the repository root. The current Vite configuration sends general API calls to port 8000 and analysis calls to port 8001. Start `main:app` on **both** ports because it exposes the background analysis routes:

```powershell
# Terminal 1, from the repository root
cd .\BudgetClear\Backend
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
# Terminal 2, from the repository root
cd .\BudgetClear\Backend
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

API documentation is available at `http://127.0.0.1:8000/docs`. Restart the APIs after changing `.env`.

### 3. Start the frontend

In a third PowerShell terminal at the repository root:

```powershell
cd .\BudgetClear\Frontend
npm ci
npm run dev
```

Open the URL Vite prints, normally `http://127.0.0.1:5173`. For a production-style local preview, run `npm run build` then `npm run preview` and open `http://127.0.0.1:4173`.

## Run an audit

1. Sign up or sign in and open **New audit**.
2. Choose a currency, then select or drag one or more CSVs.
3. Review staged row counts and map any unmatched headers to BudgetClear fields.
4. Click **Run ingestion & checks**. The site validates and stores the CSVs, starts analysis, and saves the report.
5. Open a flag for its reason, confidence basis, and cited records. Use **Download report** for the Word findings table, or **Audit history** to reopen a saved report.

Canonical CSV fields are:

```csv
transaction_id,date,vendor,category,description,amount,invoice_number
TX-001,2026-04-01,Example Supplier,Office Supplies,Printer paper,2500.00,INV-001
```

Other header names work through automatic or manual mapping. Dates in `YYYY-MM-DD` form and numeric amounts are recommended. When invoices are unavailable, choose **No invoice column**; fuzzy invoice matching then has no invoice evidence to compare. DWP files use their published disclosure columns and may include negative adjustment rows.

Default limits are 20 MB per file, 50 source files, and 50,000 records per audit. Raising the upload limit also requires a matching Supabase bucket limit.

## Deployment

- **Frontend:** Vercel serves `BudgetClear/Frontend`. Build with `npm run build` and publish `dist`. [`vercel.json`](BudgetClear/Frontend/vercel.json) forwards `/api/v1/*` to Render.
- **Backend:** Render serves `BudgetClear/Backend`. Build with `pip install -r requirements.txt` and start with `uvicorn main:app --host 0.0.0.0 --port $PORT`.
- **Environment:** Put Supabase and optional AI values in the **Render service** environment variables. Set `BUDGETCLEAR_COOKIE_SECURE=1` for HTTPS. The frontend needs no server secrets.
- **After the directory rename:** Update the **Root Directory** in both hosting projects to the new paths above before redeploying. The public website URL remains [budgetclear-frontend.vercel.app](https://budgetclear-frontend.vercel.app/).

Render is an API service; visiting its root path can return `{"detail":"Not Found"}`. Use the Vercel URL for the website.

## Key API routes

- `POST /api/v1/auth/signup`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`, `POST /api/v1/auth/logout`
- `POST /api/v1/ingest` and `GET /api/v1/sources/{source_id}/download`
- `POST /api/v1/analyze/start` and `GET /api/v1/analyze/jobs/{job_id}` for background analysis
- `GET /api/v1/audits`, `POST /api/v1/audits`, `GET /api/v1/audits/{audit_id}` for report history

Authenticated routes use HttpOnly cookies. Report snapshots store normalized transactions and cited findings; original CSV bytes are stored separately in private Storage or local uploads.

## Troubleshooting

- **404 during analysis:** Ensure both local ports run `main:app`, or check that Vercel's `/api/v1/*` rewrite points to the active Render service.
- **502 during analysis:** Check Render runtime logs for a restart, memory event, or model download error. Background jobs avoid one long Vercel proxy request, but a job is lost if its Render instance restarts.
- **Supabase table or currency-column error:** Run the complete [`schema.sql`](BudgetClear/Backend/supabase/schema.sql) in the correct Supabase project and reload its PostgREST schema cache.
- **Storage error:** Check the private `budgetclear-csv` bucket, its policies, and `SUPABASE_CSV_BUCKET`.
- **AI explanation unavailable:** Check the provider URL, key, model, quota, and JSON-mode support. Detector reasons remain visible.
- **A deployment-specific Vercel URL shows older behavior:** Use the stable production URL linked at the top; deployment URLs do not change after a new push.

For further detail, see [backend setup](BudgetClear/Backend/README.md) and [frontend setup](BudgetClear/Frontend/README.md).
