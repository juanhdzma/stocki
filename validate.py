"""Out-of-sample validation: does the signal hold across regimes, or only in this rally?

Unlike backtest.py/experiment.py (buy at D, value at TODAY -> all windows end in one rally), this
uses MANY entry dates each with its OWN 6-month forward window (E -> E+6m), spanning 2022-2025
including the 2022 drawdown. For each window it ranks tickers by a factor, buys the top-N equal
weight, and compares the forward return to SPY over the same window.

Factors tested (what's reconstructable point-in-time at each date):
  - MOM  : 6-month price momentum (return over prior 126 trading days) — the Screen's core. Price-only.
  - MOMsn: same, ranked WITHIN sector (sector-neutral) — the app's Screen column.
  - FCF  : fcf_yield = latest fully-reported annual FCF / (current shares x price_E) — the Long's
           core value signal, COARSE (annual not TTM, current share count). Value ~= Long.

Limits (stated honestly): quarter-trajectory factors, point-in-time TTM, insiders and analyst
targets are NOT reconstructable this far back, so this validates the price + coarse-value core,
not the full composite. Run inside the container:
  docker compose cp validate.py stocki:/app/validate.py && docker compose exec stocki python3 /app/validate.py
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select

from core.fetchers.yahoo import batch_download_history
from db.cache import AsyncSessionLocal, read_all_fundamentals, read_snapshot
from db.models import Watchlist

LOOKBACK_TD = 126  # ~6m momentum
HOLDING_TD = 126  # ~6m forward hold
TOP_N = 15


def _pos(index: pd.DatetimeIndex, d: date) -> int | None:
    p = index.searchsorted(pd.Timestamp(d), side="right") - 1
    return int(p) if p >= 0 else None


def _series(hist, field, ticker):
    try:
        c = hist[field]
        s = c[ticker] if ticker in c.columns else None
        return s.dropna() if s is not None else None
    except (KeyError, AttributeError):
        return None


def _annual_fcf_asof(funds: list[dict], e: date) -> float | None:
    """Latest annual FCF whose year was fully reported before E (approx report = Mar 1 of Y+1)."""
    best = None
    for f in funds:
        if f.get("type") != "annual" or f.get("fcf") is None:
            continue
        try:
            y = int(f["period"])
        except (ValueError, TypeError):
            continue
        if date(y + 1, 3, 1) <= e:
            if best is None or y > best[0]:
                best = (y, f["fcf"])
    return best[1] if best else None


def _entry_dates(today: date) -> list[date]:
    dates, d = [], date(2022, 1, 15)
    last = today - timedelta(days=HOLDING_TD * 365 // 252 + 20)  # need a full forward window
    while d <= last:
        dates.append(d)
        m = d.month + 3
        d = date(d.year + (m - 1) // 12, (m - 1) % 12 + 1, 15)
    return dates


def _topn_fwd(items: list[tuple[float, float]], n: int) -> float | None:
    """items = (factor, fwd_return); return mean fwd of the top-n by factor."""
    items = [x for x in items if x[0] is not None and x[1] is not None]
    if len(items) < n:
        return None
    top = sorted(items, key=lambda x: -x[0])[:n]
    return sum(f for _, f in top) / len(top)


def _quintile(items: list[tuple[float, float]]) -> float | None:
    items = [x for x in items if x[0] is not None and x[1] is not None]
    if len(items) < 20:
        return None
    items.sort(key=lambda x: x[0])
    k = len(items) // 5
    return sum(f for _, f in items[-k:]) / k - sum(f for _, f in items[:k]) / k


async def run() -> None:
    async with AsyncSessionLocal() as s:
        tickers = [r[0] for r in (await s.execute(select(Watchlist.ticker))).all()]
        funds_map, shares, sector = {}, {}, {}
        for t in tickers:
            funds_map[t] = await read_all_fundamentals(s, t)
            snap = await read_snapshot(s, t)
            shares[t] = (snap or {}).get("shares_outstanding")
            sector[t] = (snap or {}).get("sector") or "?"

    print(f"Downloading 5y price history for {len(tickers)} tickers + SPY ...")
    hist = await asyncio.to_thread(batch_download_history, tickers, "5y")
    spy = _series(hist, "Close", "SPY")
    closes = {t: _series(hist, "Close", t) for t in tickers}

    today = pd.Timestamp(spy.index[-1]).date()
    rows = []
    for e in _entry_dates(today):
        se = _pos(spy.index, e)
        if se is None or se + HOLDING_TD >= len(spy):
            continue
        spy_fwd = float(spy.iloc[se + HOLDING_TD] / spy.iloc[se] - 1)

        mom, momsn_by_sec, fcf = [], {}, []
        fwd_map = {}
        for t in tickers:
            c = closes[t]
            if c is None:
                continue
            pe = _pos(c.index, e)
            if pe is None or pe - LOOKBACK_TD < 0 or pe + HOLDING_TD >= len(c):
                continue
            fwd = float(c.iloc[pe + HOLDING_TD] / c.iloc[pe] - 1)
            fwd_map[t] = fwd
            m = float(c.iloc[pe] / c.iloc[pe - LOOKBACK_TD] - 1)
            mom.append((m, fwd))
            momsn_by_sec.setdefault(sector[t], []).append((t, m, fwd))
            af = _annual_fcf_asof(funds_map[t], e)
            mc = (shares[t] * float(c.iloc[pe])) if shares[t] else None
            fcf.append((af / mc if (af is not None and mc) else None, fwd))

        # sector-neutral momentum: percentile rank within sector, then top-N overall by that rank
        sn = []
        for group in momsn_by_sec.values():
            g = sorted(group, key=lambda x: x[1])
            n = len(g)
            for pos, (t, _, fwd) in enumerate(g):
                sn.append((pos / (n - 1) if n > 1 else 0.5, fwd))

        rows.append(
            {
                "date": e.isoformat(),
                "spy": spy_fwd,
                "mom": _topn_fwd(mom, TOP_N),
                "momsn": _topn_fwd(sn, TOP_N),
                "fcf": _topn_fwd(fcf, TOP_N),
                "mom_q": _quintile(mom),
                "fcf_q": _quintile(fcf),
            }
        )

    _report(rows)


def _report(rows) -> None:
    print("\nOut-of-sample: each row is an independent entry date, held 6 months (E -> E+6m).")
    print("MOM/MOMsn/FCF = top-15 forward return; (α) vs SPY same window. DD = SPY drawdown window.\n")
    hdr = f"{'ENTRY':<11}{'SPY':>8}{'MOM':>8}{'α':>7}{'MOMsn':>8}{'α':>7}{'FCF':>8}{'α':>7}{'':>5}"
    print(hdr)
    print("-" * len(hdr))
    agg = {k: [] for k in ("mom", "momsn", "fcf")}
    hit = dict.fromkeys(agg, 0)
    nwin = 0
    for r in rows:
        if r["mom"] is None:
            continue
        nwin += 1
        dd = " DD" if r["spy"] < 0 else ""

        def cell(k):
            v = r[k]
            if v is None:
                return f"{'—':>8}{'—':>7}"
            a = v - r["spy"]
            agg[k].append(a)
            return f"{v * 100:>+8.1f}{a * 100:>+7.1f}"

        line = f"{r['date']:<11}{r['spy'] * 100:>+8.1f}"
        for k in ("mom", "momsn", "fcf"):
            a_before = len(agg[k])
            line += cell(k)
            if len(agg[k]) > a_before and agg[k][-1] > 0:
                hit[k] += 1
        print(line + f"{dd:>5}")

    print("-" * len(hdr))
    print(f"\nWindows: {nwin}   (drawdown windows: {sum(1 for r in rows if r['mom'] is not None and r['spy'] < 0)})")
    for k in ("mom", "momsn", "fcf"):
        a = agg[k]
        if not a:
            continue
        avg = sum(a) / len(a)
        print(f"  {k:<6} avg α {avg * 100:>+6.1f}pp   beat SPY {hit[k]}/{len(a)} windows   worst α {min(a) * 100:>+6.1f}pp")

    # drawdown-only view: the real test
    print("\nDrawdown windows only (SPY < 0) — does the factor protect or amplify?")
    for k in ("mom", "momsn", "fcf"):
        dd_a = [r[k] - r["spy"] for r in rows if r[k] is not None and r["spy"] < 0]
        dd_r = [r[k] for r in rows if r[k] is not None and r["spy"] < 0]
        if dd_a:
            print(f"  {k:<6} avg return {sum(dd_r) / len(dd_r) * 100:>+6.1f}%   avg α {sum(dd_a) / len(dd_a) * 100:>+6.1f}pp")


if __name__ == "__main__":
    asyncio.run(run())
