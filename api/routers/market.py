from __future__ import annotations

import asyncio
import logging
import threading
import time

import yfinance
from fastapi import APIRouter

from util import utcnow_iso

log = logging.getLogger(__name__)
router = APIRouter()

_cache: dict = {}
_cache_lock = threading.Lock()
_TTL = 60  # seconds — market cards refresh on page load, don't hammer yfinance

# label -> yfinance symbol
_SYMBOLS = {
    "vix": "^VIX",
    "sp500": "^GSPC",
    "nasdaq": "^NDX",
    "tnx": "^TNX",
}


def _one(symbol: str) -> dict | None:
    try:
        fi = yfinance.Ticker(symbol).fast_info
        last = fi.get("lastPrice")
        prev = fi.get("previousClose")
        if last is None:
            return None
        return {
            "value": float(last),
            "change": (float(last) / float(prev) - 1) if prev else None,
            "low52": _f(fi.get("yearLow")),
            "high52": _f(fi.get("yearHigh")),
        }
    except Exception as exc:
        log.warning("market fetch failed for %s: %s", symbol, exc)
        return None


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _fetch_all() -> dict:
    return {key: _one(sym) for key, sym in _SYMBOLS.items()}


@router.get("/market")
async def market():
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get("data")
        if cached is not None and now - cached[1] <= _TTL:
            return cached[0]
    data = await asyncio.to_thread(_fetch_all)
    data["fetched_at"] = utcnow_iso()
    with _cache_lock:
        _cache["data"] = (data, now)
    return data
