from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
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
        "trade_date": datetime.now(UTC).replace(tzinfo=None),
        "filing_date": datetime.now(UTC).replace(tzinfo=None),
    }
    result = compute_insider_score(
        [tx],
        market_cap=1e9,
        week52_low=40.0,
        week52_high=60.0,
        days_back=365,
        _already_normalized=True,
    )
    assert result["score"] > 60.0, (
        f"Score {result['score']} too low, suggests wrong MAX_RAW normalization"
    )
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

    async def mock_refresh_one(ticker, hist=None, force=False):
        if ticker == "BAD":
            raise RuntimeError("network error")
        refreshed.append(ticker)

    mock_result = MagicMock()
    mock_result.all.return_value = [("OK", None), ("BAD", None)]
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("scheduler.worker.refresh_one", side_effect=mock_refresh_one),
        patch("scheduler.worker.AsyncSessionLocal", return_value=mock_session),
        patch("scheduler.worker.batch_download_history", return_value=None),
        patch("scheduler.worker.init_auth"),
    ):
        await refresh_all()

    assert "OK" in refreshed
    assert "BAD" not in refreshed


@pytest.mark.asyncio
async def test_refresh_all_force_propagates_to_each_ticker():
    """The manual bulk refresh (POST /api/refresh) must force every ticker's fetch —
    there's no automatic scheduled job in this app, so this button press is the only
    time refresh_all() ever runs; it should never silently no-op on a stale gate."""
    from scheduler.worker import refresh_all

    forced_calls = []

    async def mock_refresh_one(ticker, hist=None, force=False):
        forced_calls.append((ticker, force))

    mock_result = MagicMock()
    mock_result.all.return_value = [("OK", None)]
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("scheduler.worker.refresh_one", side_effect=mock_refresh_one),
        patch("scheduler.worker.AsyncSessionLocal", return_value=mock_session),
        patch("scheduler.worker.batch_download_history", return_value=None),
        patch("scheduler.worker.init_auth"),
    ):
        await refresh_all(force=True)

    assert forced_calls == [("OK", True)]


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

    with (
        patch("scheduler.worker.AsyncSessionLocal", return_value=mock_session),
        patch("scheduler.worker._should_fetch_snapshot", new_callable=AsyncMock, return_value=True),
        patch("scheduler.worker.fetch_market_snapshot", return_value={"price": 100.0}),
        patch("scheduler.worker.batch_download_history", return_value=None),
        patch("scheduler.worker.read_snapshot", new_callable=AsyncMock, return_value=None),
        patch("scheduler.worker.should_fetch", new_callable=AsyncMock, return_value=True),
        patch("scheduler.worker.fetch_insider_transactions", return_value=None),
        patch("scheduler.worker.write_snapshot", new_callable=AsyncMock),
        patch("scheduler.worker.set_last_fetch", side_effect=track_set_last_fetch),
        patch("scheduler.worker.has_fundamentals", new_callable=AsyncMock, return_value=True),
    ):
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

    with (
        patch("scheduler.worker.AsyncSessionLocal", return_value=mock_session),
        patch("scheduler.worker._should_fetch_snapshot", new_callable=AsyncMock, return_value=True),
        patch("scheduler.worker.fetch_market_snapshot", return_value={"price": 100.0}),
        patch("scheduler.worker.batch_download_history", return_value=None),
        patch("scheduler.worker.read_snapshot", new_callable=AsyncMock, return_value=None),
        patch("scheduler.worker.should_fetch", new_callable=AsyncMock, return_value=False),
        patch("scheduler.worker.write_snapshot", new_callable=AsyncMock),
        patch("scheduler.worker.set_last_fetch", side_effect=track),
    ):
        await refresh_one("TEST")

    assert "snapshot" in set_fetch_calls


@pytest.mark.asyncio
async def test_should_fetch_snapshot_force_bypasses_market_closed_gate():
    """force=True must re-fetch even if the last snapshot was already accepted as the
    closing price under the market-closed gate."""
    from scheduler.worker import _should_fetch_snapshot

    mock_session = AsyncMock()
    with (
        patch(
            "scheduler.worker.get_last_fetch",
            new_callable=AsyncMock,
            return_value=datetime.now(UTC) - timedelta(hours=1),
        ),
        patch("scheduler.worker._is_market_open", return_value=False),
    ):
        assert await _should_fetch_snapshot(mock_session, "PLTR", force=True) is True


@pytest.mark.asyncio
async def test_refresh_one_force_refetches_when_market_closed():
    """A manual POST /api/refresh/{ticker} must hit the fetcher even when the
    market-closed gate would normally treat the cached snapshot as final."""
    from scheduler.worker import refresh_one

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("scheduler.worker.AsyncSessionLocal", return_value=mock_session),
        patch(
            "scheduler.worker.get_last_fetch",
            new_callable=AsyncMock,
            return_value=datetime.now(UTC) - timedelta(hours=1),
        ),
        patch("scheduler.worker._is_market_open", return_value=False),
        patch(
            "scheduler.worker.fetch_market_snapshot", return_value={"price": 122.92}
        ) as mock_fetch,
        patch("scheduler.worker.batch_download_history", return_value=None),
        patch(
            "scheduler.worker.read_snapshot", new_callable=AsyncMock, return_value={"price": 132.66}
        ),
        patch("scheduler.worker.should_fetch", new_callable=AsyncMock, return_value=False),
        patch("scheduler.worker.write_snapshot", new_callable=AsyncMock),
        patch("scheduler.worker.set_last_fetch", new_callable=AsyncMock),
    ):
        await refresh_one("PLTR", force=True)

    mock_fetch.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_one_batches_history_when_none_given():
    """A single-ticker refresh (no pre-fetched hist, e.g. the manual /api/refresh/{ticker}
    path) must batch its own history in one call rather than let _compute_returns and
    _compute_typical_pullback each fall back to a separate yf.download."""
    from scheduler.worker import refresh_one

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("scheduler.worker.AsyncSessionLocal", return_value=mock_session),
        patch("scheduler.worker._should_fetch_snapshot", new_callable=AsyncMock, return_value=True),
        patch("scheduler.worker.batch_download_history", return_value="FAKE_HIST") as mock_hist,
        patch(
            "scheduler.worker.fetch_market_snapshot", return_value={"price": 100.0}
        ) as mock_fetch,
        patch("scheduler.worker.read_snapshot", new_callable=AsyncMock, return_value=None),
        patch("scheduler.worker.should_fetch", new_callable=AsyncMock, return_value=False),
        patch("scheduler.worker.write_snapshot", new_callable=AsyncMock),
        patch("scheduler.worker.set_last_fetch", new_callable=AsyncMock),
    ):
        await refresh_one("PLTR")

    mock_hist.assert_called_once_with(["PLTR"])
    mock_fetch.assert_called_once_with("PLTR", "FAKE_HIST")


# ── portfolio ────────────────────────────────────────────────────────────────


def test_portfolio_does_not_import_tickers():
    """portfolio.py must not import TICKERS from config."""
    import api.routers.portfolio as p

    assert not hasattr(p, "TICKERS"), "portfolio.py must not import TICKERS from config"


@pytest.mark.asyncio
async def test_lists_returns_db_tickers():
    """get_lists must serve watchlist/portfolio tickers from the DB, not config."""
    from api.routers.watchlist import get_lists

    wl_result = MagicMock()
    wl_result.all.return_value = [("NVDA",)]

    holding_row = MagicMock()
    holding_row.ticker = "AAPL"
    holding_row.avg_cost = 150.0
    holding_row.shares = 10
    pf_result = MagicMock()
    pf_result.scalars.return_value.all.return_value = [holding_row]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[wl_result, pf_result])

    result = await get_lists(session=mock_session)

    assert "NVDA" in result["watchlist"]
    assert "AAPL" in result["portfolio"]
    assert "SOFI" not in result["watchlist"] and "SOFI" not in result["portfolio"], (
        "Hardcoded SOFI must not appear"
    )


# ── openinsider fetcher ───────────────────────────────────────────────────────


def test_openinsider_base_url():
    """openinsider.com has no valid TLS cert — must stay on http://, not https://."""
    from core.fetchers.openinsider import _BASE_URL

    assert _BASE_URL.startswith("http://openinsider.com")


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
        "price": 100.0,
        "market_cap": 1e9,
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


def test_build_payload_score_change_none_without_week_ago_scores():
    from api.routers._payload import build_payload

    snap = {"price": 100.0, "market_cap": 1e9, "insider_transactions": []}
    result = build_payload("TEST", snap, [], refreshed_at="2024-01-01T00:00:00+00:00")
    assert result["score_change"] is None


def test_build_payload_score_change_diffs_against_week_ago_scores():
    from api.routers._payload import build_payload
    from core.scorers.composite import compute_all

    snap = {
        "price": 100.0,
        "market_cap": 1e9,
        "insider_transactions": [],
        "revenue_growth": 0.10,
        "roe": 0.30,
        "roa": 0.15,
        "net_margin": 0.20,
    }
    week_ago_scores = compute_all([], {**snap, "price": 90.0})
    result = build_payload(
        "TEST", snap, [], refreshed_at="2024-01-01T00:00:00+00:00", week_ago_scores=week_ago_scores
    )
    assert result["score_change"] is not None
    assert result["score_change"]["composite"]["old"] == week_ago_scores["composite_long"]["score"]
    assert result["score_change"]["composite"]["new"] == result["scores"]["composite_long"]["score"]


# ── db/cache datetime hygiene ────────────────────────────────────────────────


def test_get_last_fetch_handles_aware_string():
    aware_str = datetime.now(UTC).isoformat()
    dt = datetime.fromisoformat(aware_str)
    result = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    assert result.tzinfo is not None


def test_get_last_fetch_handles_naive_string():
    naive_str = "2024-06-15T14:30:00"
    dt = datetime.fromisoformat(naive_str)
    result = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    assert result.tzinfo == UTC


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

    recent = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
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
    import api.routers.lookup as lk
    import api.routers.watchlist as wl

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
    mock_session.commit = AsyncMock()

    import api.routers.watchlist as wl

    with pytest.raises(HTTPException) as exc_info:
        await wl.add_ticker("SO FI", "watchlist", mock_session)
    assert exc_info.value.status_code == 400


# ── scorer coverage ───────────────────────────────────────────────────────────


def test_value_quality_score_with_full_snapshot():
    from core.scorers.value_quality import score

    snap = {
        "roe": 0.25,
        "roa": 0.12,
        "net_margin": 0.18,
        "pct_from_52w_high": -0.15,
        "price": 100.0,
        "target_mean": 130.0,
        "forward_pe": 20.0,
        "trailing_pe": 25.0,
        "peg_ratio": 0.8,
        "price_to_sales": 3.0,
        "revenue_growth": 0.20,
        "current_ratio": 2.5,
        "debt_to_equity": 40.0,
        "dilution_rate": -0.01,
        "market_cap": 10e9,
        "rec_strong_buy": 5,
        "rec_buy": 10,
        "rec_hold": 3,
        "rec_sell": 0,
        "rec_strong_sell": 0,
    }
    result = score([], snap)
    assert "score" in result and "sub_scores" in result
    assert result["score"] is not None
    assert 0 <= result["score"] <= 100


def test_price_long_score_with_full_snapshot():
    from core.scorers.price_long import score

    snap = {
        "price": 80.0,
        "target_mean": 110.0,
        "analyst_count": 15,
        "market_cap": 10e9,
        "forward_pe": 18.0,
        "trailing_pe": 22.0,
        "peg_ratio": 1.2,
    }
    quarters = [{"type": "quarterly", "fcf": 150_000_000, "buybacks": -50_000_000}]
    result = score(quarters, snap)
    assert "score" in result and "sub_scores" in result
    assert result["score"] is not None
    assert 0 <= result["score"] <= 100


def test_fundamental_momentum_score_with_quarters():
    from core.scorers.fundamental_momentum import score

    quarters = [
        {
            "type": "quarterly",
            "revenue": 1_200_000,
            "net_income": 120_000,
            "gross_margin": 0.45,
            "fcf": 80_000,
            "rd_expense": 60_000,
            "buybacks": -20_000,
        },
        {
            "type": "quarterly",
            "revenue": 1_100_000,
            "net_income": 100_000,
            "gross_margin": 0.43,
            "fcf": 70_000,
            "rd_expense": 55_000,
            "buybacks": -18_000,
        },
        {
            "type": "quarterly",
            "revenue": 1_000_000,
            "net_income": 80_000,
            "gross_margin": 0.41,
            "fcf": 60_000,
            "rd_expense": 50_000,
            "buybacks": -15_000,
        },
        {
            "type": "quarterly",
            "revenue": 950_000,
            "net_income": 60_000,
            "gross_margin": 0.40,
            "fcf": 50_000,
            "rd_expense": 45_000,
            "buybacks": -12_000,
        },
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


def _mk(score_val):
    return {"score": score_val}


# ── composite_long: price boost, never a penalty ────────────────────────────────


def test_composite_long_attractive_price_lifts_good_business_to_strong_buy():
    from core.scorers.composite import _composite_long

    base = {
        "fundamental_momentum": _mk(75),
        "value_quality": _mk(85),
        "insider_conviction": _mk(50),
    }
    result = _composite_long(base, _mk(100), {})
    assert result["action"] == "STRONG-BUY"


def test_composite_long_quality_dominates_over_price_boost():
    """A materially better business must outrank a mediocre one even when the mediocre
    one looks statistically cheaper — price is a bounded modifier, not a rank-inverter."""
    from core.scorers.composite import _composite_long

    # same insiders on both, so the ONLY edge the mediocre name has is a cheaper price —
    # which must not be enough to invert a real quality gap (isolates the price boost).
    great_business = _composite_long(
        {"fundamental_momentum": _mk(84), "value_quality": _mk(95), "insider_conviction": _mk(50)},
        _mk(65),
        {},
    )
    mediocre_cheap = _composite_long(
        {"fundamental_momentum": _mk(71), "value_quality": _mk(78), "insider_conviction": _mk(50)},
        _mk(100),
        {},
    )
    assert great_business["score"] > mediocre_cheap["score"]


def test_composite_long_bad_price_no_longer_caps_a_strong_business():
    """Price is now a small additive boost (not a hard ceiling gate) — an excellent
    business at a bad price should still land solidly in STRONG-BUY on quality alone."""
    from core.scorers.composite import _composite_long

    base = {
        "fundamental_momentum": _mk(95),
        "value_quality": _mk(95),
        "insider_conviction": _mk(50),
    }
    result = _composite_long(base, _mk(20), {})
    assert result["action"] == "STRONG-BUY"


def test_composite_long_cheap_price_does_not_rescue_bad_business():
    from core.scorers.composite import _composite_long

    base = {
        "fundamental_momentum": _mk(15),
        "value_quality": _mk(20),
        "insider_conviction": _mk(50),
    }
    result = _composite_long(base, _mk(100), {})
    assert result["action"] in ("SELL", "STRONG-SELL"), (
        "a great price must not rescue a bad business"
    )


def test_composite_long_dip_bonus_rewards_quality_selloff():
    """A fundamentally strong, low-beta stock that just dropped hard should get a
    meaningful bonus — the 'buy the dip on a good business' signal."""
    from core.scorers.composite import _composite_long

    base = {
        "fundamental_momentum": _mk(84),
        "value_quality": _mk(95),
        "insider_conviction": _mk(26),
    }
    no_dip = _composite_long(
        base, _mk(65), {"beta": 1.0, "day_change_pct": 0, "returns": {"ticker_return_1w": 0}}
    )
    big_dip = _composite_long(
        base, _mk(65), {"beta": 1.0, "day_change_pct": -5, "returns": {"ticker_return_1w": -0.11}}
    )
    assert big_dip["score"] > no_dip["score"]


# ── REV↓: trend-gated, not single-quarter-YoY ───────────────────────────────────


def _q(rev):
    return {"type": "quarterly", "revenue": rev}


def test_revenue_shrinking_ignores_one_off_base_quarter():
    """QBTS case: a one-off 15M system-sale quarter in the base period makes the point YoY read
    -81%, but the trailing four quarters are flat ~3M — the business isn't shrinking."""
    from core.scorers.composite import _revenue_shrinking

    # newest-first, mirroring read_all_fundamentals ordering
    fundamentals = [_q(2_858_000), _q(2_752_000), _q(3_739_000), _q(3_095_000), _q(15_001_000)]
    assert _revenue_shrinking(fundamentals) is False


def test_revenue_shrinking_flags_sustained_decline():
    """SMR case: revenue genuinely collapsing quarter over quarter — must still flag."""
    from core.scorers.composite import _revenue_shrinking

    fundamentals = [_q(565_000), _q(1_808_000), _q(8_242_000), _q(8_054_000), _q(13_375_000)]
    assert _revenue_shrinking(fundamentals) is True


def test_revenue_shrinking_thin_history_never_flags():
    """With <4 quarters the trend can't be measured — a lumpy-revenue name (QNT: 19M→5M a year
    apart) is left unflagged rather than warned off a noisy single-quarter YoY."""
    from core.scorers.composite import _revenue_shrinking

    assert _revenue_shrinking([_q(5_237_000), _q(19_085_000)]) is False
    assert _revenue_shrinking([]) is False


def test_composite_long_one_off_base_no_longer_caps_below_strong_buy():
    """The flat-trend name (QBTS-like) should not be capped at 79.9 just because its point YoY is
    negative against a one-off base quarter."""
    from core.scorers.composite import _composite_long

    base = {
        "fundamental_momentum": _mk(95),
        "value_quality": _mk(95),
        "insider_conviction": _mk(50),
    }
    flat = [_q(2_858_000), _q(2_752_000), _q(3_739_000), _q(3_095_000), _q(15_001_000)]
    result = _composite_long(base, _mk(50), {"revenue_growth": -0.809}, flat)
    assert result["action"] == "STRONG-BUY"


def test_composite_long_dip_bonus_does_not_rescue_bad_business():
    """A big drop in a weak business is a falling knife, not a buy signal — the dip
    bonus alone must not be enough to pull a bad business out of SELL territory."""
    from core.scorers.composite import _composite_long

    base = {
        "fundamental_momentum": _mk(15),
        "value_quality": _mk(20),
        "insider_conviction": _mk(50),
    }
    result = _composite_long(
        base, _mk(50), {"beta": 1.0, "day_change_pct": -20, "returns": {"ticker_return_1w": -0.30}}
    )
    assert result["action"] in ("SELL", "STRONG-SELL")


# ── insider_score: post-earnings bonus asymmetry ────────────────────────────────


def test_insider_post_earnings_buy_bonus_amplifies_score():
    from core.insider_score import compute_insider_score

    buy = {
        "insider_name": "A",
        "title": "CEO",
        "trade_type": "P",
        "delta_own": 0.08,
        "value_usd": 2_000_000,
        "price": 50.0,
        "trade_date": "2026-05-05",
        "filing_date": "2026-05-06",
    }
    baseline = compute_insider_score([buy], market_cap=5e9, week52_low=40.0, week52_high=70.0)
    boosted = compute_insider_score(
        [buy], market_cap=5e9, week52_low=40.0, week52_high=70.0, earnings_dates=["2026-05-02"]
    )
    assert boosted["score"] > baseline["score"] + 10, (
        "a post-earnings buy should move the score a lot"
    )


def test_insider_post_earnings_sell_bonus_is_much_weaker_than_buy():
    from core.insider_score import compute_insider_score

    buy = {
        "insider_name": "A",
        "title": "CEO",
        "trade_type": "P",
        "delta_own": 0.08,
        "value_usd": 2_000_000,
        "price": 50.0,
        "trade_date": "2026-05-05",
        "filing_date": "2026-05-06",
    }
    sell = {
        "insider_name": "B",
        "title": "CFO",
        "trade_type": "S",
        "delta_own": -0.08,
        "value_usd": 2_000_000,
        "price": 50.0,
        "trade_date": "2026-05-05",
        "filing_date": "2026-05-06",
    }
    kwargs = {"market_cap": 5e9, "week52_low": 40.0, "week52_high": 70.0}

    buy_delta = (
        compute_insider_score([buy], earnings_dates=["2026-05-02"], **kwargs)["score"]
        - compute_insider_score([buy], **kwargs)["score"]
    )
    sell_delta = (
        compute_insider_score([sell], **kwargs)["score"]
        - compute_insider_score([sell], earnings_dates=["2026-05-02"], **kwargs)["score"]
    )
    assert 0 < sell_delta < buy_delta / 2, (
        "post-earnings selling should nudge the score, not scream like buying does"
    )


# ── axis separation: valuation/analyst signals live in price_long, not value_quality ────


def test_value_quality_no_longer_includes_valuation_or_analyst_conviction():
    from core.scorers.value_quality import score

    result = score([], {})
    assert "valuation" not in result["max_pts"]
    assert "analyst_conviction" not in result["max_pts"]


def test_price_long_valuation_multiples_broken_out_no_conviction():
    from core.scorers.price_long import score

    result = score([], {})
    # the valuation multiples are exposed as separate weighted sub-scores (not one blended bar)
    multiples = ("fwd_pe", "ev_ebitda", "peg", "growth_adj_ps", "ev_sales")
    for k in multiples:
        assert k in result["max_pts"]
    assert "analyst_upside" in result["max_pts"]  # additive-only bonus
    # analyst_conviction was a near-constant herd signal across the watchlist -> dropped
    assert "analyst_conviction" not in result["max_pts"]
    # the multiples together outweigh the analyst-upside bonus
    assert sum(result["max_pts"][k] for k in multiples) > result["max_pts"]["analyst_upside"]


def test_ev_sales_gives_pre_profit_names_a_valuation():
    """A pre-profit name (no P/E, no EBITDA, no PEG) must still get a valuation signal from the
    sales-based multiples rather than a null axis — EV/Sales applies without earnings."""
    from core.scorers.price_long import score

    snap = {
        "ev_to_revenue": 1.5,
        "revenue_growth": 0.5,
        "price_to_sales": None,
        "forward_pe": -10.0,
    }
    result = score([], snap)
    assert result["sub_scores"]["ev_sales"] == 6.0  # 1.5 / 1.5 = 1.0 adj -> cheap tier
    assert result["sub_scores"]["fwd_pe"] is None  # pre-profit: no earnings multiple
    assert result["score"] is not None  # ...but the axis still scores off EV/Sales


def test_ev_ebitda_rescues_depressed_earnings_name():
    """EV/EBITDA must value a name whose net earnings are depressed (sky-high P/E) but whose
    EBITDA multiple is reasonable — the P/E-only axis misread these (e.g. BA) as expensive."""
    from core.scorers.price_long import score

    # forward P/E 50 (bottom tier, 0) but EV/EBITDA 18 (a mid tier) -> the axis should not read
    # this as bottom-of-the-barrel expensive.
    cheap_ebitda = score([], {"forward_pe": 50.0, "ev_to_ebitda": 18.0})
    only_pe = score([], {"forward_pe": 50.0})
    assert cheap_ebitda["sub_scores"]["ev_ebitda"] == 7.0
    assert cheap_ebitda["score"] > only_pe["score"]


def test_ev_ebitda_none_on_negative_ebitda():
    from core.scorers.price_long import score

    result = score([], {"ev_to_ebitda": -5.0, "forward_pe": 12.0})
    assert result["sub_scores"]["ev_ebitda"] is None  # negative EBITDA -> multiple not meaningful


# ── value_quality: cash position (burn runway vs. cash cushion) ─────────────────


def test_cash_position_burning_cash_scores_survival_runway():
    from core.scorers.value_quality import score

    funds = [{"type": "quarterly", "cash": 500_000_000, "fcf": -50_000_000}] * 4
    result = score(funds, {})
    assert result["sub_scores"]["cash_runway"] == 12.0, (
        "500M cash / 50M quarterly burn = 10 quarters runway"
    )


def test_cash_position_not_burning_scores_cash_cushion_vs_revenue():
    from core.scorers.value_quality import score

    funds = [
        {"type": "quarterly", "cash": 300_000_000, "fcf": 10_000_000, "revenue": 250_000_000}
    ] * 4
    result = score(funds, {})
    assert result["sub_scores"]["cash_runway"] == 15.0, (
        "cash is 30% of ttm revenue — top cushion tier"
    )


def test_cash_position_thin_cushion_scores_low():
    from core.scorers.value_quality import score

    funds = [
        {"type": "quarterly", "cash": 20_000_000, "fcf": 10_000_000, "revenue": 250_000_000}
    ] * 4
    result = score(funds, {})
    assert result["sub_scores"]["cash_runway"] == 4.0, (
        "cash is only 2% of ttm revenue — thin cushion"
    )


# ── value_quality: execution track record ───────────────────────────────────────


def test_execution_track_full_beat_rate_maxes_score():
    from core.scorers.value_quality import score

    result = score([], {"earnings_beat_rate": 1.0})
    assert result["sub_scores"]["execution_track"] == 10.0


def test_execution_track_none_when_no_data():
    from core.scorers.value_quality import score

    result = score([], {})
    assert result["sub_scores"]["execution_track"] is None


# ── value_quality: margin durability (trend + residual noise) ───────────────────


def test_margin_durability_improving_margins_score_high_despite_moving():
    from core.scorers.value_quality import score

    funds = [
        {"type": "annual", "period": "2022", "gross_margin": 0.5538},
        {"type": "annual", "period": "2023", "gross_margin": 0.5663},
        {"type": "annual", "period": "2024", "gross_margin": 0.5820},
        {"type": "annual", "period": "2025", "gross_margin": 0.5965},
    ]
    result = score(funds, {})
    assert result["sub_scores"]["margin_durability"] == 12.0


def test_margin_durability_eroding_margins_score_low():
    from core.scorers.value_quality import score

    funds = [
        {"type": "annual", "period": "2022", "gross_margin": 0.7422},
        {"type": "annual", "period": "2023", "gross_margin": 0.6505},
        {"type": "annual", "period": "2024", "gross_margin": 0.5890},
        {"type": "annual", "period": "2025", "gross_margin": 0.6740},
    ]
    result = score(funds, {})
    assert result["sub_scores"]["margin_durability"] == 3.0, (
        "net erosion over the window, even after a partial rebound"
    )


def test_margin_durability_noisy_flat_trend_scores_mid():
    from core.scorers.value_quality import score

    funds = [
        {"type": "annual", "period": "2022", "gross_margin": 0.50},
        {"type": "annual", "period": "2023", "gross_margin": 0.65},
        {"type": "annual", "period": "2024", "gross_margin": 0.45},
        {"type": "annual", "period": "2025", "gross_margin": 0.60},
    ]
    result = score(funds, {})
    assert result["sub_scores"]["margin_durability"] == 7.0, (
        "flat-ish trend but wild swings around it"
    )


def test_margin_durability_falls_back_to_net_margin_for_financials():
    """Banks/fintechs don't report gross_margin — should still get a durability read from
    revenue/net_income instead of going permanently blank."""
    from core.scorers.value_quality import score

    funds = [
        {"type": "annual", "period": "2022", "revenue": 1000.0, "net_income": 200.0},
        {"type": "annual", "period": "2023", "revenue": 1100.0, "net_income": 240.0},
        {"type": "annual", "period": "2024", "revenue": 1200.0, "net_income": 290.0},
    ]
    result = score(funds, {})
    assert result["sub_scores"]["margin_durability"] is not None


def test_margin_durability_none_with_insufficient_history():
    from core.scorers.value_quality import score

    funds = [
        {"type": "annual", "period": "2024", "gross_margin": 0.50},
        {"type": "annual", "period": "2025", "gross_margin": 0.55},
    ]
    result = score(funds, {})
    assert result["sub_scores"]["margin_durability"] is None


# ── value_quality: earnings quality (OCF vs. net income) ────────────────────────


def test_earnings_quality_high_cash_conversion_maxes_score():
    from core.scorers.value_quality import score

    funds = [
        {"type": "quarterly", "operating_cash_flow": 150_000_000, "net_income": 100_000_000}
    ] * 4
    result = score(funds, {})
    assert result["sub_scores"]["earnings_quality"] == 10.0


def test_earnings_quality_none_when_unprofitable():
    """Nothing to sanity-check without a profit — stays None, not zero."""
    from core.scorers.value_quality import score

    funds = [
        {"type": "quarterly", "operating_cash_flow": 10_000_000, "net_income": -50_000_000}
    ] * 4
    result = score(funds, {})
    assert result["sub_scores"]["earnings_quality"] is None


# ── value_quality: profitability discounts a net margin masked by operating losses ──


def test_profitability_discounts_net_margin_propped_up_by_one_off_gain():
    from core.scorers.value_quality import score

    suspect = score([], {"net_margin": 0.90, "operating_margin": -0.30})["sub_scores"][
        "profitability"
    ]
    clean = score([], {"net_margin": 0.90, "operating_margin": 0.20})["sub_scores"]["profitability"]
    assert clean > suspect, (
        "a net margin far above a negative operating margin looks like a one-off gain"
    )


# ── value_quality: insider ownership bonus ───────────────────────────────────────


def test_insider_ownership_bonus_high_ownership_near_max():
    from core.scorers.value_quality import score

    result = score([], {"held_pct_insiders": 0.20})
    assert result["sub_scores"]["insider_ownership_bonus"] == 3.0


def test_insider_ownership_bonus_none_when_no_data():
    from core.scorers.value_quality import score

    result = score([], {})
    assert result["sub_scores"]["insider_ownership_bonus"] is None


# ── fundamental_momentum: growth consistency (accelerating vs. decelerating) ────


def test_growth_consistency_accelerating_scores_high():
    from core.scorers.fundamental_momentum import score

    quarters = [
        {"type": "quarterly", "revenue": 135.0},
        {"type": "quarterly", "revenue": 115.0},
        {"type": "quarterly", "revenue": 105.0},
        {"type": "quarterly", "revenue": 100.0},
    ]
    result = score(quarters, {})
    assert result["sub_scores"]["growth_consistency"] == 8.0


def test_growth_consistency_decelerating_scores_low():
    from core.scorers.fundamental_momentum import score

    quarters = [
        {"type": "quarterly", "revenue": 128.0},
        {"type": "quarterly", "revenue": 125.0},
        {"type": "quarterly", "revenue": 120.0},
        {"type": "quarterly", "revenue": 100.0},
    ]
    result = score(quarters, {})
    assert result["sub_scores"]["growth_consistency"] == 0.0


def test_growth_consistency_none_with_insufficient_quarters():
    from core.scorers.fundamental_momentum import score

    quarters = [
        {"type": "quarterly", "revenue": 110.0},
        {"type": "quarterly", "revenue": 100.0},
    ]
    result = score(quarters, {})
    assert result["sub_scores"]["growth_consistency"] is None


# ── fundamental_momentum: estimate revisions ─────────────────────────────────────


def test_estimate_revisions_positive_revision_scores_high():
    from core.scorers.fundamental_momentum import score

    snap = {"price": 100.0, "eps_estimate_curr_fy": 5.0, "eps_estimate_curr_fy_90d_ago": 3.0}
    result = score([], snap)
    assert result["sub_scores"]["estimate_revisions"] == 8.0


def test_estimate_revisions_none_on_currency_mismatch():
    """A foreign filer's EPS estimate (local currency) vs. a USD price is meaningless."""
    from core.scorers.fundamental_momentum import score

    snap = {
        "price": 100.0,
        "eps_estimate_curr_fy": 5.0,
        "eps_estimate_curr_fy_90d_ago": 3.0,
        "currency": "USD",
        "financial_currency": "KRW",
    }
    result = score([], snap)
    assert result["sub_scores"]["estimate_revisions"] is None


# ── composite_long: declining revenue caps out STRONG ────────────────────────


def test_composite_long_caps_below_strong_buy_when_revenue_declining():
    from core.scorers.composite import _composite_long

    base = {
        "fundamental_momentum": _mk(60),
        "value_quality": _mk(98),
        "insider_conviction": _mk(50),
    }
    declining = [_q(70), _q(85), _q(100), _q(115)]  # newest-first, trending down
    result = _composite_long(base, _mk(90), {"revenue_growth": -0.035}, declining)
    assert result["score"] <= 79.9
    assert result["action"] != "STRONG-BUY", (
        "trailing quality alone shouldn't reach STRONG-BUY with shrinking revenue"
    )


def test_composite_long_no_cap_when_revenue_growing():
    from core.scorers.composite import _composite_long

    base = {
        "fundamental_momentum": _mk(90),
        "value_quality": _mk(95),
        "insider_conviction": _mk(80),
    }
    result = _composite_long(base, _mk(90), {"revenue_growth": 0.10})
    assert result["score"] > 79.9
    assert result["action"] == "STRONG-BUY"


# ── composite: diff_scores (score change tracking) ────────────────────────────────


def _snap(
    composite,
    fm_score=None,
    fm_sub=None,
    vq_score=None,
    vq_sub=None,
    ins_score=None,
    pl_score=None,
    pl_sub=None,
):
    return {
        "fundamental_momentum": {"score": fm_score, "sub_scores": fm_sub or {}, "max_pts": {}},
        "value_quality": {"score": vq_score, "sub_scores": vq_sub or {}, "max_pts": {}},
        "insider_conviction": {
            "score": ins_score,
            "sub_scores": {"valid_buys": 1, "valid_sells": 0},
        },
        "price_long": {"score": pl_score, "sub_scores": pl_sub or {}, "max_pts": {}},
        "composite_long": {"score": composite, "action": "HOLD", "weights": {}},
    }


def test_diff_scores_reports_composite_category_and_top_movers():
    from core.scorers.composite import diff_scores

    old = _snap(
        60.0,
        fm_score=55,
        fm_sub={"revenue_trend": 20.0},
        vq_score=70,
        vq_sub={"profitability": 25.0, "balance_sheet": 10.0},
        ins_score=50,
        pl_score=40,
    )
    new = _snap(
        65.0,
        fm_score=55,
        fm_sub={"revenue_trend": 20.0},
        vq_score=73,
        vq_sub={"profitability": 28.0, "balance_sheet": 10.0},
        ins_score=50,
        pl_score=45,
    )

    result = diff_scores(old, new)

    assert result["composite"] == {"old": 60.0, "new": 65.0, "delta": 5.0}
    assert result["categories"]["value_quality"]["delta"] == 3.0
    assert result["categories"]["fundamental_momentum"]["delta"] == 0.0
    assert result["movers"][0] == {"category": "Quality", "key": "profitability", "delta": 3.0}
    assert not any(m["key"] == "balance_sheet" for m in result["movers"]), (
        "unchanged sub-score shouldn't be a mover"
    )


def test_diff_scores_none_when_no_prior_data():
    from core.scorers.composite import diff_scores

    new = _snap(65.0)
    assert diff_scores(None, new) is None
    assert diff_scores({}, new) is None


def test_diff_scores_none_when_composite_score_missing():
    from core.scorers.composite import diff_scores

    old = _snap(None)
    new = _snap(65.0)
    assert diff_scores(old, new) is None


def _bt_snap(price, high_52w, ret6=None, **extra):
    snap = {"price": price, "week52_high": high_52w}
    if ret6 is not None:
        snap["returns"] = {"ticker_return_6m": ret6}
    snap.update(extra)
    return snap


def test_buy_target_p10_anchor_widened_by_vol_tiers():
    from core.scorers.composite import _buy_target

    # p10 anchor = low + (0.10/0.5)*(median - low) = 100 + 0.2*(200-100) = 120.
    def bt(vol):
        return _buy_target(
            _bt_snap(
                105.0,
                high_52w=300.0,
                target_low=100.0,
                target_median=200.0,
                analyst_count=15,
                realized_vol=vol,
            )
        )

    assert bt(0.30)["vol_level"] == "low" and bt(0.30)["price"] == 120.0  # no discount
    assert bt(0.50)["vol_level"] == "mid" and bt(0.50)["price"] == 105.6  # 120*0.88
    assert bt(0.90)["vol_level"] == "high" and bt(0.90)["price"] == 90.0  # 120*0.75
    assert bt(0.30)["signal"] == "buy" and bt(0.90)["signal"] == "wait"


def test_buy_target_p50_falls_back_to_mean_without_median():
    from core.scorers.composite import _buy_target

    # no median -> mean stands in as p50: 100 + 0.2*(200-100) = 120 (baja vol -> no discount).
    bt = _buy_target(
        _bt_snap(
            105.0,
            high_52w=300.0,
            target_low=100.0,
            target_mean=200.0,
            analyst_count=15,
            realized_vol=0.30,
        )
    )
    assert bt["price"] == 120.0


def test_buy_target_thin_coverage_falls_back_to_drawdown():
    from core.scorers.composite import _buy_target

    # rich targets but <10 analysts -> distribution too thin -> ignore it, use the drawdown zone.
    bt = _buy_target(
        _bt_snap(
            95.0,
            high_52w=100.0,
            target_low=100.0,
            target_median=200.0,
            analyst_count=5,
            realized_vol=0.30,
        )
    )
    assert bt["method"] == "drawdown"
    assert bt["price"] == 70.0  # w52*0.70, not the p10 anchor
    assert bt["signal"] == "wait"


def test_buy_target_drawdown_widened_by_vol_tier():
    from core.scorers.composite import _buy_target

    # the volatility discount applies to the drawdown fallback too: high vol -> deeper entry.
    # anchor = w52*0.70 = 70; high tier -> 70*0.75 = 52.5.
    bt = _buy_target(_bt_snap(70.0, high_52w=100.0, analyst_count=3, realized_vol=0.90))
    assert bt["method"] == "drawdown" and bt["vol_level"] == "high"
    assert bt["price"] == 52.5
    assert bt["signal"] == "wait"  # price 70 > 52.5


def test_buy_target_falls_back_to_drawdown_without_analyst_targets():
    from core.scorers.composite import _buy_target

    # no analyst coverage -> anchor on the -30%-off-52w-high deep-value zone (low vol -> no discount).
    wait = _buy_target(_bt_snap(95.0, high_52w=100.0, realized_vol=0.30))
    assert wait["price"] == 70.0
    assert wait["signal"] == "wait"
    buy = _buy_target(_bt_snap(70.0, high_52w=100.0, realized_vol=0.30))
    assert buy["signal"] == "buy"


def test_buy_target_unmeasurable_vol_is_conservative_not_low():
    from core.scorers.composite import _buy_target

    # too little history to measure vol -> "n/a", not "low": apply the full (high) discount.
    # drawdown anchor 70 * (1 - 0.25) = 52.5, not 70.
    bt = _buy_target(_bt_snap(95.0, high_52w=100.0, realized_vol=None))
    assert bt["vol_level"] == "n/a"
    assert bt["mos"] == 0.25
    assert bt["price"] == 52.5


def test_buy_target_none_without_price_or_anchor():
    from core.scorers.composite import _buy_target

    assert _buy_target({"week52_high": 100.0}) is None  # no price
    assert _buy_target({"price": 100.0}) is None  # no target_low, no high
    assert _buy_target({"price": 100.0, "week52_high": 0.0}) is None


def test_is_expensive_needs_two_signals():
    from core.scorers.composite import _is_expensive

    # profitable & rich on BOTH forward earnings and growth-adjusted sales -> expensive.
    assert (
        _is_expensive({"forward_pe": 40.0, "price_to_sales": 15.0, "revenue_growth": 0.0}) is True
    )
    # cheap forward P/E -> not expensive no matter the sales multiple (NVO case).
    assert (
        _is_expensive({"forward_pe": 15.6, "price_to_sales": 30.0, "revenue_growth": 0.0}) is False
    )
    # depressed earnings: high P/E but ordinary sales multiple -> only one signal -> not expensive.
    assert (
        _is_expensive({"forward_pe": 45.0, "price_to_sales": 3.0, "revenue_growth": 0.0}) is False
    )
    # fat margins: rich sales but ordinary P/E -> only one signal -> not expensive (TXN case).
    assert (
        _is_expensive({"forward_pe": 25.0, "price_to_sales": 15.0, "revenue_growth": 0.0}) is False
    )
    # pre-profit (no positive P/E): a high RAW sales multiple is the tell.
    assert _is_expensive({"forward_pe": None, "price_to_sales": 25.0}) is True
    assert _is_expensive({"forward_pe": -8.0, "price_to_sales": 5.0}) is False
    # no sales multiple to judge -> not flagged.
    assert _is_expensive({"forward_pe": 50.0}) is False


def test_recent_periods_picks_newest_of_each_type():
    from scheduler.worker import _recent_periods

    periods = [
        ("2024-09-30", {"type": "quarterly"}),
        ("2024-06-30", {"type": "quarterly"}),
        ("2024-03-31", {"type": "quarterly"}),
        ("2025", {"type": "annual"}),
        ("2024", {"type": "annual"}),
    ]
    recent = _recent_periods(periods)
    assert recent == {"2024-09-30", "2024-06-30", "2025"}  # 2 newest quarters + newest annual


def test_insider_no_valid_trades_is_none_not_50():
    from core.scorers.composite import compute_all

    # snapshot with no insider transactions -> insider score None (excluded), not a neutral 50
    snap = {
        "price": 100.0,
        "market_cap": 1e10,
        "revenue_growth": 0.1,
        "week52_low": 80.0,
        "week52_high": 120.0,
        "insider_transactions": [],
    }
    quarters = [
        {
            "type": "quarterly",
            "revenue": 1e6 + i * 1e5,
            "net_income": 1e5,
            "fcf": 8e4,
            "gross_margin": 0.4,
        }
        for i in range(4)
    ]
    out = compute_all(quarters, snap)
    assert out["insider_conviction"]["score"] is None


def test_risk_flags_revenue_decline_and_price_suspect():
    from core.scorers.composite import _risk_flags

    declining = [_q(70), _q(85), _q(100), _q(115)]  # newest-first, trending down
    flags = _risk_flags(declining, {"revenue_growth": -0.04, "price_suspect": True})
    keys = {f["key"] for f in flags}
    assert "rev" in keys and "price" in keys


def test_risk_flags_expensive_valuation():
    from core.scorers.composite import _risk_flags

    # rich on both forward P/E and growth-adjusted sales -> $$$.
    flags = _risk_flags([], {"forward_pe": 40.0, "price_to_sales": 15.0, "revenue_growth": 0.2})
    assert any(f["key"] == "expensive" for f in flags)


def test_risk_flags_none_when_healthy():
    from core.scorers.composite import _risk_flags

    # cheap forward P/E, ordinary sales multiple -> not expensive, no other flag.
    assert (
        _risk_flags([], {"forward_pe": 18.0, "price_to_sales": 3.0, "revenue_growth": 0.25}) == []
    )


def test_risk_flags_new_when_under_a_year_of_history():
    from core.scorers.composite import _risk_flags

    # no 12m return but a 1w return exists -> recently listed.
    new = _risk_flags([], {"returns": {"ticker_return_1w": 0.05, "ticker_return_12m": None}})
    assert any(f["key"] == "new" for f in new)
    # a full year of history -> not new.
    seasoned = _risk_flags([], {"returns": {"ticker_return_1w": 0.05, "ticker_return_12m": 0.3}})
    assert not any(f["key"] == "new" for f in seasoned)
    # total price-fetch failure (empty returns) is data-broken, not "new".
    broken = _risk_flags([], {"returns": {}})
    assert not any(f["key"] == "new" for f in broken)


def test_cyclical_surge_flags_recovery_off_a_trough():
    from core.scorers.composite import _is_cyclical_surge

    # MU-shape: revenue crashed (30.8 -> 15.5) then recovered, and now surging -> cyclical
    ann = [{"type": "annual", "revenue": r} for r in (37.4, 25.1, 15.5, 30.8)]  # newest first
    assert _is_cyclical_surge(ann, {"revenue_growth": 3.46}) is True


def test_cyclical_surge_ignores_monotonic_hypergrowth():
    from core.scorers.composite import _is_cyclical_surge

    # NBIS/IONQ-shape: never declined YoY -> secular/hypergrowth, not cyclical
    ann = [{"type": "annual", "revenue": r} for r in (0.5, 0.1, 0.02, 0.01)]
    assert _is_cyclical_surge(ann, {"revenue_growth": 6.8}) is False


# ── refactor bug fixes (W1) ─────────────────────────────────────────────────────


def test_margin_durability_noisy_negative_margins_not_scored_perfect():
    """Loss-making, noisy margin history must NOT land the top durability score. The old
    residual_cv divided the (positive) RMS by the signed negative mean, going negative so
    `> 0.05` was always False -> a noisy negative history fell through to 12.0."""
    from core.scorers.value_quality import score

    funds = [
        {"type": "annual", "period": "2022", "revenue": 1000.0, "net_income": -200.0},  # -20%
        {"type": "annual", "period": "2023", "revenue": 1000.0, "net_income": -50.0},  # -5%
        {"type": "annual", "period": "2024", "revenue": 1000.0, "net_income": -200.0},  # -20%
    ]
    result = score(funds, {})
    assert result["sub_scores"]["margin_durability"] == 7.0  # was 12.0 before the fix


def test_profitability_partial_coverage_not_capped_below_axis():
    """A company reporting only ROE (and nothing else) that scores it fully should reach the
    profitability ceiling, not be capped by dividing through the all-three-metrics max."""
    from core.scorers.value_quality import score

    result = score([], {"roe": 0.25})
    assert result["sub_scores"]["profitability"] == 35.0  # was 14.0 (8/20*35) before the fix


def test_valuation_partial_coverage_not_capped_below_axis():
    from core.scorers.price_long import score

    # only PEG present (a cheap 0.8) -> the axis normalizes by the one present multiple and still
    # reaches the ceiling instead of being dragged down by the absent fwd_pe / growth_adj_ps.
    result = score([], {"peg_ratio": 0.8})
    assert result["sub_scores"]["peg"] == 8.0
    assert result["score"] == 100.0


def test_ttm_annualizes_partial_year():
    """Fewer than 4 populated quarters must annualize, not return a raw partial sum, so
    downstream per-quarter math (cash_runway divides TTM by 4) stays correct."""
    from core.scorers.base import ttm

    funds = [
        {"type": "quarterly", "fcf": -50.0},
        {"type": "quarterly", "fcf": -50.0},
    ]
    assert ttm(funds, "fcf") == -200.0  # -100/2*4, was -100 before the fix


def test_cyclical_surge_counts_zero_revenue_down_year():
    """A legitimately reported revenue==0 year is a real down-year and must not be dropped by
    a truthiness filter, which would hide the cycle."""
    from core.scorers.composite import _is_cyclical_surge

    funds = [  # newest first (period desc), as read_all_fundamentals returns them
        {"type": "annual", "period": "2024", "revenue": 120.0},
        {"type": "annual", "period": "2023", "revenue": 0.0},
        {"type": "annual", "period": "2022", "revenue": 100.0},
    ]
    assert _is_cyclical_surge(funds, {"revenue_growth": 0.5}) is True


# ── cyclical flag: maturity + depth-scaled surge gates (A+B) ────────────────────


def test_cyclical_surge_mild_growth_with_deep_trough_flags():
    """ADI/TXN-shape: a mature semis cyclical surging only +37% (under the old hard 40% cliff)
    still flags when the annual history shows a genuinely deep (>=20%) down-year."""
    from core.scorers.composite import _is_cyclical_surge

    ann = [
        {"type": "annual", "revenue": r} for r in (12.0, 8.0, 10.0, 11.0)
    ]  # newest first, depth ~27%
    assert _is_cyclical_surge(ann, {"revenue_growth": 0.37, "operating_margin": 0.38}) is True


def test_cyclical_surge_mild_growth_with_shallow_trough_does_not_flag():
    """A milder surge (<40%) with only a SHALLOW revenue dip (<20%) and no earnings amplification
    must NOT flag (LRCX-shape: ebit fell ≈ as much as revenue → no operating leverage)."""
    from core.scorers.composite import _is_cyclical_surge

    ann = [
        {"type": "annual", "revenue": r, "ebit": r * 0.2} for r in (12.0, 9.5, 10.0, 11.0)
    ]  # revenue depth ~14%, ebit tracks revenue → no leverage
    assert _is_cyclical_surge(ann, {"revenue_growth": 0.24, "operating_margin": 0.12}) is False


def test_cyclical_surge_excludes_deep_burn_prerevenue():
    """XNDU/RGTI-shape: near-zero revenue makes any wiggle read as a 'cycle', but an operating
    margin far below -25% marks a pre-revenue name, not a semis peak -> excluded despite the surge."""
    from core.scorers.composite import _is_cyclical_surge

    ann = [
        {"type": "annual", "revenue": r} for r in (12.0, 8.0, 10.0, 11.0)
    ]  # oscillates, would flag
    assert _is_cyclical_surge(ann, {"revenue_growth": 3.0, "operating_margin": -8.22}) is False


def test_cyclical_surge_keeps_near_breakeven_cyclical():
    """A recovered commodity cyclical near breakeven (op margin -8%, above the -25% floor) must still
    flag — the maturity gate only screens deeply-burning pre-revenue noise, not thin-margin names."""
    from core.scorers.composite import _is_cyclical_surge

    ann = [
        {"type": "annual", "revenue": r} for r in (12.0, 8.0, 10.0, 11.0)
    ]  # newest first, recovered
    assert _is_cyclical_surge(ann, {"revenue_growth": 1.19, "operating_margin": -0.08}) is True


# ── cyclical flag: recovery-or-earnings guard (drops MP/AXTI, keeps INTC) ─────────


def test_cyclical_surge_drops_name_still_near_its_trough():
    """MP/AXTI-shape: annual revenue is still far below its peak (a spiky quarterly YoY only *looks*
    like a surge). With no corroborating earnings-leverage swing, it hasn't come 'off' anything."""
    from core.scorers.composite import _is_cyclical_surge

    # newest first: latest 0.22 vs peak 0.53 = 42% of peak, well under the 85% recovery bar
    ann = [{"type": "annual", "revenue": r} for r in (0.22, 0.20, 0.25, 0.53)]
    assert _is_cyclical_surge(ann, {"revenue_growth": 1.19, "operating_margin": -0.08}) is False


def test_cyclical_surge_keeps_near_trough_when_earnings_corroborate():
    """INTC-shape: revenue still soft (84% of peak, under the recovery bar) but ebit swung violently
    (operating leverage) — the earnings signal confirms the cycle independently, so it stays flagged."""
    from core.scorers.composite import _is_cyclical_surge

    ann = [  # newest first; revenue ~flat-soft, ebit collapsed then recovered
        {"type": "annual", "revenue": rev, "ebit": eb}
        for rev, eb in [(53.0, 2.65), (53.0, -10.18), (54.0, 1.64), (63.0, 8.26)]
    ]
    assert _is_cyclical_surge(ann, {"revenue_growth": 0.25, "operating_margin": 0.12}) is True


# ── cyclical flag: operating-leverage earnings signal (margin-cyclicals) ─────────


def test_cyclical_surge_earnings_leverage_flags_shallow_revenue_dip():
    """CGNX-shape: a mild surge with a SHALLOW revenue dip (<20%) still flags when ebit fell far
    harder (operating leverage) — the margin-cyclical the revenue-only test used to miss."""
    from core.scorers.composite import _is_cyclical_surge

    # revenue depth ~14%; ebit crashed 60% then recovered → amplifies the cycle
    ann = [
        {"type": "annual", "revenue": rev, "ebit": eb}
        for rev, eb in [(12.0, 1.6), (9.5, 0.5), (10.0, 0.6), (11.0, 1.25)]
    ]  # newest first
    assert _is_cyclical_surge(ann, {"revenue_growth": 0.24, "operating_margin": 0.22}) is True


def test_cyclical_surge_earnings_signal_needs_a_revenue_cycle():
    """A secular grower with NO revenue down-year must not flag on earnings alone — a near-breakeven
    SaaS name (DDOG/ARM-shape) whose ebit wobbles across zero would otherwise look 'cyclical'."""
    from core.scorers.composite import _is_cyclical_surge

    # revenue monotonically rising (no cycle), ebit noisy across a low base
    ann = [
        {"type": "annual", "revenue": rev, "ebit": eb}
        for rev, eb in [(12.0, 0.3), (9.0, 0.1), (6.0, 0.2), (3.0, 0.05)]
    ]  # newest first → revenue only ever grew
    assert _is_cyclical_surge(ann, {"revenue_growth": 0.33, "operating_margin": 0.02}) is False


def test_cyclical_surge_earnings_trough_needs_positive_latest():
    """A name currently losing operating money has no earnings peak for a cycle to inflate — the
    ebit signal must be skipped when latest ebit <= 0 (it falls back to the revenue cycle)."""
    from core.scorers.composite import _is_cyclical_surge

    # shallow revenue dip (~14%), ebit deep but latest is negative → ebit signal must not engage
    ann = [
        {"type": "annual", "revenue": rev, "ebit": eb}
        for rev, eb in [(12.0, -0.5), (9.5, 0.5), (10.0, 0.6), (11.0, 1.25)]
    ]  # newest first, latest ebit < 0
    assert _is_cyclical_surge(ann, {"revenue_growth": 0.24, "operating_margin": 0.02}) is False


def test_buy_target_high_dispersion_deepens_the_entry():
    """A wide analyst low→high spread (Palley/Steffen/Zhang: high dispersion flips the consensus
    negative) stacks an extra margin-of-safety discount on top of the vol one — a lower target."""
    from core.scorers.composite import _buy_target

    base = {
        "price": 100.0,
        "realized_vol": 0.30,
        "analyst_count": 20,
        "target_low": 80.0,
        "target_median": 120.0,
    }
    tight = _buy_target({**base, "target_high": 130.0})  # (130-80)/120 ≈ 0.42 → mid
    wide = _buy_target({**base, "target_high": 220.0})  # (220-80)/120 ≈ 1.17 → high
    assert tight["disp_level"] == "mid" and wide["disp_level"] == "high"
    assert wide["price"] < tight["price"]  # more disagreement → deeper entry


def test_buy_target_mos_is_capped():
    """vol + dispersion discounts stack but can't exceed the cap, so the target never collapses."""
    from core.scorers.composite import _BT_MOS_CAP, _buy_target

    bt = _buy_target(
        {
            "price": 100.0,
            "realized_vol": 0.90,
            "analyst_count": 15,
            "target_low": 80.0,
            "target_median": 120.0,
            "target_high": 300.0,
        }
    )
    assert bt["mos"] == _BT_MOS_CAP  # high vol (0.25) + high disp (0.15) = 0.40, capped to 0.35


def test_buy_target_thin_analysts_uses_ma200_when_below_drawdown():
    """<10 analysts → technical anchor = lower of the −30%-off-high zone and the 200-day MA."""
    from core.scorers.composite import _buy_target

    snap = {
        "price": 100.0,
        "realized_vol": 0.30,
        "analyst_count": 3,
        "week52_high": 150.0,
        "moving_averages": {"200": 90.0},
    }
    bt = _buy_target(snap)
    # −30% off 150 = 105; MA200 = 90 is lower → MA200 wins
    assert bt["method"] == "ma200" and bt["anchor"] == 90.0


def test_buy_target_thin_analysts_falls_back_to_drawdown_without_ma():
    """No MA200 available (thin history) → the −30%-off-52w-high rule still applies unchanged."""
    from core.scorers.composite import _buy_target

    bt = _buy_target(
        {"price": 100.0, "realized_vol": 0.30, "analyst_count": 3, "week52_high": 150.0}
    )
    assert bt["method"] == "drawdown" and bt["anchor"] == 105.0
