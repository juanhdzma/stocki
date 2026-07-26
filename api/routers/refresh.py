from fastapi import APIRouter, HTTPException

from api.routers._payload import _TICKER_RE
from scheduler.worker import refresh_all, refresh_one, spawn_background

router = APIRouter()


@router.post("/refresh")
async def trigger_refresh_all():
    spawn_background(refresh_all(force=True), name="refresh_all")
    return {"status": "started"}


@router.post("/refresh/{ticker}")
async def trigger_refresh(ticker: str):
    ticker = ticker.upper().strip()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    await refresh_one(ticker, force=True)
    return {"status": "ok", "ticker": ticker}
