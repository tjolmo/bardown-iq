import os
import secrets
from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from app import refresh
from app.schedules import full_refresh

# registered as a security scheme, so /docs shows an "Authorize" button for it
admin_token_header = APIKeyHeader(name="X-Admin-Token", auto_error=False, description="Value of the ADMIN_TOKEN env var")

def require_admin_token(token: str | None = Security(admin_token_header)):
    """The refresh hits external APIs (including the metered Odds API) and retrains models,
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
