from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from api.routers._payload import _TICKER_RE
from core.fetchers.yahoo import fetch_price_history

log = logging.getLogger(__name__)
router = APIRouter()

_ALLOWED_PERIODS = {"1mo", "1y"}


@router.get("/price-history/{ticker}")
async def price_history(ticker: str, period: str = "1y"):
    ticker = ticker.upper().strip()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    if period not in _ALLOWED_PERIODS:
        raise HTTPException(
            status_code=400, detail=f"period must be one of {sorted(_ALLOWED_PERIODS)}"
        )

    try:
        points = await asyncio.to_thread(fetch_price_history, ticker, period)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to fetch price history for {ticker}: {exc}"
        )

    return {"ticker": ticker, "period": period, "points": points}
