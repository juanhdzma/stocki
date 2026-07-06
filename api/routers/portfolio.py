from __future__ import annotations
import asyncio
import logging

from fastapi import APIRouter
from sqlalchemy import select

from db.cache import AsyncSessionLocal, read_snapshot, read_all_fundamentals
from db.models import Watchlist
from api.routers._payload import build_payload

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/portfolio")
async def get_portfolio():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Watchlist.ticker).where(Watchlist.list_type == "portfolio")
        )
        tickers = [r[0] for r in result.all()]

    if not tickers:
        return {"tickers": [], "raw": {}}

    sem = asyncio.Semaphore(12)

    async def fetch_one(ticker: str) -> tuple[str, dict]:
        async with sem:
            async with AsyncSessionLocal() as session:
                snap  = await read_snapshot(session, ticker) or {}
                funds = await read_all_fundamentals(session, ticker)
            return ticker, build_payload(ticker, snap, funds)

    results = await asyncio.gather(*[fetch_one(t) for t in tickers])
    return {"tickers": tickers, "raw": dict(results)}
