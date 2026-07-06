from __future__ import annotations
import asyncio
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.cache import (
    get_session, read_snapshot, read_all_fundamentals,
    write_snapshot, write_fundamentals, has_fundamentals,
)
from db.models import MarketSnapshot
from core.fetchers.yahoo import fetch_market_snapshot, fetch_fundamentals, init_auth
from core.fetchers.openinsider import fetch_insider_transactions
from core.scorers.composite import compute_all

log = logging.getLogger(__name__)
router = APIRouter()

_CACHE_TTL_SECONDS = 3600


async def _snapshot_age_seconds(session: AsyncSession, ticker: str) -> float | None:
    result = await session.execute(
        select(MarketSnapshot.refreshed_at).where(MarketSnapshot.ticker == ticker)
    )
    row = result.first()
    if not row or not row.refreshed_at:
        return None
    try:
        ts = datetime.fromisoformat(row.refreshed_at)
        return (datetime.utcnow() - ts).total_seconds()
    except Exception:
        return None


def _build_payload(ticker: str, snap: dict, funds: list[dict]) -> dict:
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
    }


@router.get("/lookup/{ticker}")
async def lookup_ticker(ticker: str, session: AsyncSession = Depends(get_session)):
    ticker = ticker.upper().strip()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker")

    age = await _snapshot_age_seconds(session, ticker)

    if age is None or age > _CACHE_TTL_SECONDS:
        log.info("[%s] lookup: fetching live data", ticker)
        init_auth()
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
            txs if txs is not None
            else (existing.get("insider_transactions", []) if existing else [])
        )
        await write_snapshot(session, ticker, snap)

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

    funds   = await read_all_fundamentals(session, ticker)
    payload = _build_payload(ticker, snap, funds)

    if not payload["snapshot"].get("price"):
        raise HTTPException(status_code=404, detail=f"No data found for {ticker}")

    return {"ticker": ticker, "raw": {ticker: payload}, "tickers": [ticker]}
