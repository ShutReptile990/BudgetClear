# BudgetClear

BudgetClear pairs deterministic ledger pre-flight checks with probabilistic anomaly review. Supabase integration stores accounts, original CSV evidence, and completed reports. See [AI and Supabase setup](Backend/INTEGRATION_SETUP.md) to fill `Backend/.env` and run the database schema. Local SQLite mode remains available.

## Run locally on Windows

Open three PowerShell terminals.

1. Start the ingestion, authentication, and audit-history API:

   ```powershell
   cd "C:\path\to\VORTEXA 3.0\Backend"
   .\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
   ```

2. Start the AI analysis API in a second terminal:

   ```powershell
   cd "C:\path\to\VORTEXA 3.0\Backend"
   .\.venv\Scripts\python.exe -m uvicorn analyze:app --reload --port 8001
   ```

   The first semantic analysis downloads `all-MiniLM-L6-v2` if it is not cached.

3. Build and serve the frontend in a third terminal:

   ```powershell
   cd "C:\path\to\VORTEXA 3.0\Frontend"
   pnpm install
   pnpm build
   pnpm preview
   ```

   Open `http://127.0.0.1:4173`. Use `pnpm dev` instead of `pnpm preview` for live development.

4. Choose **Create an account** and register an auditor account. There are no demo credentials. Confirm your email if requested by Supabase. After signing in, browse for your CSV and run the audit. Use **View evidence** for each flag's explanation and original source, and **Audit history** to reopen saved reports.

## Persistence and configuration

`Backend/.env` selects Supabase or local storage and configures the AI provider. In Supabase mode, accounts use Supabase Auth, originals use private Storage, and reports use Postgres. In local mode, the API creates `Backend/budgetclear.sqlite3` and preserves originals under `Backend/uploads/`. Set `BUDGETCLEAR_COOKIE_SECURE=1` when using HTTPS; use `0` for local HTTP. Existing local data is not automatically migrated to Supabase.

The frontend proxy routes ingestion, source downloads, authentication, and history to port 8000, and analysis to port 8001. The editable React/TypeScript source lives in `Frontend/src/`.

## Known scope limits

The current ingestion API checks required fields and negative amounts (with the DWP adjustment exception). It does not calculate Excel `SUM()` formulas, truncation signatures, or category-wise declared totals. Confidence scores describe detector signal strength and require human review. AI explanations use validated evidence references and fall back to labeled detector explanations when the external API is unavailable.
