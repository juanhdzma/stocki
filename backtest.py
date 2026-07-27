"""Time-machine backtest: run TODAY's scoring formulas on the data as it stood on a past date.

Reconstructs each watchlist ticker's inputs as of `--date` (default: one month ago) and runs the
current compute_all(), then values the resulting portfolio at `--value-date` (default: latest).

Point-in-time reconstruction (no look-ahead):
  - Price path (from the daily series ending at D): price, week52_high/low, all returns,
    day_change_pct, typical_pullback_pct, market_cap, beta (vs SPY over the trailing year).
  - Fundamentals derived from the financial statements filtered to what was reported by D
    (_period_available drops post-D quarters): net/operating margin, ROE, ROA, revenue_growth,
    current_ratio, debt_to_equity, dilution_rate, trailing_pe, price_to_sales, ev_to_revenue,
    plus everything the scorers read straight off the statements (fcf, cash, ebit, ...).
  - Analyst ratings + price targets via upgrades_downgrades backtracing: each firm's most recent
    change on/before D is its active rating+target then; stale firms (no change in the trailing
    year) drop out. Reconstructs rec_* counts, target_mean, analyst_count.
  - Insiders: transactions filtered to filing_date <= D (what was public at D), and
    compute_all(as_of=D) anchors the time-decay + 365d window at D instead of today.

Still not reconstructable from yfinance (set to None -> excluded from the score, not leaked):
  forward_pe / peg_ratio / eps estimate revisions (forward estimates have no dated history),
  earnings_beat_rate, held_pct_insiders/institutions, short interest. Also: the openinsider scrape
  window is relative to today, so for D far in the past the older half of [D-365, D] is missing —
  fidelity of the insider axis degrades with lookback (fine at 1m, weak by 6m).

Run (DB is only reachable from inside the app container):
  docker compose cp backtest.py stocki:/app/backtest.py && docker compose exec stocki python3 /app/backtest.py
"""

from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta
from sqlalchemy import select

from core.fetchers.yahoo import batch_download_history, fetch_grade_history, init_auth
from core.scorers.base import all_annual, latest_quarters, ttm
from core.scorers.composite import compute_all
from db.cache import AsyncSessionLocal, read_all_fundamentals, read_snapshot
from db.models import Watchlist

# invest sizing: (composite action, buy_target label) -> dollars. 6:3:1 conviction units, 1 unit = $100.
# BUY+CASI dropped (the lowest-conviction quadrant, consistently the worst performer).
SIZING = {
    ("STRONG-BUY", "COMPRAR"): 600,
    ("STRONG-BUY", "CASI"): 300,
    ("BUY", "COMPRAR"): 100,
}

_RETURN_DAYS = {"1w": 5, "1m": 21, "3m": 63, "6m": 126, "12m": 252}

# yfinance .info fields with no dated history — excluded (None) rather than leaked from the present.
_UNRECOVERABLE = (
    "forward_pe",
    "peg_ratio",
    "eps_estimate_curr_fy",
    "eps_estimate_curr_fy_90d_ago",
    "earnings_beat_rate",
    "held_pct_insiders",
    "held_pct_institutions",
    "short_percent_of_float",
    "short_ratio",
)

# ToGrade string -> recommendation bucket (Yahoo's rec_* buckets)
_GRADE_BUCKET = {
    "strong buy": "rec_strong_buy",
    "buy": "rec_buy",
    "outperform": "rec_buy",
    "overweight": "rec_buy",
    "positive": "rec_buy",
    "accumulate": "rec_buy",
    "add": "rec_buy",
    "sector outperform": "rec_buy",
    "conviction buy": "rec_buy",
    "long-term buy": "rec_buy",
    "hold": "rec_hold",
    "neutral": "rec_hold",
    "market perform": "rec_hold",
    "sector perform": "rec_hold",
    "equal-weight": "rec_hold",
    "equalweight": "rec_hold",
    "peer perform": "rec_hold",
    "perform": "rec_hold",
    "sector weight": "rec_hold",
    "in-line": "rec_hold",
    "underperform": "rec_sell",
    "underweight": "rec_sell",
    "reduce": "rec_sell",
    "negative": "rec_sell",
    "sector underperform": "rec_sell",
    "sell": "rec_strong_sell",
    "strong sell": "rec_strong_sell",
}


def _asof_pos(index: pd.DatetimeIndex, d: date) -> int | None:
    pos = index.searchsorted(pd.Timestamp(d), side="right") - 1
    return int(pos) if pos >= 0 else None


def _returns_asof(closes: pd.Series, i: int) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for label, days in _RETURN_DAYS.items():
        out[label] = (
            float((closes.iloc[i] - closes.iloc[i - days]) / closes.iloc[i - days])
            if i - days >= 0
            else None
        )
    return out


def _typical_pullback(closes: pd.Series) -> float | None:
    s = closes.tail(504)
    if len(s) < 60:
        return None
    drawdown = s / s.cummax() - 1.0
    troughs, cur_min, active = [], 0.0, False
    for v in drawdown:
        if v <= -0.05:
            active, cur_min = True, min(cur_min, v)
        elif active:
            troughs.append(cur_min)
            active, cur_min = False, 0.0
    if active:
        troughs.append(cur_min)
    return abs(float(np.median(troughs))) if troughs else None


def _beta(closes: pd.Series, spy: pd.Series, d: date) -> float | None:
    df = pd.concat([closes.rename("t"), spy.rename("s")], axis=1, sort=True).dropna()
    df = df[df.index <= pd.Timestamp(d)].tail(252)
    if len(df) < 60:
        return None
    r = df.pct_change().dropna()
    var = float(r["s"].var())
    return float(r["t"].cov(r["s"]) / var) if var else None


def _period_available(period: str, d: date) -> bool:
    """Approx: was this fundamentals period already reported by date D? (period-end + filing lag)"""
    try:
        if "Q" in period:
            y, q = period.split("-Q")
            end = date(int(y), {1: 3, 2: 6, 3: 9, 4: 12}[int(q)], 28)
            lag = 50
        else:
            end = date(int(period), 12, 31)
            lag = 80
        return end + timedelta(days=lag) <= d
    except (ValueError, KeyError):
        return True


def _ratio(a: float | None, b: float | None) -> float | None:
    return a / b if (a is not None and b) else None


def _latest_val(funds: list[dict], field: str) -> float | None:
    """Newest non-null value of a statement field, preferring quarterly over annual."""
    for kind in ("quarterly", "annual"):
        for f in funds:
            if f.get("type") == kind and f.get(field) is not None:
                return f[field]
    return None


def _apply_pit_fundamentals(
    snap: dict, funds: list[dict], price_d: float, mcap_d: float | None
) -> None:
    """Recompute the .info aggregates from the point-in-time statements + date-D price."""
    ttm_rev = ttm(funds, "revenue")
    ttm_ni = ttm(funds, "net_income")
    ttm_ebit = ttm(funds, "ebit")

    snap["net_margin"] = _ratio(ttm_ni, ttm_rev)
    snap["operating_margin"] = _ratio(ttm_ebit, ttm_rev)
    snap["roe"] = _ratio(ttm_ni, _latest_val(funds, "total_equity"))
    snap["roa"] = _ratio(ttm_ni, _latest_val(funds, "total_assets"))
    snap["current_ratio"] = _ratio(
        _latest_val(funds, "current_assets"), _latest_val(funds, "current_liabilities")
    )
    d2e = _ratio(_latest_val(funds, "total_debt"), _latest_val(funds, "total_equity"))
    snap["debt_to_equity"] = d2e * 100 if d2e is not None else None  # yfinance D/E is a percent

    # revenue_growth: quarterly YoY (matches yfinance's revenueGrowth) if >=5 quarters, else annual YoY
    qrev = [q.get("revenue") for q in latest_quarters(funds, 8)]
    annuals = all_annual(funds)
    if len(qrev) >= 5 and qrev[0] is not None and qrev[4]:
        snap["revenue_growth"] = qrev[0] / qrev[4] - 1
    elif len(annuals) >= 2 and annuals[0].get("revenue") is not None and annuals[1].get("revenue"):
        snap["revenue_growth"] = annuals[0]["revenue"] / annuals[1]["revenue"] - 1
    else:
        snap["revenue_growth"] = None

    if len(annuals) >= 2:
        s0, s1 = annuals[0].get("shares_outstanding"), annuals[1].get("shares_outstanding")
        snap["dilution_rate"] = (s0 - s1) / s1 if (s0 is not None and s1) else None
    else:
        snap["dilution_rate"] = None

    eps_ttm = _ratio(ttm_ni, _latest_val(funds, "shares_outstanding"))
    snap["trailing_pe"] = price_d / eps_ttm if (eps_ttm and eps_ttm > 0) else None
    snap["price_to_sales"] = _ratio(mcap_d, ttm_rev)
    if mcap_d is not None:
        ev = mcap_d + (_latest_val(funds, "total_debt") or 0) - (_latest_val(funds, "cash") or 0)
        snap["ev_to_revenue"] = _ratio(ev, ttm_rev)
    else:
        snap["ev_to_revenue"] = None


def _analyst_asof(history: list[dict], d: date, window_days: int = 365) -> dict:
    """Reconstruct rec_* counts, target_mean, analyst_count from dated rating changes: each firm's
    latest change on/before D is its active rating+target; firms with no change in the trailing
    window are treated as having dropped coverage."""
    di = d.isoformat()
    lo = (d - timedelta(days=window_days)).isoformat()
    latest_by_firm: dict[str, dict] = {}
    for h in history:
        if h["firm"] and h["date"] <= di:
            cur = latest_by_firm.get(h["firm"])
            if cur is None or h["date"] > cur["date"]:
                latest_by_firm[h["firm"]] = h

    counts = dict.fromkeys(
        ("rec_strong_buy", "rec_buy", "rec_hold", "rec_sell", "rec_strong_sell"), 0
    )
    targets: list[float] = []
    active = 0
    for h in latest_by_firm.values():
        if h["date"] < lo:
            continue
        bucket = _GRADE_BUCKET.get(h["to_grade"].lower())
        if bucket is None:
            continue
        counts[bucket] += 1
        active += 1
        if h.get("target"):
            targets.append(h["target"])

    if active == 0:
        return {**dict.fromkeys(counts), "target_mean": None, "analyst_count": None}
    return {
        **counts,
        "target_mean": round(sum(targets) / len(targets), 2) if targets else None,
        "analyst_count": float(active),
    }


def reconstruct_snapshot(
    snap_now: dict,
    closes: pd.Series,
    spy: pd.Series,
    d: date,
    funds: list[dict],
    grade_hist: list[dict],
) -> dict | None:
    i = _asof_pos(closes.index, d)
    if i is None:
        return None
    price_d = float(closes.iloc[i])
    price_now = snap_now.get("price") or float(closes.iloc[-1])
    if not price_now or price_d <= 0:
        return None
    ratio = price_d / price_now
    mcap_d = snap_now["market_cap"] * ratio if snap_now.get("market_cap") else None

    window = closes.iloc[max(0, i - 251) : i + 1]
    w52h, w52l = float(window.max()), float(window.min())
    win5 = closes.iloc[max(0, i - 4) : i + 1]
    h1w = float(win5.max())
    prev = float(closes.iloc[i - 1]) if i >= 1 else price_d

    snap = dict(snap_now)
    snap["price"] = price_d
    snap["market_cap"] = mcap_d
    snap["week52_high"] = w52h
    snap["week52_low"] = w52l
    snap["pct_from_52w_high"] = (price_d - w52h) / w52h if w52h else None
    snap["pct_from_1w_high"] = (price_d - h1w) / h1w if h1w else None
    snap["day_change_pct"] = (price_d / prev - 1) * 100 if prev else None
    snap["typical_pullback_pct"] = _typical_pullback(closes.iloc[: i + 1])
    snap["beta"] = _beta(closes, spy, d)
    snap["price_suspect"] = False

    tr = _returns_asof(closes, i)
    j = _asof_pos(spy.index, d)
    sr = _returns_asof(spy, j) if j is not None else {}
    snap["returns"] = {
        **{f"ticker_return_{k}": v for k, v in tr.items()},
        **{f"spy_return_{k}": v for k, v in sr.items()},
    }

    _apply_pit_fundamentals(snap, funds, price_d, mcap_d)
    snap.update(_analyst_asof(grade_hist, d))
    for k in _UNRECOVERABLE:
        snap[k] = None

    # Insiders: only what was PUBLIC at D (filing_date), fall back to trade_date if unfiled.
    di = d.isoformat()
    snap["insider_transactions"] = [
        tx
        for tx in snap_now.get("insider_transactions", [])
        if (tx.get("filing_date") or tx.get("trade_date") or "")[:10] <= di
    ]
    return snap


def _bt_label(bt: dict | None) -> str | None:
    if not bt:
        return None
    if bt["signal"] == "buy":
        return "COMPRAR"
    return "CASI" if bt["pct_from_current"] >= -0.04 else "ESPERAR"


def _series(hist: pd.DataFrame, field: str, ticker: str) -> pd.Series | None:
    try:
        col = hist[field]
        s = col[ticker] if ticker in col.columns else None
        return s.dropna() if s is not None else None
    except (KeyError, AttributeError):
        return None


async def run(d: date, value_date: date | None) -> None:
    async with AsyncSessionLocal() as session:
        tickers = [r[0] for r in (await session.execute(select(Watchlist.ticker))).all()]

    print(f"Downloading 2y price history for {len(tickers)} tickers + SPY ...")
    hist = await asyncio.to_thread(batch_download_history, tickers, "2y")
    spy = _series(hist, "Close", "SPY")
    if spy is None:
        raise SystemExit("SPY history unavailable — cannot compute relative returns.")

    print("Fetching analyst rating history (upgrades_downgrades) for backtracing ...")
    await asyncio.to_thread(init_auth)

    def _all_grades() -> dict[str, list[dict]]:
        with ThreadPoolExecutor(max_workers=8) as ex:
            return dict(zip(tickers, ex.map(fetch_grade_history, tickers), strict=True))

    grades = await asyncio.to_thread(_all_grades)
    as_of_dt = datetime(d.year, d.month, d.day)

    picks, skipped = [], []
    async with AsyncSessionLocal() as session:
        for t in tickers:
            closes = _series(hist, "Close", t)
            if closes is None or closes.empty:
                skipped.append((t, "no price history"))
                continue
            snap_now = await read_snapshot(session, t)
            if not snap_now:
                skipped.append((t, "no snapshot"))
                continue
            funds = [
                f
                for f in await read_all_fundamentals(session, t)
                if _period_available(f["period"], d)
            ]
            snap = reconstruct_snapshot(snap_now, closes, spy, d, funds, grades.get(t, []))
            if snap is None:
                skipped.append((t, "no price on/before date"))
                continue
            try:
                scores = compute_all(funds, snap, as_of=as_of_dt)
            except Exception as exc:
                skipped.append((t, f"score error: {exc}"))
                continue

            action = scores["composite_long"]["action"]
            label = _bt_label(scores["buy_target"])
            amount = SIZING.get((action, label), 0)
            if amount == 0:
                continue

            vpos = _asof_pos(closes.index, value_date) if value_date else len(closes) - 1
            price_val = float(closes.iloc[vpos])
            price_d = snap["price"]
            shares = amount / price_d
            picks.append(
                {
                    "ticker": t,
                    "action": action,
                    "label": label,
                    "score": scores["composite_long"]["score"],
                    "price_d": price_d,
                    "price_val": price_val,
                    "amount": amount,
                    "shares": shares,
                    "value": shares * price_val,
                }
            )

    _report(picks, skipped, d, value_date, spy)


def _report(picks, skipped, d, value_date, spy) -> None:
    vlabel = value_date.isoformat() if value_date else "latest (today)"
    print("\n" + "=" * 78)
    print(f"BACKTEST — bought as of {d.isoformat()}, valued at {vlabel}")
    print("=" * 78)

    order = [("STRONG-BUY", "COMPRAR"), ("STRONG-BUY", "CASI"), ("BUY", "COMPRAR"), ("BUY", "CASI")]
    picks.sort(key=lambda p: (order.index((p["action"], p["label"])), -p["score"]))

    hdr = f"{'TICKER':<8}{'ACTION':<12}{'SIGNAL':<9}{'SCORE':>6}{'BUY@':>10}{'NOW@':>10}{'INVEST':>9}{'VALUE':>10}{'P&L':>10}{'P&L%':>8}"
    print("\n" + hdr)
    print("-" * len(hdr))
    inv_tot = val_tot = 0.0
    cur_bucket = None
    for p in picks:
        b = (p["action"], p["label"])
        if b != cur_bucket:
            cur_bucket = b
            print(f"  -- {p['action']} + {p['label']}  (${SIZING[b]}/pos) --")
        pnl = p["value"] - p["amount"]
        pnlp = pnl / p["amount"] * 100
        print(
            f"{p['ticker']:<8}{p['action']:<12}{p['label']:<9}{p['score']:>6.1f}"
            f"{p['price_d']:>10.2f}{p['price_val']:>10.2f}{p['amount']:>9.0f}"
            f"{p['value']:>10.2f}{pnl:>+10.2f}{pnlp:>+7.1f}%"
        )
        inv_tot += p["amount"]
        val_tot += p["value"]

    print("-" * len(hdr))
    if inv_tot:
        pnl = val_tot - inv_tot
        print(
            f"{'TOTAL':<8}{'':<12}{'':<9}{'':>6}{'':>10}{'':>10}"
            f"{inv_tot:>9.0f}{val_tot:>10.2f}{pnl:>+10.2f}{pnl / inv_tot * 100:>+7.1f}%"
        )
        sp_i = _asof_pos(spy.index, d)
        sp_v = _asof_pos(spy.index, value_date) if value_date else len(spy) - 1
        if sp_i is not None:
            spy_ret = float(spy.iloc[sp_v] / spy.iloc[sp_i] - 1)
            print(
                f"{'SPY':<8}{'(same $)':<12}{'':<9}{'':>6}{'':>10}{'':>10}"
                f"{inv_tot:>9.0f}{inv_tot * (1 + spy_ret):>10.2f}"
                f"{inv_tot * spy_ret:>+10.2f}{spy_ret * 100:>+7.1f}%"
            )
    else:
        print("No tickers matched the buy rules on that date.")

    n_by: dict[tuple, int] = {}
    for p in picks:
        n_by[(p["action"], p["label"])] = n_by.get((p["action"], p["label"]), 0) + 1
    print(
        "\nPositions:", ", ".join(f"{k[0]}+{k[1]}={v}" for k, v in sorted(n_by.items())) or "none"
    )
    if skipped:
        print(
            f"Skipped {len(skipped)}:",
            ", ".join(f"{t}({why})" for t, why in skipped[:15]),
            "..." if len(skipped) > 15 else "",
        )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Time-machine backtest of the current scoring formulas."
    )
    ap.add_argument("--date", help="buy-as-of date YYYY-MM-DD (default: one month ago)")
    ap.add_argument(
        "--months", type=int, default=1, help="months back if --date omitted (default 1)"
    )
    ap.add_argument("--value-date", help="valuation date YYYY-MM-DD (default: latest close)")
    args = ap.parse_args()

    today = datetime.now().date()
    d = date.fromisoformat(args.date) if args.date else today - relativedelta(months=args.months)
    vd = date.fromisoformat(args.value_date) if args.value_date else None
    asyncio.run(run(d, vd))


if __name__ == "__main__":
    main()
