from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, nullsfirst

from db.cache import (
    AsyncSessionLocal, write_snapshot, write_fundamentals, has_fundamentals,
    should_fetch, set_last_fetch, get_last_fetch, read_snapshot,
)
from db.models import Watchlist, MarketSnapshot
from core.fetchers.yahoo import fetch_market_snapshot, fetch_fundamentals, batch_download_history, init_auth
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

_in_flight: set[str] = set()
_errors: dict[str, set[str]] = {}
_refresh_running: bool = False


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


async def refresh_one(ticker: str, hist=None) -> None:
    _in_flight.add(ticker)
    errs: set[str] = _errors.get(ticker, set()).copy()
    try:
        async with AsyncSessionLocal() as session:
            existing = await read_snapshot(session, ticker)
            fetch_snap = await _should_fetch_snapshot(session, ticker)

            snapshot = None
            if fetch_snap:
                log.info("[%s] fetching snapshot", ticker)
                try:
                    snapshot = await asyncio.to_thread(fetch_market_snapshot, ticker, hist)
                    errs.discard("snapshot")
                except Exception as exc:
                    log.error("[%s] snapshot fetch failed: %s", ticker, exc)
                    errs.add("snapshot")
                    return
            else:
                log.info("[%s] snapshot cached — market closed", ticker)

            if await should_fetch(session, ticker, "insider", INSIDER_TTL):
                log.info("[%s] fetching insider transactions", ticker)
                try:
                    txs = await asyncio.to_thread(fetch_insider_transactions, ticker, days_back=365)
                    if txs is not None:
                        await set_last_fetch(session, ticker, "insider")
                        errs.discard("insider")
                    else:
                        log.warning("[%s] insider fetch returned no data", ticker)
                        txs = None
                except Exception as exc:
                    log.warning("[%s] insider fetch failed: %s", ticker, exc)
                    errs.add("insider")
                    txs = None
            else:
                log.info("[%s] insider transactions cached", ticker)
                txs = None

            if snapshot is not None:
                snapshot["insider_transactions"] = (
                    txs if txs is not None
                    else (existing.get("insider_transactions", []) if existing else [])
                )
                await write_snapshot(session, ticker, snapshot)
                await set_last_fetch(session, ticker, "snapshot")
            elif txs is not None and existing is not None:
                existing["insider_transactions"] = txs
                await write_snapshot(session, ticker, existing)

            if await should_fetch(session, ticker, "fundamentals", FUNDAMENTALS_TTL):
                log.info("[%s] fetching fundamentals", ticker)
                try:
                    periods = await asyncio.to_thread(fetch_fundamentals, ticker)
                    for period, data in periods:
                        if not await has_fundamentals(session, ticker, period):
                            await write_fundamentals(session, ticker, period, data)
                    await set_last_fetch(session, ticker, "fundamentals")
                    errs.discard("fundamentals")
                except Exception as exc:
                    log.warning("[%s] fundamentals fetch failed: %s", ticker, exc)
                    errs.add("fundamentals")
            else:
                log.info("[%s] fundamentals cached", ticker)
    finally:
        _in_flight.discard(ticker)
        _errors[ticker] = errs


async def refresh_all() -> None:
    global _refresh_running
    if _refresh_running:
        log.info("Refresh already in progress, skipping duplicate request")
        return
    _refresh_running = True
    try:
        await _refresh_all_impl()
    finally:
        _refresh_running = False


async def _refresh_all_impl() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Watchlist.ticker, MarketSnapshot.refreshed_at)
            .outerjoin(MarketSnapshot, Watchlist.ticker == MarketSnapshot.ticker)
            .order_by(nullsfirst(MarketSnapshot.refreshed_at.asc()))
        )
        ordered = [r[0] for r in result.all()]
    if not ordered:
        log.info("No tickers to refresh")
        return

    log.info("Refresh queue: %s", ordered)

    log.info("Bulk price download for %d tickers + SPY", len(ordered))
    try:
        hist = await asyncio.to_thread(batch_download_history, ordered)
        log.info("Bulk download complete — shape: %s", hist.shape)
        await asyncio.to_thread(init_auth)
    except Exception as exc:
        log.warning("Bulk download failed (%s) — falling back to per-ticker downloads", exc)
        hist = None

    batch_size = 12
    batch_delay = 5.0

    for i in range(0, len(ordered), batch_size):
        batch = ordered[i : i + batch_size]
        log.info("Refresh batch %d/%d: %s", i // batch_size + 1, -(-len(ordered) // batch_size), batch)
        results = await asyncio.gather(*[refresh_one(t, hist) for t in batch], return_exceptions=True)
        for ticker, res in zip(batch, results):
            if isinstance(res, Exception):
                log.error("[%s] refresh failed: %s", ticker, res)
        if i + batch_size < len(ordered):
            await asyncio.sleep(batch_delay)

    log.info("Refresh complete")
