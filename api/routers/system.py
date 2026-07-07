from __future__ import annotations
import asyncio
import logging
import threading
import time

import requests
import yfinance
from fastapi import APIRouter

log = logging.getLogger(__name__)
router_cache: dict = {}
_cache_lock = threading.Lock()

_YF_LATEST_TTL = 24 * 3600


def _fetch_latest_yfinance() -> str | None:
    try:
        resp = requests.get("https://pypi.org/pypi/yfinance/json", timeout=8)
        resp.raise_for_status()
        return resp.json()["info"]["version"]
    except Exception as exc:
        log.warning("PyPI version fetch failed: %s", exc)
        return None


router = APIRouter()


@router.get("/system/info")
async def system_info():
    installed = yfinance.__version__
    now = time.monotonic()
    with _cache_lock:
        cached = router_cache.get("yfinance_latest")
        if cached is not None and now - cached[1] <= _YF_LATEST_TTL:
            return {
                "yfinance_installed": installed,
                "yfinance_latest":    cached[0],
                "up_to_date":         cached[0] is None or installed == cached[0],
            }
    latest = await asyncio.to_thread(_fetch_latest_yfinance)
    with _cache_lock:
        router_cache["yfinance_latest"] = (latest, now)
    return {
        "yfinance_installed": installed,
        "yfinance_latest":    latest,
        "up_to_date":         latest is None or installed == latest,
    }
