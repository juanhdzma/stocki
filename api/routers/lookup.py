from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routers._payload import _TICKER_RE, build_payload
from core.fetchers.yahoo import init_auth
from db.cache import (
    get_session,
    read_all_fundamentals,
    read_score_history_reference,
    read_snapshot,
)
from db.models import MarketSnapshot
from scheduler.worker import refresh_one
from util import parse_iso_aware, today_and_week_ago

log = logging.getLogger(__name__)
router = APIRouter()

_CACHE_TTL_SECONDS = 3600
_auth_lock = asyncio.Lock()
_last_auth_at: float = float("-inf")
_AUTH_INTERVAL = 300.0


async def _get_snapshot_info(session: AsyncSession, ticker: str) -> tuple[float | None, str | None]:
    result = await session.execute(
        select(MarketSnapshot.refreshed_at).where(MarketSnapshot.ticker == ticker)
    )
    row = result.first()
    ts = parse_iso_aware(row.refreshed_at) if row else None
    if ts is None:
        return None, None
    return (datetime.now(UTC) - ts).total_seconds(), row.refreshed_at


async def _snapshot_age_seconds(session: AsyncSession, ticker: str) -> float | None:
    age, _ = await _get_snapshot_info(session, ticker)
    return age


@router.get("/lookup/{ticker}")
async def lookup_ticker(ticker: str, session: AsyncSession = Depends(get_session)):
    ticker = ticker.upper().strip()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker")

    age, cached_refreshed_at = await _get_snapshot_info(session, ticker)

    if age is None or age > _CACHE_TTL_SECONDS:
        log.info("[%s] lookup: fetching live data", ticker)
        async with _auth_lock:
            global _last_auth_at
            if time.monotonic() - _last_auth_at > _AUTH_INTERVAL:
                await asyncio.to_thread(init_auth)
                _last_auth_at = time.monotonic()
        # Single source of truth for fetch+store: the same path the scheduler uses, so a
        # lookup also records earnings dates, fetch timestamps and daily score history,
        # instead of the divergent partial write this endpoint used to do on its own.
        await refresh_one(ticker, force=True)
        _, refreshed_at = await _get_snapshot_info(session, ticker)
        snap = await read_snapshot(session, ticker) or {}
    else:
        log.info("[%s] lookup: serving from cache (age %.0fs)", ticker, age)
        snap = await read_snapshot(session, ticker) or {}
        refreshed_at = cached_refreshed_at

    funds = await read_all_fundamentals(session, ticker)
    today, week_ago = today_and_week_ago()
    week_ago_scores = await read_score_history_reference(session, ticker, week_ago, today)
    payload = build_payload(ticker, snap, funds, refreshed_at, week_ago_scores)

    if not payload["snapshot"].get("price"):
        raise HTTPException(status_code=404, detail=f"No data found for {ticker}")

    return {"ticker": ticker, "raw": {ticker: payload}, "tickers": [ticker]}
