from __future__ import annotations
import json

from fastapi import APIRouter
from sqlalchemy import select

from db.cache import AsyncSessionLocal
from db.models import MarketSnapshot, FundamentalsHistory, FetchTimestamp
import scheduler.worker as _worker

router = APIRouter()


@router.get("/status")
async def get_status(tickers: str = ""):
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:200]
    if not ticker_list:
        return {}

    async with AsyncSessionLocal() as session:
        snap_rows = await session.execute(
            select(MarketSnapshot.ticker, MarketSnapshot.data_json)
            .where(MarketSnapshot.ticker.in_(ticker_list))
        )
        snap_map: dict[str, dict] = {}
        for row in snap_rows:
            snap_map[row.ticker] = json.loads(row.data_json)

        fund_rows = await session.execute(
            select(FundamentalsHistory.ticker, FundamentalsHistory.data_json)
            .where(FundamentalsHistory.ticker.in_(ticker_list))
        )
        annual_count:    dict[str, int] = {}
        quarterly_count: dict[str, int] = {}
        for row in fund_rows:
            data = json.loads(row.data_json)
            kind = data.get("type", "")
            t = row.ticker
            if kind == "annual":
                annual_count[t] = annual_count.get(t, 0) + 1
            elif kind == "quarterly":
                quarterly_count[t] = quarterly_count.get(t, 0) + 1

        ins_rows = await session.execute(
            select(FetchTimestamp.ticker)
            .where(FetchTimestamp.ticker.in_(ticker_list))
            .where(FetchTimestamp.data_type == "insider")
        )
        insider_fetched: set[str] = {row.ticker for row in ins_rows}

    result = {}
    for ticker in ticker_list:
        in_flight = ticker in _worker._in_flight
        errs = _worker._errors.get(ticker, set())
        snap = snap_map.get(ticker)

        has_snap   = snap is not None
        has_ins    = ticker in insider_fetched
        has_annual = annual_count.get(ticker, 0) >= 1
        has_qtrs   = quarterly_count.get(ticker, 0) >= 2
        has_score  = has_snap and has_qtrs

        def light(has_data: bool, err_key: str) -> str:
            if in_flight:
                return "yellow"
            if err_key in errs:
                return "red"
            return "green" if has_data else "gray"

        result[ticker] = {
            "snap":  light(has_snap,   "snapshot"),
            "fund":  light(has_annual, "fundamentals"),
            "qtrs":  light(has_qtrs,   "fundamentals"),
            "ins":   light(has_ins,    "insider"),
            "score": light(has_score,  "score"),
        }

    result["_running"] = _worker._refresh_running
    return result
