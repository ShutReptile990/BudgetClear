# AI and Supabase setup

The existing React screens and two FastAPI servers are retained. Both servers load `Backend/.env` automatically. The editable `.env` has been created with empty credentials; `.env.example` is the template. Environment variables set in your terminal take precedence. Restart both servers after changing configuration.

## 1. Prepare Supabase

1. Create or open your Supabase project.
2. Open **SQL Editor**, paste the contents of `Backend/supabase/schema.sql`, and run it. This creates `csv_uploads`, `audits`, a private `budgetclear-csv` bucket, and access policies for the signed-in owner. Run this before trying to upload a file.
3. In **Authentication**, enable the Email provider. Set **URL Configuration > Site URL** to `http://127.0.0.1:4173` for Vite preview, or your actual development/production URL. Add the same URL to allowed redirect URLs if your configuration requires it.
4. Keep email confirmation enabled if you want verified accounts. Signup then displays a confirmation message in the existing form; after following the email link, return to the sign-in page and sign in. For a local demo, you can disable Confirm Email in Supabase to sign in immediately after signup.
5. From project settings, copy the project URL and **anon** key (the newer **publishable** key also works) into `Backend/.env`:

   ```dotenv
   BUDGETCLEAR_STORAGE_BACKEND=supabase
   SUPABASE_URL=https://YOUR-PROJECT.supabase.co
   SUPABASE_ANON_KEY=YOUR_ANON_OR_PUBLISHABLE_KEY
   SUPABASE_CSV_BUCKET=budgetclear-csv
   ```

No service-role key is needed. Requests use the auditor's Supabase session, so database and Storage row-level security remain active. Passwords are handled by Supabase Auth. Tokens are stored in HttpOnly cookies, and expired access tokens are refreshed by the backend. Credentials and provider keys are never returned to the React app.

If you change the bucket name, update both `.env` and all bucket references in the SQL script. Keep the bucket private. Its upload limit defaults to 20 MB; changing `MAX_UPLOAD_MB` also requires updating the bucket limit in Supabase.

## 2. Configure AI explanations

Paste these into the same `Backend/.env`:

```dotenv
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=YOUR_AI_API_KEY
AI_MODEL=YOUR_PROVIDER_MODEL_ID
```

The integration uses the OpenAI-compatible **Chat Completions** protocol with JSON mode. The base URL should end before `/chat/completions`. If using another compatible provider, use that provider's base URL and a model supporting `response_format: {"type":"json_object"}`. Native APIs with a different protocol require an adapter. No model ID is assumed; enter one available to your account.

Only each flag's measurements and supporting record samples are sent for explanation. Transaction descriptions, vendors, invoice details and amounts in those samples are sent to the configured AI provider. The model returns a short rationale plus evidence IDs. Unknown citations, missing required records, malformed output, and overly long explanations are rejected. The model cannot change the detector's confidence score. Citation validation checks record references, not the factual correctness of every generated sentence; the auditor still reviews the evidence.

Missing keys, unavailable models, provider errors, timeouts, or flags beyond `AI_MAX_FLAGS` retain a detector explanation. The report labels these as detector explanations and shows the fallback reason. The default limit is 500 AI explanations per audit, with a 120-second total explanation budget. Every flag retains source evidence even when AI is unavailable.

## 3. Install dependencies and restart

From PowerShell, install the backend requirements:

```powershell
cd "C:\Users\nalad\Desktop\VORTEXA 3.0\VORTEXA 3.0\Backend"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Start the API processes in two separate terminals:

```powershell
cd "C:\Users\nalad\Desktop\VORTEXA 3.0\VORTEXA 3.0\Backend"
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

```powershell
cd "C:\Users\nalad\Desktop\VORTEXA 3.0\VORTEXA 3.0\Backend"
.\.venv\Scripts\python.exe -m uvicorn analyze:app --reload --port 8001
```

In a third terminal:

```powershell
cd "C:\Users\nalad\Desktop\VORTEXA 3.0\VORTEXA 3.0\Frontend"
pnpm build
pnpm preview
```

Open `http://127.0.0.1:4173`. Use `pnpm dev` for live development. Vite proxies `/api/v1/sources` along with authentication, ingestion, and history to port 8000; analysis goes to port 8001. Deployment needs equivalent reverse-proxy routes. Set `BUDGETCLEAR_COOKIE_SECURE=1` when using HTTPS.

## Stored data and evidence

- **Supabase Auth:** auditor accounts, password credentials, and auth sessions. Full name is user metadata.
- **Private Storage / budgetclear-csv:** original uploaded bytes under `<user-id>/<source-id>.csv`.
- **public.csv_uploads:** original filename, user ID, object path, byte size, record count, and SHA-256.
- **public.audits:** complete report JSON, confidence scores, explanations, linked evidence, source IDs, and the report SHA-256. Reports are in Postgres; they do not require a second Storage bucket.

Upload happens when **Run ingestion & checks** is pressed. A successfully ingested CSV remains stored even if analysis or report saving later fails. Analysis reloads the stored file, verifies its hash, and creates evidence IDs from the source UUID and record ordinal. A CSV record number counts data records after the header; it is not a physical line number when quoted cells span lines. Original downloads require the owner's authenticated session.

Click **View evidence** or a transaction ID in the existing report queue. The existing drawer shows the score basis, short reason, linked record references, source fields, and **Download original CSV**. JSON downloads and reopened reports retain all this information. Old reports created before this integration retain their original content and have no retroactive source downloads or AI explanations.

Confidence is a 0–100 detector signal score, not a calibrated probability of fraud: semantic cosine distance × 100 (capped), invoice Jaro-Winkler similarity × 100, or Benford MAD / 0.10 × 100 (capped). The basis is attached to every new flag. Benford checks require at least 100 positive transactions, and DWP threshold-selected disclosures remain excluded from Benford and invoice checks.

For the previous local setup, set `BUDGETCLEAR_STORAGE_BACKEND=local`. Existing SQLite accounts/reports remain available in that mode, and new original uploads are saved in `Backend/uploads/<user-id>/`. Switching to Supabase does not migrate the existing local accounts or reports; create a Supabase account to use cloud mode. The code does not silently fall back to SQLite on a Supabase error.

## Validation

Offline integration checks use temporary SQLite data and mocked external HTTP responses:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

After adding real credentials and running SQL, complete a new signup/login, upload a CSV, open a flag, download its original source, and reopen the report from history. Offline tests do not validate a live Supabase project's policies or a provider's model availability.

Official API references: [Supabase password authentication](https://supabase.com/docs/guides/auth/passwords), [Supabase private Storage access control](https://supabase.com/docs/guides/storage/security/access-control), [Supabase sessions](https://supabase.com/docs/guides/auth/sessions), and [Chat Completions API](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).
