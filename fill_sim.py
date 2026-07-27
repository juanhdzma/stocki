"""buy_target fill-simulation: does WAITING for the dip actually beat buying now?

The untested half of buy_target: for names it says "wait for a dip to $target", we place a limit at
$target over a wait window and ask, honestly, across 2022-2025 (incl. drawdowns):
  1. does the dip come?  (fill rate)
  2. when it fills, is the cheaper entry worth it?  (return on filled names vs buy-now)
  3. when it does NOT fill, do you miss the run?  (unfilled handling: cash vs chase-at-market)

Uses the PRODUCTION _buy_target on a reconstructed point-in-time snapshot, so the targets match
what the app would have shown. Everything is price-only, fully reconstructable at any date.
For each "wait" name at entry E, we compare, measured to the SAME exit E+6m:
  - buy_now : return from price_E
  - wait    : if the window low touches the target -> enter at target; else miss (cash 0) or chase.

  docker compose cp fill_sim.py stocki:/app/fill_sim.py && docker compose exec stocki python3 /app/fill_sim.py
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select

from core.fetchers.yahoo import batch_download_history
from core.scorers.composite import _buy_target
from db.cache import AsyncSessionLocal
from db.models import Watchlist

HOLD_TD = 126  # 6m exit
WAIT_WINDOWS = (21, 42)  # how long you leave the limit order working (~1m, ~2m)
_RET_TD = {"ticker_return_1m": 21, "ticker_return_3m": 63, "ticker_return_6m": 126, "ticker_return_12m": 252}


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


def _typical_pullback(a, pe):
    s = a[max(0, pe - 503) : pe + 1]
    if len(s) < 60:
        return None
    cummax = np.maximum.accumulate(s)
    dd = s / cummax - 1.0
    troughs, cur, active = [], 0.0, False
    for v in dd:
        if v <= -0.05:
            active, cur = True, min(cur, v)
        elif active:
            troughs.append(cur)
            active, cur = False, 0.0
    if active:
        troughs.append(cur)
    return abs(float(np.median(troughs))) if troughs else None


def _snap_at(a, pe):
    price = float(a[pe])
    low52 = float(np.min(a[max(0, pe - 251) : pe + 1]))
    returns = {k: (float(a[pe] / a[pe - n] - 1) if pe - n >= 0 else None) for k, n in _RET_TD.items()}
    return {
        "price": price,
        "week52_low": low52,
        "returns": returns,
        "typical_pullback_pct": _typical_pullback(a, pe),
    }


def _entry_dates(today):
    dates, d = [], date(2022, 1, 15)
    last = today - timedelta(days=HOLD_TD * 365 // 252 + 20)
    while d <= last:
        dates.append(d)
        m = d.month + 3
        d = date(d.year + (m - 1) // 12, (m - 1) % 12 + 1, 15)
    return dates


async def run():
    async with AsyncSessionLocal() as s:
        tickers = [r[0] for r in (await s.execute(select(Watchlist.ticker))).all()]
    print(f"Downloading 5y price history for {len(tickers)} tickers + SPY ...")
    hist = await asyncio.to_thread(batch_download_history, tickers, "5y")
    arrs = {}
    for t in tickers:
        c = _series(hist, t)
        if c is not None and len(c) > 260:
            arrs[t] = (c.index, c.to_numpy())

    spy = _series(hist, "SPY")
    today = pd.Timestamp(spy.index[-1]).date()

    # accumulate per wait-window: lists of (buy_now, filled?, wait_ret_if_filled, chase_ret)
    acc = {w: {"buy_now": [], "filled": [], "wait_at_T": [], "chase": []} for w in WAIT_WINDOWS}
    n_wait = 0
    n_total = 0
    for e in _entry_dates(today):
        for _t, (idx, a) in arrs.items():
            pe = _pos(idx, e)
            if pe is None or pe + HOLD_TD >= len(a):
                continue
            n_total += 1
            snap = _snap_at(a, pe)
            bt = _buy_target(snap)
            if not bt or bt["signal"] != "wait":
                continue
            target = bt["price"]
            price_e = snap["price"]
            exit_px = float(a[pe + HOLD_TD])
            buy_now = exit_px / price_e - 1
            n_wait += 1
            for w in WAIT_WINDOWS:
                win = a[pe + 1 : pe + 1 + w]
                if len(win) == 0:
                    continue
                filled = float(np.min(win)) <= target
                acc[w]["buy_now"].append(buy_now)
                acc[w]["filled"].append(1 if filled else 0)
                acc[w]["wait_at_T"].append(exit_px / target - 1 if filled else None)
                # if not filled: chase = buy at market at window end
                chase_px = float(a[pe + w]) if pe + w < len(a) else exit_px
                acc[w]["chase"].append((exit_px / target - 1) if filled else (exit_px / chase_px - 1))

    _report(acc, n_wait, n_total)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else float("nan")


def _report(acc, n_wait, n_total):
    print(f"\nWait-signal names: {n_wait} of {n_total} ticker-dates (rest were COMPRAR/no-signal).")
    print("All returns measured to the same 6m exit. 'wait' strategies act only on wait-names.\n")
    print(f"{'WAIT_WIN':<9}{'fill%':>7}{'buy_now':>9}{'filled@T':>10}{'wait_cash':>11}{'wait_chase':>12}{'edge_filled':>12}")
    print("-" * 71)
    for w, d in acc.items():
        fill = _mean(d["filled"])
        buy_now = _mean(d["buy_now"])
        # filled names only: entry at target
        filled_at_T = _mean([r for r in d["wait_at_T"] if r is not None])
        # buy_now on that same filled subset (edge from the cheaper entry, isolated)
        edge = _mean(
            [
                (rt - bn)
                for rt, bn in zip(d["wait_at_T"], d["buy_now"], strict=True)
                if rt is not None
            ]
        )
        # whole wait book, miss handled two ways:
        wait_cash = _mean([(rt if rt is not None else 0.0) for rt in d["wait_at_T"]])
        wait_chase = _mean(d["chase"])
        print(
            f"{str(w) + 'td':<9}{fill * 100:>6.0f}%{buy_now * 100:>+9.1f}{filled_at_T * 100:>+10.1f}"
            f"{wait_cash * 100:>+11.1f}{wait_chase * 100:>+12.1f}{edge * 100:>+12.1f}"
        )
    print(
        "\nbuy_now = buy every wait-name now | filled@T = return of names whose dip filled (entered at target)"
        "\nwait_cash = whole book, unfilled sits in cash (0) | wait_chase = unfilled bought at window-end"
        "\nedge_filled = filled@T minus buy_now on the SAME names (pure benefit of the cheaper entry)"
    )


if __name__ == "__main__":
    asyncio.run(run())
