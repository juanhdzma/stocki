from __future__ import annotations
import logging
import time

import requests
import yfinance
from fastapi import APIRouter

log = logging.getLogger(__name__)
router_cache: dict = {}

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
def system_info():
    installed = yfinance.__version__
    cached = router_cache.get("yfinance_latest")
    now = time.monotonic()
    if cached is None or now - cached[1] > _YF_LATEST_TTL:
        latest = _fetch_latest_yfinance()
        router_cache["yfinance_latest"] = (latest, now)
    else:
        latest = cached[0]
    return {
        "yfinance_installed": installed,
        "yfinance_latest":    latest,
        "up_to_date":         latest is None or installed == latest,
    }
