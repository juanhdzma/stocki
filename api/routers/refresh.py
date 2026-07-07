import asyncio
from fastapi import APIRouter
from scheduler.worker import refresh_one, refresh_all

router = APIRouter()


@router.post("/refresh")
async def trigger_refresh_all():
    asyncio.create_task(refresh_all())
    return {"status": "started"}


@router.post("/refresh/{ticker}")
async def trigger_refresh(ticker: str):
    await refresh_one(ticker.upper())
    return {"status": "ok", "ticker": ticker.upper()}
