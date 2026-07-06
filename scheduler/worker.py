from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from config import TICKERS
from db.cache import (
    AsyncSessionLocal, write_snapshot, write_fundamentals, has_fundamentals,
    should_fetch, set_last_fetch, get_last_fetch, read_snapshot,
)
from db.models import Watchlist, MarketSnapshot
from core.fetchers.yahoo import fetch_market_snapshot, fetch_fundamentals
from core.fetchers.openinsider import fetch_insider_transactions

INSIDER_TTL      = timedelta(hours=24)
FUNDAMENTALS_TTL = timedelta(days=7)
SNAPSHOT_TTL     = timedelta(minutes=4)

_TZ_ET    = ZoneInfo("America/New_York")
_TZ_PARIS = ZoneInfo("Europe/Paris")

_MARKET_HOURS: dict[str, tuple[ZoneInfo, tuple[int, int], tuple[int, int]]] = {
    "PA": (_TZ_PARIS, (9, 0),  (17, 30)),
    "US": (_TZ_ET,   (9, 30), (16, 0)),
}

log = logging.getLogger(__name__)
_scheduler = AsyncIOScheduler(timezone="UTC")


def _market_zone(ticker: str):
    suffix = ticker.split(".")[-1] if "." in ticker else "US"
    return _MARKET_HOURS.get(suffix, _MARKET_HOURS["US"])


def _is_market_open(ticker: str, ts: datetime) -> bool:
    tz, (oh, om), (ch, cm) = _market_zone(ticker)
    local = ts.astimezone(tz)
    if local.weekday() >= 5:
        return False
    t = (local.hour, local.minute)
    return (oh, om) <= t < (ch, cm)


async def _should_fetch_snapshot(session, ticker: str) -> bool:
    now = datetime.now(timezone.utc)
    last = await get_last_fetch(session, ticker, "snapshot")
    if _is_market_open(ticker, now):
        return last is None or (now - last) > SNAPSHOT_TTL
    if last is None:
        return True
    return _is_market_open(ticker, last)


async def refresh_one(ticker: str) -> None:
    async with AsyncSessionLocal() as session:
        if not await _should_fetch_snapshot(session, ticker):
            log.info("[%s] snapshot cached — market closed, skipping", ticker)
            return

        log.info("[%s] fetching snapshot", ticker)
        try:
            snapshot = await asyncio.to_thread(fetch_market_snapshot, ticker)
            await set_last_fetch(session, ticker, "snapshot")
        except Exception as exc:
            log.error("[%s] snapshot fetch failed: %s", ticker, exc)
            return

        existing = await read_snapshot(session, ticker)

        if await should_fetch(session, ticker, "insider", INSIDER_TTL):
            log.info("[%s] fetching insider transactions", ticker)
            try:
                txs = await asyncio.to_thread(fetch_insider_transactions, ticker, days_back=365)
                await set_last_fetch(session, ticker, "insider")
            except Exception as exc:
                log.warning("[%s] insider fetch failed: %s", ticker, exc)
                txs = None
        else:
            log.info("[%s] insider transactions cached", ticker)
            txs = None

        snapshot["insider_transactions"] = (
            txs if txs is not None
            else (existing.get("insider_transactions", []) if existing else [])
        )

        await write_snapshot(session, ticker, snapshot)

        if await should_fetch(session, ticker, "fundamentals", FUNDAMENTALS_TTL):
            log.info("[%s] fetching fundamentals", ticker)
            try:
                periods = await asyncio.to_thread(fetch_fundamentals, ticker)
                for period, data in periods:
                    if not await has_fundamentals(session, ticker, period):
                        await write_fundamentals(session, ticker, period, data)
                await set_last_fetch(session, ticker, "fundamentals")
            except Exception as exc:
                log.warning("[%s] fundamentals fetch failed: %s", ticker, exc)
        else:
            log.info("[%s] fundamentals cached", ticker)


async def refresh_all() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Watchlist.ticker))
        tracked = {r[0] for r in result.all()}
        tracked.update(TICKERS)

        result2 = await session.execute(select(MarketSnapshot.ticker))
        in_db = {r[0] for r in result2.all()}

        missing = [t for t in tracked if t not in in_db]
        result3 = await session.execute(
            select(MarketSnapshot.ticker)
            .where(MarketSnapshot.ticker.in_(tracked))
            .order_by(MarketSnapshot.refreshed_at.asc())
        )
        existing_ordered = [r[0] for r in result3.all()]

    ordered = missing + existing_ordered
    if not ordered:
        log.info("No tickers to refresh")
        return

    log.info("Refresh queue: %s", ordered)
    results = await asyncio.gather(*[refresh_one(t) for t in ordered], return_exceptions=True)
    for ticker, res in zip(ordered, results):
        if isinstance(res, Exception):
            log.error("[%s] refresh failed: %s", ticker, res)

    log.info("Refresh complete")


def start_scheduler() -> None:
    _scheduler.add_job(
        refresh_all,
        "interval",
        minutes=5,
        id="refresh_all",
        next_run_time=datetime.utcnow(),
    )
    _scheduler.start()
    log.info("Scheduler started")


def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
