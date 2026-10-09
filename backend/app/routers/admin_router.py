import os
import secrets
from fastapi import APIRouter, Depends, HTTPException, Query, Security
from sqlalchemy.ext.asyncio import AsyncSession
from app.dependencies import get_db
from fastapi.security import APIKeyHeader
from app import refresh
from app.schedules import full_refresh

# registered as a security scheme, so /docs shows an "Authorize" button for it
admin_token_header = APIKeyHeader(name="X-Admin-Token", auto_error=False, description="Value of the ADMIN_TOKEN env var")

def require_admin_token(token: str | None = Security(admin_token_header)):
    """The refresh hits external APIs (including the metered PropLine API) and retrains models,
    so it is only available when ADMIN_TOKEN is set, and only to callers presenting it."""
    expected = os.getenv("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin endpoints are disabled: set ADMIN_TOKEN to enable them")
    if token is None or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Token header")

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_token)])

@router.post("/refresh", status_code=202)
async def trigger_full_refresh():
    if not refresh.start_in_background("full refresh", full_refresh):
        raise HTTPException(status_code=409, detail={"message": "A refresh is already running", **refresh.get_status()})
    return {"message": "Full refresh started", **refresh.get_status()}

@router.get("/refresh", status_code=200)
async def get_refresh_status():
    return refresh.get_status()

@router.get("/model-report", status_code=200)
async def get_model_report(model_version: str | None = None, start: int | None = Query(None, description="YYYYMMDD"),
                           end: int | None = Query(None, description="YYYYMMDD"), db: AsyncSession = Depends(get_db)):
    """Forward test of the frozen models (read-only): realized log loss / Poisson deviance vs the market at log
    time and at the close, calibration buckets and closing-line value, from prediction_scores."""
    from predictions.prediction_log import model_report
    return await model_report(db, model_version, start, end)
