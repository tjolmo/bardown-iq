import os
import secrets
from fastapi import APIRouter, Header, HTTPException
from app import refresh
from app.schedules import full_refresh

router = APIRouter(prefix="/admin", tags=["admin"])

def require_admin_token(token: str | None):
    """The refresh hits external APIs (including the metered Odds API) and retrains models,
    so it is only available when ADMIN_TOKEN is set, and only to callers presenting it."""
    expected = os.getenv("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin endpoints are disabled: set ADMIN_TOKEN to enable them")
    if token is None or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Token header")

@router.post("/refresh", status_code=202)
async def trigger_full_refresh(x_admin_token: str | None = Header(default=None)):
    require_admin_token(x_admin_token)
    if not refresh.start_in_background("full refresh", full_refresh):
        raise HTTPException(status_code=409, detail={"message": "A refresh is already running", **refresh.get_status()})
    return {"message": "Full refresh started", **refresh.get_status()}

@router.get("/refresh", status_code=200)
async def get_refresh_status(x_admin_token: str | None = Header(default=None)):
    require_admin_token(x_admin_token)
    return refresh.get_status()
