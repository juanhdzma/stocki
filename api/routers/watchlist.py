from __future__ import annotations
import json
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from db.cache import get_session, read_all_fundamentals, AsyncSessionLocal
from db.models import Watchlist, MarketSnapshot
from core.scorers.composite import compute_all

log = logging.getLogger(__name__)
router = APIRouter()


def _build_payload(ticker: str, snap: dict, funds: list[dict], refreshed_at: str) -> dict:
    current_year = str(date.today().year)
    annuals     = [f for f in funds if f.get("type") == "annual" and f.get("period") != current_year][:4]
    quarterlies = [f for f in funds if f.get("type") == "quarterly"][:4]
    snap_data   = {k: v for k, v in snap.items() if k not in ("returns", "insider_transactions")}
    market_cap  = snap.get("market_cap")
    recent_fcf  = next((f.get("fcf") for f in annuals if f.get("fcf") is not None), None)
    snap_data["fcf_yield"] = (recent_fcf / market_cap) if (recent_fcf and market_cap) else None
    try:
        scores = compute_all(funds, snap)
    except Exception as exc:
        log.warning("[%s] score computation failed: %s", ticker, exc)
        scores = None
    return {
        "snapshot":             snap_data,
        "returns":              snap.get("returns", {}),
        "annuals":              [{"period": f["period"], **{k: v for k, v in f.items() if k not in ("type", "period")}} for f in annuals],
        "quarterlies":          [{"period": f["period"], **{k: v for k, v in f.items() if k not in ("type", "period")}} for f in quarterlies],
        "insider_transactions": snap.get("insider_transactions", []),
        "scores":               scores,
        "refreshed_at":         refreshed_at,
        "data_ready":           len(quarterlies) >= 2,
    }


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


@router.post("/lists/{ticker}")
async def add_ticker(ticker: str, list_type: str = "watchlist",
                     session: AsyncSession = Depends(get_session)):
    ticker = ticker.upper()
    if list_type not in ("watchlist", "portfolio"):
        raise HTTPException(status_code=400, detail="list_type must be watchlist or portfolio")
    stmt = pg_insert(Watchlist).values(
        ticker=ticker, list_type=list_type, added_at=datetime.utcnow().isoformat()
    ).on_conflict_do_nothing()
    await session.execute(stmt)
    await session.commit()
    return {"ok": True}


@router.delete("/lists/{ticker}")
async def remove_ticker(ticker: str, session: AsyncSession = Depends(get_session)):
    await session.execute(delete(Watchlist).where(Watchlist.ticker == ticker.upper()))
    await session.commit()
    return {"ok": True}


@router.patch("/lists/{ticker}")
async def move_ticker(ticker: str, list_type: str,
                      session: AsyncSession = Depends(get_session)):
    ticker = ticker.upper()
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

    async def fetch_one(ticker: str):
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(MarketSnapshot).where(MarketSnapshot.ticker == ticker)
            )
            row = result.scalars().first()
            if not row:
                return ticker, None
            snap  = json.loads(row.data_json)
            funds = await read_all_fundamentals(session, ticker)
            return ticker, _build_payload(ticker, snap, funds, row.refreshed_at)

    results = await asyncio.gather(*[fetch_one(t) for t in ticker_list])
    return dict(results)
