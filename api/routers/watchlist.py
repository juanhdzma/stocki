from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.routers._payload import _TICKER_RE, build_payload, parse_ticker_csv
from db.cache import (
    AsyncSessionLocal,
    get_session,
    read_all_fundamentals_batch,
    read_score_history_reference_batch,
)
from db.models import MarketSnapshot, Watchlist
from util import today_and_week_ago, utcnow_iso

log = logging.getLogger(__name__)
router = APIRouter()

_LIST_TYPES = ("watchlist", "favorite")


@router.get("/lists")
async def get_lists(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Watchlist.ticker, Watchlist.list_type).order_by(Watchlist.added_at.asc())
    )
    watchlist_tickers, favorites = [], []
    for ticker, list_type in result.all():
        (favorites if list_type == "favorite" else watchlist_tickers).append(ticker)
    return {"watchlist": watchlist_tickers, "favorites": favorites}


@router.post("/lists/import")
async def import_tickers(
    tickers: list[str] = Body(...),
    session: AsyncSession = Depends(get_session),
):
    valid = [t.strip().upper() for t in tickers if _TICKER_RE.match(t.strip().upper())][:500]
    if not valid:
        raise HTTPException(status_code=400, detail="No valid tickers")
    await session.execute(delete(Watchlist))
    now = utcnow_iso()
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
    if list_type not in _LIST_TYPES:
        raise HTTPException(status_code=400, detail="list_type must be watchlist or favorite")
    stmt = (
        pg_insert(Watchlist)
        .values(ticker=ticker, list_type=list_type, added_at=utcnow_iso())
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
    await session.commit()
    return {"ok": True}


@router.patch("/lists/{ticker}")
async def move_ticker(ticker: str, list_type: str, session: AsyncSession = Depends(get_session)):
    ticker = ticker.upper()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    if list_type not in _LIST_TYPES:
        raise HTTPException(status_code=400, detail="list_type must be watchlist or favorite")
    await session.execute(
        pg_insert(Watchlist)
        .values(ticker=ticker, list_type=list_type, added_at=utcnow_iso())
        .on_conflict_do_update(index_elements=["ticker"], set_={"list_type": list_type})
    )
    await session.commit()
    return {"ok": True}


@router.get("/watchlist")
async def get_watchlist_data(tickers: str = "", full: bool = False):
    ticker_list = parse_ticker_csv(tickers)
    if not ticker_list:
        return {}

    today, week_ago = today_and_week_ago()

    # Batched: 3 queries total for the whole ticker list instead of ~3 per ticker —
    # this endpoint gets polled often (refresh progress, rescore), so N+1 here was
    # the single biggest source of redundant DB load.
    async with AsyncSessionLocal() as session:
        snap_result = await session.execute(
            select(MarketSnapshot).where(MarketSnapshot.ticker.in_(ticker_list))
        )
        snap_rows = {r.ticker: (r.data_json, r.refreshed_at) for r in snap_result.scalars().all()}
        funds_map = await read_all_fundamentals_batch(session, ticker_list)
        history_map = await read_score_history_reference_batch(
            session, ticker_list, week_ago, today
        )

    # compute_all (multi-scorer slope math) runs per ticker inside build_payload and is CPU-bound;
    # a 200-ticker load would otherwise block the event loop back-to-back. Offload the whole build.
    def _build() -> dict:
        out = {}
        for ticker in ticker_list:
            rec = snap_rows.get(ticker)
            if not rec:
                out[ticker] = None
                continue
            # Isolate per ticker: a single malformed snapshot must not 500 the whole
            # multi-ticker response and blank out every other row.
            try:
                data_json, refreshed_at = rec
                snap = json.loads(data_json)
                out[ticker] = build_payload(
                    ticker,
                    snap,
                    funds_map.get(ticker, []),
                    refreshed_at,
                    history_map.get(ticker),
                    full=full,
                )
            except Exception:
                log.exception("[%s] payload build failed", ticker)
                out[ticker] = None
        return out

    return await asyncio.to_thread(_build)
