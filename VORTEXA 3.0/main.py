from fastapi import FastAPI, UploadFile, File, HTTPException
import pandas as pd
import io

app = FastAPI(title="BudgetClear Ingestion API")

@app.post("/api/v1/ingest")
async def ingest_and_reconcile(file: UploadFile = File(...)):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files allowed")
        
    # Stream the file into memory
    content = await file.read()
    df = pd.read_csv(io.BytesIO(content))
    
    # --- LAYER 1: DETERMINISTIC CHECKS ---
    
    # Check 1: Null Values
    null_rows = df[df.isnull().any(axis=1)]
    if not null_rows.empty:
        return {
            "status": "rejected", 
            "reason": "Deterministic Failure: Missing fields detected", 
            "error_count": len(null_rows),
            "failed_rows": null_rows['transaction_id'].tolist()
        }
    
    # Check 2: Mathematical Sanity
    if (df['amount'] < 0).any():
        return {
             "status": "rejected",
             "reason": "Deterministic Failure: Negative amounts detected"
        }
        
    # If the ledger is mathematically sound, it queues for Layer 2.
    return {
        "status": "success", 
        "message": f"Ledger structurally sound. {len(df)} rows queued for Probabilistic AI analysis."
    }