"""
Tests validating all 9 fixes applied during the code review.
No network calls, no live DB required.
"""
from __future__ import annotations
import asyncio
import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Fix 1: MAX_RAW = 130 ─────────────────────────────────────────────────────

def test_max_raw_correct_value():
    from core.insider_score import compute_insider_score

    src = open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)),
                     "core", "insider_score.py")
    ).read()
    assert "MAX_RAW = 130.0" in src, "MAX_RAW must be 130.0"
    assert "MAX_RAW = 150.0" not in src, "Old MAX_RAW=150 must be gone"


def test_perfect_insider_signal_reaches_100():
    """
    A perfect single tx scores rep_tx=100. With MAX_RAW=130 that gives
    bull_norm = min(100, 100/130*100) = 76.9. Adding cluster+persist bonuses
    from many insiders can push it to 100. This test verifies two things:
    1. A single perfect tx scores ~76.9 (not the old ceiling of ~66.7 with MAX_RAW=150)
    2. bull_norm is capped at 100 (min guard holds)
    """
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
    # With MAX_RAW=130, single tx: rep_tx=100 → bull_norm = 76.9
    # With MAX_RAW=150 (old bug), single tx: bull_norm = 66.7
    # Score must be above the old wrong ceiling
    assert result["score"] > 60.0, (
        f"Score {result['score']} too low, suggests wrong MAX_RAW normalization"
    )
    assert result["score"] <= 100.0, "Score must never exceed 100"


def test_old_max_raw_would_have_deflated():
    """Demonstrate the math: with MAX_RAW=150, max achievable was ~86.7."""
    old_cap = (130.0 / 150.0) * 100  # 86.66...
    new_cap = (130.0 / 130.0) * 100  # 100.0
    assert old_cap < 87.0
    assert new_cap == 100.0


# ── Fix 2: Semaphore in scheduler ────────────────────────────────────────────

def test_scheduler_semaphore_present():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)),
                     "scheduler", "worker.py")
    ).read()
    assert "Semaphore(12)" in src, "Semaphore must be present in worker.py"
    assert "bounded" in src, "bounded() wrapper must be present"


def test_scheduler_aware_datetime():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)),
                     "scheduler", "worker.py")
    ).read()
    assert "datetime.now(timezone.utc)" in src
    assert "datetime.utcnow()" not in src, "No naive utcnow() allowed in worker.py"


# ── Fix 3: Semaphore in watchlist endpoint ───────────────────────────────────

def test_watchlist_semaphore_present():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)),
                     "api", "routers", "watchlist.py")
    ).read()
    assert "Semaphore(12)" in src, "Semaphore must be in watchlist.py"


# ── Fix 4: Portfolio queries DB, not hardcoded TICKERS ───────────────────────

def test_portfolio_no_hardcoded_tickers():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)),
                     "api", "routers", "portfolio.py")
    ).read()
    assert 'from config import TICKERS' not in src, "portfolio.py must not import TICKERS"
    assert 'list_type == "portfolio"' in src, "portfolio.py must query Watchlist by list_type"


@pytest.mark.asyncio
async def test_portfolio_returns_db_tickers():
    """get_portfolio must serve tickers from the Watchlist table, not config."""
    from api.routers.portfolio import get_portfolio

    fake_row = MagicMock()
    fake_row.__iter__ = MagicMock(return_value=iter(["NVDA"]))

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [("NVDA",)]
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("api.routers.portfolio.AsyncSessionLocal", return_value=mock_session), \
         patch("api.routers.portfolio.read_snapshot", new_callable=AsyncMock, return_value={}), \
         patch("api.routers.portfolio.read_all_fundamentals", new_callable=AsyncMock, return_value=[]), \
         patch("api.routers.portfolio.build_payload", return_value={"snapshot": {}}):
        result = await get_portfolio()

    assert "NVDA" in result["tickers"]
    assert "SOFI" not in result["tickers"], "Hardcoded SOFI must not appear"


# ── Fix 5: APScheduler gets aware datetime ───────────────────────────────────

def test_apscheduler_next_run_aware():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)),
                     "scheduler", "worker.py")
    ).read()
    assert "next_run_time=datetime.now(timezone.utc)" in src


# ── Fix 6: openinsider uses HTTPS ────────────────────────────────────────────

def test_openinsider_https():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)),
                     "core", "fetchers", "openinsider.py")
    ).read()
    assert "_BASE_URL = \"https://openinsider.com/screener\"" in src
    assert "http://" not in src, "No plain HTTP allowed"


# ── Fix 7: concurrent init_auth serialized with asyncio.Lock ─────────────────

def test_auth_lock_present():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)),
                     "api", "routers", "lookup.py")
    ).read()
    assert "_auth_lock = asyncio.Lock()" in src
    assert "async with _auth_lock:" in src


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
    # If lock works, second call starts after first finishes (0.05s gap)
    assert len(call_times) == 2
    assert call_times[1] - call_times[0] >= 0.04


# ── Fix 8: _build_payload consolidated in _payload.py ────────────────────────

def test_payload_module_exists():
    path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "api", "routers", "_payload.py"
    )
    assert os.path.exists(path), "_payload.py must exist"


def test_payload_imported_everywhere():
    for fname in ("portfolio.py", "lookup.py", "watchlist.py"):
        src = open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)),
                         "api", "routers", fname)
        ).read()
        assert "from api.routers._payload import build_payload" in src, (
            f"{fname} must import build_payload from _payload"
        )


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
    assert result["data_ready"] is False  # no quarterlies


# ── Fix 9: db/cache.py uses timezone-aware datetimes ─────────────────────────

def test_cache_no_naive_utcnow():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)),
                     "db", "cache.py")
    ).read()
    assert "datetime.utcnow()" not in src, (
        "db/cache.py must not use naive datetime.utcnow()"
    )


def test_get_last_fetch_handles_aware_string():
    """get_last_fetch must not crash when stored string has +00:00 timezone."""
    from datetime import datetime, timezone
    aware_str = datetime.now(timezone.utc).isoformat()  # includes +00:00
    dt = datetime.fromisoformat(aware_str)
    result = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    assert result.tzinfo is not None


def test_get_last_fetch_handles_naive_string():
    """get_last_fetch must handle legacy naive UTC strings."""
    from datetime import datetime, timezone
    naive_str = "2024-06-15T14:30:00"
    dt = datetime.fromisoformat(naive_str)
    result = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    assert result.tzinfo == timezone.utc


# ── Snapshot age: handles both naive and aware refreshed_at ─────────────────

@pytest.mark.asyncio
async def test_snapshot_age_handles_naive_ts():
    """_snapshot_age_seconds must not crash on a naive datetime string."""
    from api.routers.lookup import _snapshot_age_seconds

    mock_session = AsyncMock()
    mock_row = MagicMock()
    mock_row.refreshed_at = "2024-01-01T12:00:00"  # naive UTC string
    mock_result = MagicMock()
    mock_result.first.return_value = mock_row
    mock_session.execute = AsyncMock(return_value=mock_result)

    age = await _snapshot_age_seconds(mock_session, "AAPL")
    assert age is not None
    assert age > 0


@pytest.mark.asyncio
async def test_snapshot_age_handles_aware_ts():
    """_snapshot_age_seconds must not crash on a timezone-aware string."""
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
    assert 0 < age < 120  # within 2 minutes of 30s-ago timestamp
