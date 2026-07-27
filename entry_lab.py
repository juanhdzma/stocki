"""Entry-timing lab: given the watchlist is 'good stocks', which ENTRY rule improves 1M/3M/6M?

Assumes selection is fine (the curated names are good) and isolates ENTRY. At each date E, apply a
boolean entry rule (buy the names that PASS now); measure their forward return at 1M/3M/6M vs the
baseline of buying ALL names. edge = rule_mean − all_mean per horizon (positive = the rule times
entry better). Across 2022-2025 incl. drawdowns, per-window then averaged so each regime counts once.

Hypothesis under test: the best entry differs by horizon — 1M mean-reverts (buy weakness), 6m trends
(buy strength). If so, buy_target should be horizon-aware rather than one-size-fits-all.

  docker compose cp entry_lab.py stocki:/app/entry_lab.py && docker compose exec stocki python3 /app/entry_lab.py
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

HORIZONS = {"1M": 21, "3M": 63, "6M": 126}


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
    last = today - timedelta(days=max(HORIZONS.values()) * 365 // 252 + 20)
    while d <= last:
        dates.append(d)
        m = d.month + 3
        d = date(d.year + (m - 1) // 12, (m - 1) % 12 + 1, 15)
    return dates


def _typical_pullback(a, pe, window=504):
    """Median depth of this ticker's own drawdown episodes (≥5%) over the trailing `window` days,
    using only data up to pe (no look-ahead). Mirrors core.fetchers.yahoo._compute_typical_pullback."""
    seg = a[max(0, pe - window + 1) : pe + 1]
    if len(seg) < 60:
        return None
    dd = seg / np.maximum.accumulate(seg) - 1.0
    troughs, cur_min, active = [], 0.0, False
    for v in dd:
        if v <= -0.05:
            active, cur_min = True, min(cur_min, v)
        elif active:
            troughs.append(cur_min)
            active, cur_min = False, 0.0
    if active:
        troughs.append(cur_min)
    return abs(float(np.median(troughs))) if troughs else None


def _state(a, pe):
    """Price-derived features at pe for the entry rules."""
    def ret(n):
        return a[pe] / a[pe - n] - 1 if pe - n >= 0 else None

    def ma(n):
        return float(np.mean(a[pe - n + 1 : pe + 1])) if pe - n + 1 >= 0 else None

    low52 = float(np.min(a[max(0, pe - 251) : pe + 1]))
    high52 = float(np.max(a[max(0, pe - 251) : pe + 1]))
    hi20 = float(np.max(a[max(0, pe - 19) : pe + 1]))
    ma50, ma200 = ma(50), ma(200)
    p = float(a[pe])
    return {
        "r1m": ret(21), "r3m": ret(63), "r6m": ret(126),
        "ma50_gap": (p / ma50 - 1) if ma50 else None,
        "ma200_gap": (p / ma200 - 1) if ma200 else None,
        "from_low": (p - low52) / p,
        "from_high": (p - high52) / high52,
        "from_hi20": p / hi20 - 1,
        "typ_pb": _typical_pullback(a, pe),
    }


# rule(state) -> bool | None (None = can't evaluate, name excluded from that rule this window)
def _up(s):  # in an uptrend
    return s["ma200_gap"] is not None and s["ma200_gap"] > 0


RULES = {
    "ALL (baseline)": lambda s: True,
    # EXACT production buy_target COMPRAR rule: deep value OR pullback-in-uptrend
    "PROD deep|up+dip": lambda s: s["from_high"] <= -0.20
    or (s["r6m"] is not None and s["r6m"] > 0 and s["from_high"] <= -0.02),
    "PROD: deep only": lambda s: s["from_high"] <= -0.20,
    "PROD: pullback only": lambda s: s["r6m"] is not None and s["r6m"] > 0 and s["from_high"] <= -0.02,
    # UNDER TEST: per-ticker "deep" = drawdown >= this name's own median pullback depth,
    # vs the flat −20% ("PROD: deep only"). Same buy_target question, vol-normalized threshold.
    "PT: >=typ_pb": lambda s: s["typ_pb"] is not None and s["from_high"] <= -s["typ_pb"],
    "PT: >=1.25*typ_pb": lambda s: s["typ_pb"] is not None and s["from_high"] <= -1.25 * s["typ_pb"],
    "PT: >=typ cap[.10,.30]": lambda s: s["typ_pb"] is not None
    and s["from_high"] <= -min(0.30, max(0.10, s["typ_pb"])),
    # regime 1: deep weakness (reference — already validated)
    "deep(<-20)": lambda s: s["r6m"] is not None and s["r6m"] < -0.20,
    # regime 2 candidates: strong name that pulled back a LITTLE
    "up+dip2-8%hi20": lambda s: _up(s) and -0.08 <= s["from_hi20"] <= -0.02,
    "up+dip3-10%hi20": lambda s: _up(s) and -0.10 <= s["from_hi20"] <= -0.03,
    "up+1mdip(-10..-1)": lambda s: _up(s) and s["r1m"] is not None and -0.10 <= s["r1m"] <= -0.01,
    "mom6pos+dip2-8": lambda s: s["r6m"] is not None and s["r6m"] > 0 and -0.08 <= s["from_hi20"] <= -0.02,
    "nearhigh+dip": lambda s: -0.12 <= s["from_high"] <= -0.03 and s["r1m"] is not None and s["r1m"] < 0,
    "up+shallow(<-2%hi20)": lambda s: _up(s) and s["from_hi20"] <= -0.02,
    # two-regime combos: deep weakness OR strong-with-small-dip
    "TWO: deep|up+dip2-8": lambda s: (s["r6m"] is not None and s["r6m"] < -0.20)
    or (_up(s) and -0.08 <= s["from_hi20"] <= -0.02),
    "TWO: deep|up+1mdip": lambda s: (s["r6m"] is not None and s["r6m"] < -0.20)
    or (_up(s) and s["r1m"] is not None and -0.10 <= s["r1m"] <= -0.01),
}


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

    # per rule per horizon: list of per-window edges (rule_mean - all_mean); + coverage
    edges = {r: {h: [] for h in HORIZONS} for r in RULES}
    cover = {r: [] for r in RULES}
    for e in _entry_dates(today):
        # gather per-ticker state + forward returns
        recs = []
        for _t, (idx, a) in arrs.items():
            pe = _pos(idx, e)
            if pe is None or pe + max(HORIZONS.values()) >= len(a):
                continue
            fwd = {h: float(a[pe + n] / a[pe] - 1) for h, n in HORIZONS.items()}
            recs.append((_state(a, pe), fwd))
        if len(recs) < 20:
            continue
        base = {h: np.mean([r[1][h] for r in recs]) for h in HORIZONS}
        for rname, rule in RULES.items():
            passed = [r for r in recs if bool(rule(r[0]))]
            if len(passed) < 5:
                continue
            cover[rname].append(len(passed) / len(recs))
            for h in HORIZONS:
                edges[rname][h].append(np.mean([r[1][h] for r in passed]) - base[h])

    _report(edges, cover)


def _report(edges, cover):
    print("\nEntry-rule edge = (passing-names forward return) − (all-names forward return), per horizon.")
    print("Positive = the rule improves entry at that horizon. Averaged over 2022-2025 windows.\n")
    print(f"{'RULE':<18}{'cov%':>6}" + "".join(f"{h:>9}" for h in HORIZONS))
    print("-" * 51)
    for rname in RULES:
        cov = np.mean(cover[rname]) if cover[rname] else 0
        cells = ""
        for h in HORIZONS:
            e = edges[rname][h]
            cells += f"{np.mean(e) * 100:>+9.1f}" if e else f"{'—':>9}"
        print(f"{rname:<18}{cov * 100:>5.0f}%{cells}")
    print("\ncov% = avg share of names that pass the rule. edge in pp vs buying everything.")


if __name__ == "__main__":
    asyncio.run(run())
