from __future__ import annotations
import logging

import requests
import yfinance

log = logging.getLogger(__name__)
router_cache: dict = {}


def _fetch_latest_yfinance() -> str | None:
    try:
        resp = requests.get("https://pypi.org/pypi/yfinance/json", timeout=8)
        resp.raise_for_status()
        return resp.json()["info"]["version"]
    except Exception as exc:
        log.warning("PyPI version fetch failed: %s", exc)
        return None


from fastapi import APIRouter

router = APIRouter()


@router.get("/system/info")
def system_info():
    installed = yfinance.__version__
    if "yfinance_latest" not in router_cache:
        router_cache["yfinance_latest"] = _fetch_latest_yfinance()
    latest = router_cache.get("yfinance_latest")
    return {
        "yfinance_installed": installed,
        "yfinance_latest":    latest,
        "up_to_date":         latest is None or installed == latest,
    }
