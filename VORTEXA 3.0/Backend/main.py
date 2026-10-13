from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Response, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
import re
import config
import services
from services import get_current_user
from urllib.parse import quote
import pandas as pd
from ledger_import import read_ledger, invalid_rows

app = FastAPI(title="BudgetClear Ingestion API")


class Registration(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=256)


class Credentials(BaseModel):
    email: str
    password: str


class AuditSubmission(BaseModel):
    source_ids: list[str] = Field(min_length=1, max_length=50)
    budget_name: str = Field(min_length=1, max_length=200)
    record_count: int = Field(ge=0)
    analysis_result: dict
    original_filename: str | None = None
    declared_total: str | None = None
    calculated_total: str | None = None
    difference: str | None = None
    discrepancy_count: int = Field(default=0, ge=0)
    data_quality_count: int = Field(default=0, ge=0)
    review_suggestion_count: int = Field(default=0, ge=0)
    reconciliation_status: str = "completed"


class AnalysisSubmission(BaseModel):
    source_ids: list[str] = Field(min_length=1, max_length=50)


def _validate_email(email: str) -> str:
    email = email.strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    return email


@app.post("/api/v1/auth/signup")
def signup(data: Registration, response: Response):
    return services.signup(data.full_name, _validate_email(data.email), data.password, response)


@app.post("/api/v1/auth/login")
def login(data: Credentials, response: Response):
    return services.login(_validate_email(data.email), data.password, response)


@app.get("/api/v1/auth/me")
def auth_me(user: dict = Depends(get_current_user)):
    return {"user": {k: v for k, v in user.items() if not k.startswith("_")}}


@app.post("/api/v1/auth/logout")
def logout(request: Request, response: Response):
    services.logout(request, response)
    return {"status": "success"}


@app.get("/api/v1/audits")
def audit_history(user: dict = Depends(get_current_user)):
    return {"audits": services.list_audits(user)}


@app.post("/api/v1/analyze")
async def analyze_uploaded_sources(data: AnalysisSubmission, user: dict = Depends(get_current_user)):
    from analyze import analyze_ledger
    return await analyze_ledger(data, user)


@app.post("/api/v1/audits", status_code=201)
def create_audit(data: AuditSubmission, user: dict = Depends(get_current_user)):
    return services.save_audit(user, data.model_dump())


@app.get("/api/v1/audits/{audit_id}")
def historical_audit(audit_id: str, user: dict = Depends(get_current_user)):
    return services.get_audit(user, audit_id)


@app.get("/api/v1/audits/{audit_id}/download")
def download_historical_audit(audit_id: str, response: Response, user: dict = Depends(get_current_user)):
    report = services.get_audit(user, audit_id)
    result = JSONResponse(
        content=report,
        headers={"Content-Disposition": f'attachment; filename="{audit_id}.json"'},
    )
    result.raw_headers.extend((key, value) for key, value in response.raw_headers if key == b"set-cookie")
    return result

@app.post("/api/v1/ingest")
async def ingest_and_reconcile(file: UploadFile = File(...), currency: str = Form(...), user: dict = Depends(get_current_user)):
    if not (file.filename or '').lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files allowed")
        
    # Stream the file into memory
    content = await file.read(config.MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"CSV files must be at most {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    try:
        df = read_ledger(content, currency)
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=400, detail=str(error))
    if len(df) > config.MAX_LEDGER_ROWS:
        raise HTTPException(413, f"CSV files must contain at most {config.MAX_LEDGER_ROWS} records.")
    
    # --- LAYER 1: DETERMINISTIC CHECKS ---
    
    # Check 1: Null Values
    null_rows = invalid_rows(df)
    if not null_rows.empty:
        return {
            "status": "rejected", 
            "reason": "Deterministic Failure: Missing fields detected", 
            "error_count": len(null_rows),
            "failed_rows": null_rows['transaction_id'].tolist()
        }
    
    # Check 2: Mathematical Sanity
    dwp = df.get('source_format', pd.Series('', index=df.index)).eq('dwp')
    if ((df['amount'] < 0) & ~dwp).any():
        return {
             "status": "rejected",
             "reason": "Deterministic Failure: Negative amounts detected"
        }
        
    source = await run_in_threadpool(services.store_source, user, file.filename, content, len(df), currency.upper())
    return {
        "status": "success", 
        "message": f"Ledger structurally sound. {len(df)} rows queued for Probabilistic AI analysis.",
        "currency": currency.upper(),
        "source": source,
        "records": services.source_records(df, source),
    }


@app.get("/api/v1/sources/{source_id}/download")
def download_source(source_id: str, response: Response, user: dict = Depends(get_current_user)):
    metadata, content = services.load_source(user, source_id)
    result = Response(content, media_type="text/csv", headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(metadata["original_filename"], safe=""),
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })
    result.raw_headers.extend((key, value) for key, value in response.raw_headers if key == b"set-cookie")
    return result
