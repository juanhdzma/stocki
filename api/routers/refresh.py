from fastapi import APIRouter

from scheduler.worker import refresh_all, refresh_one, spawn_background

router = APIRouter()


@router.post("/refresh")
async def trigger_refresh_all():
    spawn_background(refresh_all(force=True), name="refresh_all")
    return {"status": "started"}


@router.post("/refresh/{ticker}")
async def trigger_refresh(ticker: str):
    await refresh_one(ticker.upper(), force=True)
    return {"status": "ok", "ticker": ticker.upper()}
