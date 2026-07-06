from fastapi import APIRouter
from scheduler.worker import refresh_one

router = APIRouter()


@router.post("/refresh/{ticker}")
async def trigger_refresh(ticker: str):
    await refresh_one(ticker.upper())
    return {"status": "ok", "ticker": ticker.upper()}
