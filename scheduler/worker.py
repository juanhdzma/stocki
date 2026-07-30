from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import nullsfirst, select

from core.fetchers.openinsider import fetch_insider_transactions
from core.fetchers.yahoo import (
    batch_download_history,
    fetch_earnings_dates,
    fetch_fundamentals,
    fetch_market_snapshot,
    init_auth,
)
from core.scorers.composite import compute_all
from db.cache import (
    AsyncSessionLocal,
    get_last_fetch,
    has_fundamentals,
    read_all_fundamentals,
    read_snapshot,
    set_last_fetch,
    should_fetch,
    write_fundamentals,
    write_score_history_if_missing,
    write_snapshot,
)
from db.models import MarketSnapshot, Watchlist

INSIDER_TTL = timedelta(hours=24)
FUNDAMENTALS_TTL = timedelta(days=7)
SNAPSHOT_TTL = timedelta(minutes=4)
EARNINGS_TTL = timedelta(days=14)

_TZ_ET = ZoneInfo("America/New_York")
_TZ_PARIS = ZoneInfo("Europe/Paris")

_MARKET_HOURS: dict[str, tuple[ZoneInfo, tuple[int, int], tuple[int, int]]] = {
    "PA": (_TZ_PARIS, (9, 0), (17, 30)),
    "US": (_TZ_ET, (9, 30), (16, 0)),
}

log = logging.getLogger(__name__)

_in_flight: set[str] = set()
_errors: dict[str, set[str]] = {}
_refresh_running: bool = False

# Keep a reference to fire-and-forget tasks so they aren't garbage-collected mid-run, and
# surface any exception instead of letting it vanish silently (the default for a lost task).
_background_tasks: set[asyncio.Task] = set()


def spawn_background(coro, name: str) -> None:
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if not t.cancelled() and (exc := t.exception()) is not None:
            log.error("background task %r failed: %s", t.get_name(), exc)

    task.add_done_callback(_done)


def _market_zone(ticker: str):
    suffix = ticker.split(".")[-1] if "." in ticker else "US"
    return _MARKET_HOURS.get(suffix, _MARKET_HOURS["US"])


def _recent_periods(periods, n_quarterly: int = 2, n_annual: int = 1) -> set[str]:
    """The newest quarterly/annual period strings — the ones prone to being partial right
    after a report, so they get re-written (overwrite) on each fetch instead of frozen."""
    q = sorted((p for p, d in periods if d.get("type") == "quarterly"), reverse=True)
    a = sorted((p for p, d in periods if d.get("type") == "annual"), reverse=True)
    return set(q[:n_quarterly]) | set(a[:n_annual])


def _is_market_open(ticker: str, ts: datetime) -> bool:
    tz, (oh, om), (ch, cm) = _market_zone(ticker)
    local = ts.astimezone(tz)
    if local.weekday() >= 5:
        return False
    t = (local.hour, local.minute)
    return (oh, om) <= t < (ch, cm)


async def _should_fetch_snapshot(session, ticker: str, force: bool = False) -> bool:
    if force:
        return True
    now = datetime.now(UTC)
    last = await get_last_fetch(session, ticker, "snapshot")
    if _is_market_open(ticker, now):
        return last is None or (now - last) > SNAPSHOT_TTL
    if last is None:
        return True
    return _is_market_open(ticker, last)


async def refresh_one(ticker: str, hist=None, force: bool = False) -> None:
    _in_flight.add(ticker)
    errs: set[str] = _errors.get(ticker, set()).copy()
    try:
        async with AsyncSessionLocal() as session:
            existing = await read_snapshot(session, ticker)
            fetch_snap = await _should_fetch_snapshot(session, ticker, force=force)

            snapshot = None
            if fetch_snap:
                log.info("[%s] fetching snapshot", ticker)
                try:
                    if hist is None:
                        # Without pre-fetched history, _compute_returns/_compute_realized_vol
                        # each fall back to their own separate yf.download — one batched call
                        # covers both and matches the speed of the bulk refresh_all() path.
                        hist = await asyncio.to_thread(batch_download_history, [ticker])
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

            if await should_fetch(session, ticker, "earnings", EARNINGS_TTL):
                log.info("[%s] fetching earnings dates", ticker)
                try:
                    earnings_dates = await asyncio.to_thread(fetch_earnings_dates, ticker)
                    await set_last_fetch(session, ticker, "earnings")
                    errs.discard("earnings")
                except Exception as exc:
                    log.warning("[%s] earnings dates fetch failed: %s", ticker, exc)
                    errs.add("earnings")
                    earnings_dates = None
            else:
                log.info("[%s] earnings dates cached", ticker)
                earnings_dates = None

            final_snap = existing

            if snapshot is not None:
                snapshot["insider_transactions"] = (
                    txs
                    if txs is not None
                    else (existing.get("insider_transactions", []) if existing else [])
                )
                snapshot["earnings_dates"] = (
                    earnings_dates
                    if earnings_dates is not None
                    else (existing.get("earnings_dates", []) if existing else [])
                )
                await write_snapshot(session, ticker, snapshot)
                await set_last_fetch(session, ticker, "snapshot")
                final_snap = snapshot
            elif existing is not None and (txs is not None or earnings_dates is not None):
                if txs is not None:
                    existing["insider_transactions"] = txs
                if earnings_dates is not None:
                    existing["earnings_dates"] = earnings_dates
                await write_snapshot(session, ticker, existing)

            if await should_fetch(session, ticker, "fundamentals", FUNDAMENTALS_TTL):
                log.info("[%s] fetching fundamentals", ticker)
                try:
                    periods = await asyncio.to_thread(fetch_fundamentals, ticker)
                    recent = _recent_periods(periods)
                    for period, data in periods:
                        if period in recent:
                            # newest periods may have been partial when first written → refresh
                            await write_fundamentals(session, ticker, period, data, overwrite=True)
                        elif not await has_fundamentals(session, ticker, period):
                            await write_fundamentals(session, ticker, period, data)
                    await set_last_fetch(session, ticker, "fundamentals")
                    errs.discard("fundamentals")
                except Exception as exc:
                    log.warning("[%s] fundamentals fetch failed: %s", ticker, exc)
                    errs.add("fundamentals")
            else:
                log.info("[%s] fundamentals cached", ticker)

            # One score snapshot per ticker per day — the reference point "score_change"
            # (in _payload.py) diffs the live score against, to show change over the last week.
            if final_snap is not None:
                try:
                    funds = await read_all_fundamentals(session, ticker)
                    scores = compute_all(funds, final_snap)
                    if scores.get("composite_long", {}).get("score") is not None:
                        today = datetime.now(UTC).date().isoformat()
                        await write_score_history_if_missing(session, ticker, today, scores)
                except Exception as exc:
                    log.warning("[%s] score history recording failed: %s", ticker, exc)
    finally:
        _in_flight.discard(ticker)
        _errors[ticker] = errs


async def refresh_all(force: bool = False) -> None:
    global _refresh_running
    if _refresh_running:
        log.info("Refresh already in progress, skipping duplicate request")
        return
    _refresh_running = True
    try:
        await _refresh_all_impl(force=force)
    finally:
        _refresh_running = False


async def _refresh_all_impl(force: bool = False) -> None:
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
    except Exception as exc:
        log.warning("Bulk download failed (%s) — falling back to per-ticker downloads", exc)
        hist = None

    await asyncio.to_thread(init_auth)

    # curl_cffi (not requests) handles connections now — synthetic load tests showed 0
    # failures up to 40 concurrent requests and only occasional blips at 40 sustained,
    # vs. failures starting ~60. 30 keeps margin below that.
    batch_size = 30
    batch_delay = 1.5

    for i in range(0, len(ordered), batch_size):
        batch_num = i // batch_size
        if batch_num > 0:
            log.info("Re-initializing Yahoo auth (batch %d)", batch_num + 1)
            await asyncio.to_thread(init_auth)

        batch = ordered[i : i + batch_size]
        log.info("Refresh batch %d/%d: %s", batch_num + 1, -(-len(ordered) // batch_size), batch)
        results = await asyncio.gather(
            *[refresh_one(t, hist, force=force) for t in batch], return_exceptions=True
        )
        for ticker, res in zip(batch, results, strict=True):
            if isinstance(res, Exception):
                log.error("[%s] refresh failed: %s", ticker, res)
        if i + batch_size < len(ordered):
            await asyncio.sleep(batch_delay)

    log.info("Refresh complete")
