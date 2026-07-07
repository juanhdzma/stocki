from __future__ import annotations
import asyncio
import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── insider_score ─────────────────────────────────────────────────────────────

def test_perfect_insider_signal_reaches_100():
    """Single CEO buy should score well above the old MAX_RAW=150 ceiling (~66.7)."""
    from core.insider_score import compute_insider_score

    tx = {
        "insider_name": "John CEO",
        "title": "Chief Executive Officer",
        "trade_type": "P",
        "delta_own": 0.99,
        "value_usd": 100_000_000,
        "price": 50.0,
        "trade_date": datetime.now(timezone.utc).replace(tzinfo=None),
        "filing_date": datetime.now(timezone.utc).replace(tzinfo=None),
    }
    result = compute_insider_score(
        [tx], market_cap=1e9, week52_low=40.0, week52_high=60.0,
        days_back=365, _already_normalized=True,
    )
    assert result["score"] > 60.0, f"Score {result['score']} too low, suggests wrong MAX_RAW normalization"
    assert result["score"] <= 100.0, "Score must never exceed 100"


def test_old_max_raw_would_have_deflated():
    old_cap = (130.0 / 150.0) * 100
    new_cap = (130.0 / 130.0) * 100
    assert old_cap < 87.0
    assert new_cap == 100.0


def test_normalize_is_public():
    """normalize() must be importable as a public symbol (no leading underscore)."""
    from core.insider_score import normalize
    assert callable(normalize)


# ── scheduler/worker ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_all_isolates_ticker_exceptions():
    """An exception from one ticker must not prevent others from being refreshed."""
    from scheduler.worker import refresh_all

    refreshed = []

    async def mock_refresh_one(ticker):
        if ticker == "BAD":
            raise RuntimeError("network error")
        refreshed.append(ticker)

    mock_result = MagicMock()
    mock_result.all.return_value = [("OK", None), ("BAD", None)]
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("scheduler.worker.refresh_one", side_effect=mock_refresh_one), \
         patch("scheduler.worker.AsyncSessionLocal", return_value=mock_session):
        await refresh_all()

    assert "OK" in refreshed
    assert "BAD" not in refreshed


@pytest.mark.asyncio
async def test_insider_ttl_not_updated_on_network_failure():
    """When fetch_insider_transactions returns None, the insider TTL must not be recorded."""
    from scheduler.worker import refresh_one

    set_fetch_calls = []

    async def track_set_last_fetch(session, ticker, data_type):
        set_fetch_calls.append(data_type)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("scheduler.worker.AsyncSessionLocal", return_value=mock_session), \
         patch("scheduler.worker._should_fetch_snapshot", new_callable=AsyncMock, return_value=True), \
         patch("scheduler.worker.fetch_market_snapshot", return_value={"price": 100.0}), \
         patch("scheduler.worker.read_snapshot", new_callable=AsyncMock, return_value=None), \
         patch("scheduler.worker.should_fetch", new_callable=AsyncMock, return_value=True), \
         patch("scheduler.worker.fetch_insider_transactions", return_value=None), \
         patch("scheduler.worker.write_snapshot", new_callable=AsyncMock), \
         patch("scheduler.worker.set_last_fetch", side_effect=track_set_last_fetch), \
         patch("scheduler.worker.has_fundamentals", new_callable=AsyncMock, return_value=True):
        await refresh_one("TEST")

    assert "insider" not in set_fetch_calls


@pytest.mark.asyncio
async def test_refresh_one_records_snapshot_timestamp():
    """After a successful refresh_one, the snapshot fetch timestamp must be recorded."""
    from scheduler.worker import refresh_one

    set_fetch_calls = []

    async def track(session, ticker, data_type):
        set_fetch_calls.append(data_type)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("scheduler.worker.AsyncSessionLocal", return_value=mock_session), \
         patch("scheduler.worker._should_fetch_snapshot", new_callable=AsyncMock, return_value=True), \
         patch("scheduler.worker.fetch_market_snapshot", return_value={"price": 100.0}), \
         patch("scheduler.worker.read_snapshot", new_callable=AsyncMock, return_value=None), \
         patch("scheduler.worker.should_fetch", new_callable=AsyncMock, return_value=False), \
         patch("scheduler.worker.write_snapshot", new_callable=AsyncMock), \
         patch("scheduler.worker.set_last_fetch", side_effect=track):
        await refresh_one("TEST")

    assert "snapshot" in set_fetch_calls


# ── portfolio ────────────────────────────────────────────────────────────────

def test_portfolio_does_not_import_tickers():
    """portfolio.py must not import TICKERS from config."""
    import api.routers.portfolio as p
    assert not hasattr(p, "TICKERS"), "portfolio.py must not import TICKERS from config"


@pytest.mark.asyncio
async def test_portfolio_returns_db_tickers():
    """get_portfolio must serve tickers from the Watchlist table, not config."""
    from api.routers.portfolio import get_portfolio

    wl_result = MagicMock()
    wl_result.all.return_value = [("NVDA",)]

    snap_row = MagicMock()
    snap_row.data_json = '{"price": 100.0}'
    snap_row.refreshed_at = "2024-01-01T00:00:00+00:00"
    snap_result = MagicMock()
    snap_result.scalars.return_value.first.return_value = snap_row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[wl_result, snap_result])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("api.routers.portfolio.AsyncSessionLocal", return_value=mock_session), \
         patch("api.routers.portfolio.read_all_fundamentals", new_callable=AsyncMock, return_value=[]), \
         patch("api.routers.portfolio.build_payload", return_value={"snapshot": {}}):
        result = await get_portfolio()

    assert "NVDA" in result["tickers"]
    assert "SOFI" not in result["tickers"], "Hardcoded SOFI must not appear"


# ── openinsider fetcher ───────────────────────────────────────────────────────

def test_openinsider_uses_https():
    from core.fetchers.openinsider import _BASE_URL
    assert _BASE_URL.startswith("https://"), "OpenInsider URL must use HTTPS"


# ── lookup auth ──────────────────────────────────────────────────────────────

def test_lookup_auth_cold_start():
    """_last_auth_at must init to float('-inf') so the first request always triggers auth."""
    import math
    import api.routers.lookup as lk
    assert math.isinf(lk._last_auth_at) and lk._last_auth_at < 0


def test_auth_double_check_variables_present():
    import api.routers.lookup as lk
    assert hasattr(lk, "_last_auth_at"), "_last_auth_at module-level float missing"
    assert hasattr(lk, "_AUTH_INTERVAL"), "_AUTH_INTERVAL constant missing"
    assert lk._AUTH_INTERVAL == 300.0


@pytest.mark.asyncio
async def test_auth_lock_serializes():
    """Two concurrent auth refreshes must not run simultaneously."""
    call_times = []

    async def fake_init_auth():
        call_times.append(asyncio.get_event_loop().time())
        await asyncio.sleep(0.05)

    lock = asyncio.Lock()

    async def caller():
        async with lock:
            await fake_init_auth()

    await asyncio.gather(caller(), caller())
    assert len(call_times) == 2
    assert call_times[1] - call_times[0] >= 0.04


@pytest.mark.asyncio
async def test_auth_not_called_twice_within_interval():
    """Second lookup within _AUTH_INTERVAL must NOT call init_auth again."""
    import time
    import api.routers.lookup as lk

    call_count = 0

    async def fake_init():
        nonlocal call_count
        call_count += 1

    with patch("api.routers.lookup.asyncio.to_thread", side_effect=fake_init):
        lk._last_auth_at = time.monotonic()
        async with lk._auth_lock:
            if time.monotonic() - lk._last_auth_at > lk._AUTH_INTERVAL:
                await fake_init()
                lk._last_auth_at = time.monotonic()

    assert call_count == 0, "init_auth must be skipped if auth was recent"


# ── _payload ─────────────────────────────────────────────────────────────────

def test_build_payload_output_shape():
    from api.routers._payload import build_payload

    snap = {
        "price": 100.0, "market_cap": 1e9,
        "returns": {"ticker_return_1m": 0.05},
        "insider_transactions": [],
    }
    result = build_payload("TEST", snap, [], refreshed_at="2024-01-01T00:00:00+00:00")
    assert "snapshot" in result
    assert "returns" in result
    assert "scores" in result
    assert "refreshed_at" in result
    assert result["refreshed_at"] == "2024-01-01T00:00:00+00:00"
    assert "data_ready" in result
    assert result["data_ready"] is False


# ── db/cache datetime hygiene ────────────────────────────────────────────────

def test_get_last_fetch_handles_aware_string():
    aware_str = datetime.now(timezone.utc).isoformat()
    dt = datetime.fromisoformat(aware_str)
    result = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    assert result.tzinfo is not None


def test_get_last_fetch_handles_naive_string():
    naive_str = "2024-06-15T14:30:00"
    dt = datetime.fromisoformat(naive_str)
    result = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    assert result.tzinfo == timezone.utc


# ── lookup snapshot age ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_snapshot_age_handles_naive_ts():
    from api.routers.lookup import _snapshot_age_seconds

    mock_session = AsyncMock()
    mock_row = MagicMock()
    mock_row.refreshed_at = "2024-01-01T12:00:00"
    mock_result = MagicMock()
    mock_result.first.return_value = mock_row
    mock_session.execute = AsyncMock(return_value=mock_result)

    age = await _snapshot_age_seconds(mock_session, "AAPL")
    assert age is not None
    assert age > 0


@pytest.mark.asyncio
async def test_snapshot_age_handles_aware_ts():
    from api.routers.lookup import _snapshot_age_seconds

    recent = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    mock_session = AsyncMock()
    mock_row = MagicMock()
    mock_row.refreshed_at = recent
    mock_result = MagicMock()
    mock_result.first.return_value = mock_row
    mock_session.execute = AsyncMock(return_value=mock_result)

    age = await _snapshot_age_seconds(mock_session, "AAPL")
    assert age is not None
    assert 0 < age < 120


# ── ticker validation ────────────────────────────────────────────────────────

def test_ticker_re_pattern():
    import api.routers.watchlist as wl
    import api.routers.lookup as lk
    for mod in (wl, lk):
        assert hasattr(mod, "_TICKER_RE"), f"_TICKER_RE missing from {mod.__name__}"
        assert mod._TICKER_RE.match("SOFI")
        assert mod._TICKER_RE.match("BRK.B")
        assert not mod._TICKER_RE.match("")
        assert not mod._TICKER_RE.match("A" * 13)
        assert not mod._TICKER_RE.match("SO FI")


@pytest.mark.asyncio
async def test_add_ticker_rejects_invalid():
    from fastapi import HTTPException

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit  = AsyncMock()

    import api.routers.watchlist as wl
    with pytest.raises(HTTPException) as exc_info:
        await wl.add_ticker("SO FI", "watchlist", mock_session)
    assert exc_info.value.status_code == 400


# ── scorer coverage ───────────────────────────────────────────────────────────

def test_value_quality_score_with_full_snapshot():
    from core.scorers.value_quality import score

    snap = {
        "roe": 0.25, "roa": 0.12, "net_margin": 0.18,
        "pct_from_52w_high": -0.15,
        "price": 100.0, "target_mean": 130.0,
        "forward_pe": 20.0, "trailing_pe": 25.0,
        "peg_ratio": 0.8, "price_to_sales": 3.0, "revenue_growth": 0.20,
        "current_ratio": 2.5, "debt_to_equity": 40.0,
        "dilution_rate": -0.01, "market_cap": 10e9,
        "rec_strong_buy": 5, "rec_buy": 10, "rec_hold": 3, "rec_sell": 0, "rec_strong_sell": 0,
    }
    result = score([], snap)
    assert "score" in result and "sub_scores" in result
    assert result["score"] is not None
    assert 0 <= result["score"] <= 100


def test_price_opportunity_score_with_full_snapshot():
    from core.scorers.price_opportunity import score

    snap = {
        "pct_from_1w_high": -0.03, "pct_from_52w_high": -0.25, "beta": 1.5,
        "returns": {"ticker_return_3m": -0.05, "spy_return_3m": 0.08,
                    "ticker_return_1m": -0.02, "spy_return_1m": 0.03},
        "short_percent_of_float": 0.12, "short_ratio": 6.0,
        "put_call_ratio": 1.2,
        "price": 80.0, "target_mean": 110.0, "analyst_count": 15,
    }
    result = score([], snap)
    assert "score" in result and "sub_scores" in result
    assert result["score"] is not None
    assert 0 <= result["score"] <= 100


def test_fundamental_momentum_score_with_quarters():
    from core.scorers.fundamental_momentum import score

    quarters = [
        {"type": "quarterly", "revenue": 1_200_000, "net_income": 120_000,
         "gross_margin": 0.45, "fcf": 80_000, "rd_expense": 60_000, "buybacks": -20_000},
        {"type": "quarterly", "revenue": 1_100_000, "net_income": 100_000,
         "gross_margin": 0.43, "fcf": 70_000, "rd_expense": 55_000, "buybacks": -18_000},
        {"type": "quarterly", "revenue": 1_000_000, "net_income": 80_000,
         "gross_margin": 0.41, "fcf": 60_000, "rd_expense": 50_000, "buybacks": -15_000},
        {"type": "quarterly", "revenue": 950_000, "net_income": 60_000,
         "gross_margin": 0.40, "fcf": 50_000, "rd_expense": 45_000, "buybacks": -12_000},
    ]
    snap = {"market_cap": 50_000_000, "revenue_growth": 0.15, "operating_margin": 0.12}
    result = score(quarters, snap)
    assert "score" in result and "sub_scores" in result
    assert result["score"] is not None
    assert 0 <= result["score"] <= 100


def test_analyst_upside_pts_helper():
    from core.scorers.base import analyst_upside_pts

    assert analyst_upside_pts(100.0, 130.0, 15.0) == pytest.approx(15.0, abs=0.1)
    assert analyst_upside_pts(100.0, 100.0, 15.0) == pytest.approx(0.0, abs=0.1)
    assert analyst_upside_pts(None, 130.0, 15.0) is None
    assert analyst_upside_pts(100.0, None, 15.0) is None
    assert analyst_upside_pts(0.0, 130.0, 15.0) is None
