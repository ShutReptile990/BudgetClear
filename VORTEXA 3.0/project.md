# Project Context

## Problem Statement
Standard financial audits rely on checking if rows and columns sum correctly—a vulnerability known as the "Excel Fallacy." Sophisticated bad actors ensure their fraudulent ledgers are mathematically balanced to evade detection. Traditional systems cannot detect behavioral, semantic, or structural fraud, such as illicit luxury items hidden within massive "Office Supplies" categories, slightly altered duplicate invoice numbers, or intentional payment splitting (smurfing) to bypass mandatory oversight thresholds. 

## Proposed Solution
**BudgetClear (G-03)**: A bifurcated, dual-engine forensic auditing architecture. 
1. **Layer 1 (Deterministic Engine):** Enforces strict mathematical truth by immediately rejecting flat files with broken formulas, truncation, or missing fields.
2. **Layer 2 (Probabilistic AI Engine):** Analyzes mathematically sound data using NLP, statistical distributions, and fuzzy string matching to surface behavioral anomalies. It outputs a prioritized "Unified Evidence Report" with strict legal disclaimers, directing human auditors to the highest-probability fraud vectors rather than relying on random sampling.

## Tech Stack
* **Backend:** FastAPI, Python 3.10+
* **Frontend:** Streamlit
* **Data Processing:** Pandas, NumPy
* **AI / Machine Learning:** 
  * `sentence-transformers` (Hugging Face `all-MiniLM-L6-v2`) for embeddings.
  * `faiss-cpu` for high-dimensional vector similarity search.
  * `recordlinkage` for fuzzy string matching.
  * `scipy` for statistical testing (Benford's Law Mean Absolute Deviation test).

## Must-Have Features
* **P0 - Deterministic Ingestion Pipeline:** API endpoint that streams CSVs into memory and hard-fails if null values or negative amounts exist.
* **P0 - Category Camouflage Detection:** SBERT + FAISS module to identify semantic mismatches between invoice free-text descriptions and their assigned budget categories.
* **P0 - Threshold Dodging Detection:** Benford's Law implementation utilizing the Mean Absolute Deviation (MAD) test to catch probability spikes directly below audit limits (e.g., $9,900).
* **P0 - Fuzzy Duplicate Identification:** Locality-Sensitive Hashing (LSH) and Jaro-Winkler distance to catch perturbed invoice strings (e.g., `INV-101` vs `INV-101-A`).
* **P0 - Unified Evidence Dashboard:** Streamlit UI displaying a prioritized anomaly queue and the mandatory human-review disclaimer.

## Optional Features
* **P1 - Over-Invoicing / Kickback Detection:** XGBoost Quantile Regression to predict dynamic 95th-percentile market price ceilings for standard SKUs.
* **P2 - Shell Company Network Mapping:** Graph Neural Networks (GNNs) and Louvain Community Detection to expose hidden vendor loops.
* **P2 - Tamper-Evident Audit Log:** SQLite append-only backend with SHA-256 cryptographic hashing to prevent silent ledger overwrites.

## API Contracts
* **`POST /api/v1/ingest`**
  * **Payload:** `multipart/form-data` (CSV file)
  * **Response (Success):** `200 OK` `{ "status": "success", "message": "Ledger structurally sound. Queued for AI." }`
  * **Response (Fail):** `400 Bad Request` `{ "status": "rejected", "reason": "Missing fields detected", "failed_rows": [...] }`

* **`POST /api/v1/analyze`**
  * **Payload:** JSON array of parsed transaction records.
  * **Response:** JSON array of flagged anomalies detailing `transaction_id`, `scheme_detected`, `confidence_score`, and `rationale`.

## Database Schema
*(For PoC, data is handled in-memory via Pandas DataFrames. Below is the strict CSV/DataFrame schema expected by the API).*
* `transaction_id` (String) - Unique identifier
* `date` (Date/String, YYYY-MM-DD) - Transaction date
* `vendor` (String) - Name of the payee
* `category` (String) - Broad budget classification (e.g., "IT Infrastructure")
* `description` (String) - Free-text item description
* `amount` (Float) - Disbursed amount
* `invoice_number` (String) - Vendor-provided invoice ID

## Development Rules
- Do not change the architecture without approval.
- Do not create fake completed functionality.
- Do not modify unrelated files.
- Prefer minimal dependencies.
- Keep API keys in environment variables.
- Run build/tests after implementation.
- Report changed files and test results.

## Demo Flow
1. **Dataset Generation:** Run `generate_dataset.py` to create the synthetic, rigged CSV containing exactly 508 rows (500 normal, 8 fraudulent).
2. **Deterministic Rejection:** Open Streamlit UI. Upload the rigged CSV. The FastAPI backend instantly rejects the file, displaying an error that Row `TX-9998` is missing a Vendor Name. 
3. **Correction & Re-upload:** Remove the intentionally corrupted row to demonstrate the "Excel Fallacy" defense. Re-upload the structurally sound CSV. The API accepts it.
4. **AI Analysis Execution:** Click "Run Probabilistic Audit" in the UI.
5. **Surfacing Category Camouflage:** The UI surfaces `TX-9991` (Sony PlayStation 5 hidden in "General Logistics") with a 90%+ SBERT outlier score.
6. **Surfacing Smurfing:** The UI flags the four consecutive $9,900 payments to `Consulting_LLC` due to a Benford's Law MAD test violation.
7. **Surfacing Fuzzy Duplicates:** The UI links `INV-777` and `INV-777-A` side-by-side, proving standard SQL `UNIQUE` constraints would have missed the duplicate payment.
8. **Compliance Sign-Off:** Point the judges to the mandatory disclaimer permanently affixed to the bottom of the screen: *"An anomaly flag is a statistical deviation, not proof of fraud."*