from __future__ import annotations
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select, update, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from db.cache import get_session, read_all_fundamentals, AsyncSessionLocal
from db.models import Watchlist, MarketSnapshot
from api.routers._payload import build_payload, _TICKER_RE

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/lists")
async def get_lists(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Watchlist.ticker, Watchlist.list_type).order_by(Watchlist.added_at.asc())
    )
    out: dict[str, list[str]] = {"portfolio": [], "watchlist": []}
    for row in result.all():
        lt = row.list_type if row.list_type in out else "watchlist"
        out[lt].append(row.ticker)
    return out


@router.post("/lists/import")
async def import_tickers(
    tickers: list[str] = Body(...),
    session: AsyncSession = Depends(get_session),
):
    valid = [t.strip().upper() for t in tickers if _TICKER_RE.match(t.strip().upper())][:500]
    if not valid:
        raise HTTPException(status_code=400, detail="No valid tickers")
    await session.execute(delete(Watchlist))
    now = datetime.now(timezone.utc).isoformat()
    for t in valid:
        stmt = pg_insert(Watchlist).values(
            ticker=t, list_type="watchlist", added_at=now
        ).on_conflict_do_nothing()
        await session.execute(stmt)
    await session.commit()
    log.info("Imported %d tickers, replacing previous list", len(valid))
    return {"ok": True, "imported": len(valid)}


@router.post("/lists/{ticker}")
async def add_ticker(ticker: str, list_type: str = "watchlist",
                     session: AsyncSession = Depends(get_session)):
    ticker = ticker.upper()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    if list_type not in ("watchlist", "portfolio"):
        raise HTTPException(status_code=400, detail="list_type must be watchlist or portfolio")
    stmt = pg_insert(Watchlist).values(
        ticker=ticker, list_type=list_type, added_at=datetime.now(timezone.utc).isoformat()
    ).on_conflict_do_nothing()
    await session.execute(stmt)
    await session.commit()
    return {"ok": True}


@router.delete("/lists/{ticker}")
async def remove_ticker(ticker: str, session: AsyncSession = Depends(get_session)):
    ticker = ticker.upper()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    await session.execute(delete(Watchlist).where(Watchlist.ticker == ticker))
    await session.commit()
    return {"ok": True}


@router.patch("/lists/{ticker}")
async def move_ticker(ticker: str, list_type: str,
                      session: AsyncSession = Depends(get_session)):
    ticker = ticker.upper()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    if list_type not in ("watchlist", "portfolio"):
        raise HTTPException(status_code=400, detail="list_type must be watchlist or portfolio")
    await session.execute(
        update(Watchlist).where(Watchlist.ticker == ticker).values(list_type=list_type)
    )
    await session.commit()
    return {"ok": True}


@router.get("/watchlist")
async def get_watchlist_data(tickers: str = ""):
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:200]

    sem = asyncio.Semaphore(12)

    async def fetch_one(ticker: str):
        async with sem:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(MarketSnapshot).where(MarketSnapshot.ticker == ticker)
                )
                row = result.scalars().first()
                if not row:
                    return ticker, None
                snap  = json.loads(row.data_json)
                funds = await read_all_fundamentals(session, ticker)
                return ticker, build_payload(ticker, snap, funds, row.refreshed_at)

    results = await asyncio.gather(*[fetch_one(t) for t in ticker_list])
    return dict(results)
