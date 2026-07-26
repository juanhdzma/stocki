from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.routers._payload import _TICKER_RE, build_payload
from db.cache import (
    AsyncSessionLocal,
    get_session,
    read_all_fundamentals_batch,
    read_score_history_reference_batch,
)
from db.models import MarketSnapshot, PortfolioHolding, Watchlist

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/lists")
async def get_lists(session: AsyncSession = Depends(get_session)):
    wl_result = await session.execute(
        select(Watchlist.ticker)
        .where(Watchlist.list_type == "watchlist")
        .order_by(Watchlist.added_at.asc())
    )
    watchlist_tickers = [r[0] for r in wl_result.all()]

    pf_result = await session.execute(
        select(PortfolioHolding).order_by(PortfolioHolding.added_at.asc())
    )
    pf_rows = pf_result.scalars().all()

    return {
        "watchlist": watchlist_tickers,
        "portfolio": [r.ticker for r in pf_rows],
        "portfolio_holdings": {
            r.ticker: {"avg_cost": r.avg_cost, "shares": r.shares} for r in pf_rows
        },
    }


@router.post("/lists/import")
async def import_tickers(
    tickers: list[str] = Body(...),
    session: AsyncSession = Depends(get_session),
):
    valid = [t.strip().upper() for t in tickers if _TICKER_RE.match(t.strip().upper())][:500]
    if not valid:
        raise HTTPException(status_code=400, detail="No valid tickers")
    await session.execute(delete(Watchlist))
    await session.execute(delete(PortfolioHolding))
    now = datetime.now(UTC).isoformat()
    for t in valid:
        stmt = (
            pg_insert(Watchlist)
            .values(ticker=t, list_type="watchlist", added_at=now)
            .on_conflict_do_nothing()
        )
        await session.execute(stmt)
    await session.commit()
    log.info("Imported %d tickers, replacing previous list", len(valid))
    return {"ok": True, "imported": len(valid)}


@router.post("/lists/{ticker}")
async def add_ticker(
    ticker: str, list_type: str = "watchlist", session: AsyncSession = Depends(get_session)
):
    ticker = ticker.upper()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    if list_type not in ("watchlist", "portfolio"):
        raise HTTPException(status_code=400, detail="list_type must be watchlist or portfolio")
    now = datetime.now(UTC).isoformat()
    stmt = (
        pg_insert(Watchlist)
        .values(ticker=ticker, list_type="watchlist", added_at=now)
        .on_conflict_do_nothing()
    )
    await session.execute(stmt)
    if list_type == "portfolio":
        stmt = (
            pg_insert(PortfolioHolding)
            .values(ticker=ticker, avg_cost=None, shares=None, added_at=now)
            .on_conflict_do_nothing()
        )
        await session.execute(stmt)
    await session.commit()
    return {"ok": True}


@router.delete("/lists/{ticker}")
async def remove_ticker(ticker: str, session: AsyncSession = Depends(get_session)):
    ticker = ticker.upper()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    await session.execute(delete(Watchlist).where(Watchlist.ticker == ticker))
    await session.execute(delete(PortfolioHolding).where(PortfolioHolding.ticker == ticker))
    await session.commit()
    return {"ok": True}


@router.patch("/lists/{ticker}")
async def move_ticker(ticker: str, list_type: str, session: AsyncSession = Depends(get_session)):
    ticker = ticker.upper()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    if list_type not in ("watchlist", "portfolio"):
        raise HTTPException(status_code=400, detail="list_type must be watchlist or portfolio")
    if list_type == "portfolio":
        stmt = (
            pg_insert(PortfolioHolding)
            .values(
                ticker=ticker, avg_cost=None, shares=None, added_at=datetime.now(UTC).isoformat()
            )
            .on_conflict_do_nothing()
        )
        await session.execute(stmt)
    else:
        await session.execute(delete(PortfolioHolding).where(PortfolioHolding.ticker == ticker))
    await session.commit()
    return {"ok": True}


@router.patch("/portfolio/{ticker}/holding")
async def update_holding(
    ticker: str,
    data: dict = Body(...),
    session: AsyncSession = Depends(get_session),
):
    ticker = ticker.upper()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    avg_cost = data.get("avg_cost")
    shares = data.get("shares")
    stmt = (
        pg_insert(PortfolioHolding)
        .values(
            ticker=ticker, avg_cost=avg_cost, shares=shares, added_at=datetime.now(UTC).isoformat()
        )
        .on_conflict_do_update(
            index_elements=["ticker"],
            set_={"avg_cost": avg_cost, "shares": shares},
        )
    )
    await session.execute(stmt)
    await session.commit()
    return {"ok": True}


@router.get("/watchlist")
async def get_watchlist_data(tickers: str = ""):
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:200]
    if not ticker_list:
        return {}

    today = datetime.now(UTC).date().isoformat()
    week_ago = (datetime.now(UTC).date() - timedelta(days=7)).isoformat()

    # Batched: 3 queries total for the whole ticker list instead of ~3 per ticker —
    # this endpoint gets polled often (refresh progress, rescore), so N+1 here was
    # the single biggest source of redundant DB load.
    async with AsyncSessionLocal() as session:
        snap_result = await session.execute(
            select(MarketSnapshot).where(MarketSnapshot.ticker.in_(ticker_list))
        )
        snap_rows = {row.ticker: row for row in snap_result.scalars().all()}
        funds_map = await read_all_fundamentals_batch(session, ticker_list)
        history_map = await read_score_history_reference_batch(
            session, ticker_list, week_ago, today
        )

    results = {}
    for ticker in ticker_list:
        row = snap_rows.get(ticker)
        if not row:
            results[ticker] = None
            continue
        snap = json.loads(row.data_json)
        results[ticker] = build_payload(
            ticker, snap, funds_map.get(ticker, []), row.refreshed_at, history_map.get(ticker)
        )
    return results
