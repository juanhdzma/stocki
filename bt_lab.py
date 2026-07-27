"""buy_target lab — which price-timing signal actually predicts forward return, across regimes?

Same out-of-sample frame as validate.py (many entry dates, each held 6m, 2022-2025 incl. drawdowns),
but here every candidate is a pure ENTRY-TIMING signal computed from the price series at date E.
The question buy_target should answer: given I like a name, WHEN do I buy? Buy strength (momentum,
near highs) or buy weakness (near 52w low = the current "washed-out" regime)?

Finding: momentum (esp. gated by MA200) is the strongest ENTRY RANKING; but as a per-ticker binary
gate ("above MA200 AND mom>0 -> buy") it does NOT separate winners from losers (beaten-down names
often rebound hardest). So the entry edge is cross-sectional ranking, not a per-name binary. The
current "washed-out near 52w low" is the weakest direction — hence buy_target now requires the
3m return to have turned non-negative before calling a near-low name a buy.

  docker compose cp bt_lab.py stocki:/app/bt_lab.py && docker compose exec stocki python3 /app/bt_lab.py
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select

from core.fetchers.yahoo import batch_download_history
from db.cache import AsyncSessionLocal
from db.models import Watchlist

HOLD_TD = 126
TOP_N = 15


def _pos(index, d):
    p = index.searchsorted(pd.Timestamp(d), side="right") - 1
    return int(p) if p >= 0 else None


def _series(hist, ticker):
    try:
        c = hist["Close"]
        s = c[ticker] if ticker in c.columns else None
        return s.dropna() if s is not None else None
    except (KeyError, AttributeError):
        return None


def _entry_dates(today):
    dates, d = [], date(2022, 1, 15)
    last = today - timedelta(days=HOLD_TD * 365 // 252 + 20)
    while d <= last:
        dates.append(d)
        m = d.month + 3
        d = date(d.year + (m - 1) // 12, (m - 1) % 12 + 1, 15)
    return dates


def _ret(a, pe, n):
    return a[pe] / a[pe - n] - 1 if pe - n >= 0 else None


def _ma_gap(a, pe, n):
    if pe - n + 1 < 0:
        return None
    return a[pe] / np.mean(a[pe - n + 1 : pe + 1]) - 1


def _dist_low(a, pe, n=252):
    lo = np.min(a[max(0, pe - n + 1) : pe + 1])
    return a[pe] / lo - 1 if lo > 0 else None


def _dist_high(a, pe, n=252):
    hi = np.max(a[max(0, pe - n + 1) : pe + 1])
    return a[pe] / hi if hi > 0 else None


def _pullback_in_uptrend(a, pe):
    m6 = _ret(a, pe, 126)
    if m6 is None or m6 <= 0:
        return None
    hi20 = np.max(a[max(0, pe - 19) : pe + 1])
    dip = a[pe] / hi20 - 1
    return -abs(dip + 0.05)  # peaks at a ~5% pullback


SIGNALS = {
    "mom_3m": lambda a, pe: _ret(a, pe, 63),
    "mom_6m": lambda a, pe: _ret(a, pe, 126),
    "mom_12m": lambda a, pe: _ret(a, pe, 252),
    "near_52w_LOW": lambda a, pe: -_dist_low(a, pe) if _dist_low(a, pe) is not None else None,
    "near_52w_HIGH": lambda a, pe: _dist_high(a, pe),
    "above_MA50": lambda a, pe: _ma_gap(a, pe, 50),
    "above_MA200": lambda a, pe: _ma_gap(a, pe, 200),
    "pullback_uptrend": _pullback_in_uptrend,
}

COMBOS = {
    "mom6+ma200": {"mom_6m": 1, "above_MA200": 1},
    "mom6+nearlow": {"mom_6m": 1, "near_52w_LOW": 1},
    "mom6+ma50": {"mom_6m": 1, "above_MA50": 1},
    "ma200+accel": {"above_MA200": 1, "accel": 1},
    "mom6+ma200+nearlow": {"mom_6m": 1, "above_MA200": 1, "near_52w_LOW": 1},
    "mom6_x_ma200gate": "gate",
}


def _pct_rank(pairs):
    present = sorted(((k, v) for k, v in pairs if v is not None), key=lambda x: x[1])
    n = len(present)
    return {k: (i / (n - 1) if n > 1 else 0.5) for i, (k, _) in enumerate(present)}


async def run():
    async with AsyncSessionLocal() as s:
        tickers = [r[0] for r in (await s.execute(select(Watchlist.ticker))).all()]
    print(f"Downloading 5y price history for {len(tickers)} tickers + SPY ...")
    hist = await asyncio.to_thread(batch_download_history, tickers, "5y")
    spy = _series(hist, "SPY")
    arrs = {}
    for t in tickers:
        c = _series(hist, t)
        if c is not None and len(c) > 260:
            arrs[t] = (c.index, c.to_numpy())

    today = pd.Timestamp(spy.index[-1]).date()
    windows = []
    for e in _entry_dates(today):
        se = _pos(spy.index, e)
        if se is None or se + HOLD_TD >= len(spy):
            continue
        spy_fwd = float(spy.iloc[se + HOLD_TD] / spy.iloc[se] - 1)
        prim, fwd_map, extra = {}, {}, {}
        for t, (idx, a) in arrs.items():
            pe = _pos(idx, e)
            if pe is None or pe + HOLD_TD >= len(a):
                continue
            fwd_map[t] = float(a[pe + HOLD_TD] / a[pe] - 1)
            prim[t] = {name: fn(a, pe) for name, fn in SIGNALS.items()}
            m3, m6 = _ret(a, pe, 63), _ret(a, pe, 126)
            extra[t] = {
                "accel": (m3 - m6) if (m3 is not None and m6 is not None) else None,
                "above200": _ma_gap(a, pe, 200),
            }

        per_sig = {}
        for name in SIGNALS:
            items = [(prim[t][name], fwd_map[t]) for t in prim if prim[t][name] is not None]
            if len(items) >= TOP_N:
                per_sig[name] = sum(f for _, f in sorted(items, key=lambda x: -x[0])[:TOP_N]) / TOP_N

        rank_cache = {}
        for pname in ("mom_6m", "above_MA200", "above_MA50", "near_52w_LOW"):
            rank_cache[pname] = _pct_rank([(t, prim[t][pname]) for t in prim])
        rank_cache["accel"] = _pct_rank([(t, extra[t]["accel"]) for t in extra])
        for cname, spec in COMBOS.items():
            if spec == "gate":
                elig = [t for t in prim if (extra[t]["above200"] or -1) > 0]
                items = [(prim[t]["mom_6m"], fwd_map[t]) for t in elig if prim[t]["mom_6m"] is not None]
            else:
                comp = {t: sum(w * rank_cache[p].get(t, 0.5) for p, w in spec.items()) for t in prim}
                items = [(comp[t], fwd_map[t]) for t in prim]
            if len(items) >= TOP_N:
                per_sig[cname] = sum(f for _, f in sorted(items, key=lambda x: -x[0])[:TOP_N]) / TOP_N

        pf = [fwd_map[t] for t in prim if (extra[t]["above200"] or -1) > 0 and (prim[t]["mom_6m"] or -1) > 0]
        ff = [fwd_map[t] for t in prim if not ((extra[t]["above200"] or -1) > 0 and (prim[t]["mom_6m"] or -1) > 0)]
        gate = {
            "pass": sum(pf) / len(pf) if pf else None,
            "fail": sum(ff) / len(ff) if ff else None,
            "n": len(pf),
        }
        windows.append({"date": e.isoformat(), "spy": spy_fwd, "dd": spy_fwd < 0, "sig": per_sig, "gate": gate})

    _report(windows, list(SIGNALS) + list(COMBOS))
    _report_gate(windows)


def _report(windows, names):
    print("\nEntry-timing signals — top-15 by signal, 6m forward, across entry dates 2022-2025.")
    print("avgα = mean forward-return advantage vs SPY (pp). DDret = avg return in SPY-down windows.\n")
    print(f"{'SIGNAL':<20}{'avgα':>8}{'beatSPY':>9}{'worst':>8}{'DDret':>8}")
    print("-" * 53)
    stats = []
    for n in names:
        al = [w["sig"][n] - w["spy"] for w in windows if n in w["sig"]]
        ddr = [w["sig"][n] for w in windows if n in w["sig"] and w["dd"]]
        if al:
            stats.append((sum(al) / len(al), n, al, ddr))
    for avg, n, al, ddr in sorted(stats, key=lambda x: -x[0]):
        beat = sum(1 for a in al if a > 0)
        dd = f"{sum(ddr) / len(ddr) * 100:>+7.1f}" if ddr else f"{'—':>7}"
        print(f"{n:<20}{avg * 100:>+8.1f}{beat:>6}/{len(al):<2}{min(al) * 100:>+8.1f}{dd:>8}")


def _report_gate(windows):
    print("\nBinary COMPRAR gate — 'above MA200 AND mom_6m > 0' vs the rest (mean 6m forward, ALL names).")
    print(f"{'ENTRY':<11}{'SPY':>7}{'PASS':>8}{'FAIL':>8}{'spread':>8}{'nPASS':>7}")
    print("-" * 49)
    spreads, dd_pass = [], []
    for w in windows:
        g = w["gate"]
        if g["pass"] is None or g["fail"] is None:
            continue
        sp = g["pass"] - g["fail"]
        spreads.append(sp)
        if w["dd"]:
            dd_pass.append(g["pass"])
        print(f"{w['date']:<11}{w['spy'] * 100:>+7.1f}{g['pass'] * 100:>+8.1f}{g['fail'] * 100:>+8.1f}{sp * 100:>+8.1f}{g['n']:>7}" + ("  DD" if w["dd"] else ""))
    if spreads:
        print("-" * 49)
        print(f"avg PASS−FAIL spread: {sum(spreads) / len(spreads) * 100:+.1f}pp   PASS beat FAIL {sum(1 for s in spreads if s > 0)}/{len(spreads)} windows")
        if dd_pass:
            print(f"drawdown windows: PASS avg return {sum(dd_pass) / len(dd_pass) * 100:+.1f}%")


if __name__ == "__main__":
    asyncio.run(run())
