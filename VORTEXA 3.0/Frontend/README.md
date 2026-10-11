# BudgetClear frontend

The React + TypeScript app lives in `src/`. Build it once before using Vite preview.

```powershell
cd "C:\path\to\VORTEXA 3.0\Frontend"
pnpm install
pnpm build
pnpm preview
```

Open `http://127.0.0.1:4173`. For live development, use `pnpm dev` instead of `pnpm preview`.

Start both FastAPI processes first (see `../Backend/README.md`). Vite proxies ingestion and authentication/history requests to port 8000, and analysis requests to port 8001. Create a real auditor account through **Create an account**; there are no demo credentials. Select one or more CSV files with **Browse CSV files**. Selection stages and parses files in your browser; clicking **Run ingestion & checks** sends each original CSV to the FastAPI ingestion endpoint.

AI and Supabase configuration belongs only in `Backend/.env`; no frontend API keys or additional layout changes are required. Follow `../Backend/INTEGRATION_SETUP.md`. The existing confidence column and evidence drawer display detector scores, AI/detector explanations, source record citations, and original CSV downloads. Source downloads proxy to port 8000 and require the signed-in owner.
