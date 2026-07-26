from __future__ import annotations

import asyncio
import logging
import time as _time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routers._payload import _TICKER_RE, build_payload
from core.fetchers.openinsider import fetch_insider_transactions
from core.fetchers.yahoo import fetch_fundamentals, fetch_market_snapshot, init_auth
from db.cache import (
    get_session,
    has_fundamentals,
    read_all_fundamentals,
    read_score_history_reference,
    read_snapshot,
    write_fundamentals,
    write_snapshot,
)
from db.models import MarketSnapshot

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
    if not row or not row.refreshed_at:
        return None, None
    try:
        ts = datetime.fromisoformat(row.refreshed_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return (datetime.now(UTC) - ts).total_seconds(), row.refreshed_at
    except Exception:
        return None, None


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
            if _time.monotonic() - _last_auth_at > _AUTH_INTERVAL:
                await asyncio.to_thread(init_auth)
                _last_auth_at = _time.monotonic()
        try:
            snap = await asyncio.to_thread(fetch_market_snapshot, ticker)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to fetch {ticker}: {exc}")

        try:
            txs = await asyncio.to_thread(fetch_insider_transactions, ticker, days_back=365)
        except Exception:
            txs = None

        existing = await read_snapshot(session, ticker)
        snap["insider_transactions"] = (
            txs
            if txs is not None
            else (existing.get("insider_transactions", []) if existing else [])
        )
        await write_snapshot(session, ticker, snap)
        refreshed_at = datetime.now(UTC).isoformat()

        try:
            periods = await asyncio.to_thread(fetch_fundamentals, ticker)
            for period, data in periods:
                if not await has_fundamentals(session, ticker, period):
                    await write_fundamentals(session, ticker, period, data)
        except Exception as exc:
            log.warning("[%s] fundamentals fetch failed: %s", ticker, exc)
    else:
        log.info("[%s] lookup: serving from cache (age %.0fs)", ticker, age)
        snap = await read_snapshot(session, ticker) or {}
        refreshed_at = cached_refreshed_at

    funds = await read_all_fundamentals(session, ticker)
    today = datetime.now(UTC).date().isoformat()
    week_ago = (datetime.now(UTC).date() - timedelta(days=7)).isoformat()
    week_ago_scores = await read_score_history_reference(session, ticker, week_ago, today)
    payload = build_payload(ticker, snap, funds, refreshed_at, week_ago_scores)

    if not payload["snapshot"].get("price"):
        raise HTTPException(status_code=404, detail=f"No data found for {ticker}")

    return {"ticker": ticker, "raw": {ticker: payload}, "tickers": [ticker]}
