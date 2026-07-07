from __future__ import annotations
import asyncio
import json
import logging

from fastapi import APIRouter
from sqlalchemy import select

from db.cache import AsyncSessionLocal, read_all_fundamentals
from db.models import Watchlist, MarketSnapshot
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
                result = await session.execute(
                    select(MarketSnapshot).where(MarketSnapshot.ticker == ticker)
                )
                row = result.scalars().first()
                snap = json.loads(row.data_json) if row else {}
                refreshed_at = row.refreshed_at if row else None
                funds = await read_all_fundamentals(session, ticker)
            return ticker, build_payload(ticker, snap, funds, refreshed_at)

    results = await asyncio.gather(*[fetch_one(t) for t in tickers])
    return {"tickers": tickers, "raw": dict(results)}
