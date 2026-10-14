# BudgetClear frontend

The [main guide](../../README.md) covers the complete setup. The public website is [budgetclear-frontend.vercel.app](https://budgetclear-frontend.vercel.app/).

This Vite, React, and TypeScript app contains the landing page, auditor sign-in, CSV upload and header mapping, evidence report, and audit history. `src/csvMapping.ts` normalizes uploaded headers. `src/reportDownload.ts` generates a Word document with only flagged findings and their reasons.

From `BudgetClear/Frontend`, install dependencies and start Vite:

```powershell
npm ci
npm run dev
```

Open the URL printed by Vite, normally `http://127.0.0.1:5173`. For a local production preview:

```powershell
npm run build
npm run preview
```

Open `http://127.0.0.1:4173`. The local Vite proxy uses backend ports 8000 and 8001; follow the [backend instructions](../Backend/README.md) to start them. Vercel uses root directory `BudgetClear/Frontend`, build command `npm run build`, output directory `dist`, and the rewrite in `vercel.json` to reach Render. Supabase and AI keys belong on the backend, never in this frontend.
