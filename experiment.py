"""Iterate on score + price (buy_target) definitions and backtest each variant at 1M/3M/6M.

Two phases so iteration is fast:
  build : reconstruct point-in-time inputs for every ticker at each horizon (slow: downloads +
          grade history), compute the base sub-scores once, pickle to /app/exp_cache.pkl.
  eval  : load the pickle and score the CONFIGS list purely in-process (fast) — recombining the
          cached sub-scores with each config's weights / boosts / buy_target rules / sizing.

  docker compose exec stocki python3 /app/experiment.py build
  docker compose exec stocki python3 /app/experiment.py eval
"""

from __future__ import annotations

import asyncio
import math
import pickle
import sys
from datetime import datetime

from dateutil.relativedelta import relativedelta
from sqlalchemy import select

from backtest import _asof_pos, _period_available, _series, reconstruct_snapshot
from core.fetchers.yahoo import batch_download_history, fetch_grade_history, init_auth
from core.scorers.base import clamp
from core.scorers.composite import compute_all
from db.cache import AsyncSessionLocal, read_all_fundamentals, read_snapshot
from db.models import Watchlist

CACHE = "/app/exp_cache.pkl"
HORIZONS = {"1M": 1, "3M": 3, "6M": 6}

_SNAP_KEYS = (
    "price",
    "week52_low",
    "week52_high",
    "returns",
    "typical_pullback_pct",
    "day_change_pct",
    "beta",
    "revenue_growth",
)


# ── build phase ────────────────────────────────────────────────────────────────


async def build() -> None:
    async with AsyncSessionLocal() as session:
        tickers = [r[0] for r in (await session.execute(select(Watchlist.ticker))).all()]

    print(f"Downloading 2y price history for {len(tickers)} tickers + SPY ...")
    hist = await asyncio.to_thread(batch_download_history, tickers, "2y")
    spy = _series(hist, "Close", "SPY")
    print("Fetching analyst rating history ...")
    await asyncio.to_thread(init_auth)
    from concurrent.futures import ThreadPoolExecutor

    def _grades():
        with ThreadPoolExecutor(max_workers=8) as ex:
            return dict(zip(tickers, ex.map(fetch_grade_history, tickers), strict=True))

    grades = await asyncio.to_thread(_grades)

    today = datetime.now().date()
    cache: dict = {}
    async with AsyncSessionLocal() as session:
        for hlabel, months in HORIZONS.items():
            d = today - relativedelta(months=months)
            si = _asof_pos(spy.index, d)
            spy_ret = float(spy.iloc[-1] / spy.iloc[si] - 1) if si is not None else None
            rows = []
            for t in tickers:
                closes = _series(hist, "Close", t)
                if closes is None or closes.empty:
                    continue
                snap_now = await read_snapshot(session, t)
                if not snap_now:
                    continue
                funds = [
                    f
                    for f in await read_all_fundamentals(session, t)
                    if _period_available(f["period"], d)
                ]
                snap = reconstruct_snapshot(snap_now, closes, spy, d, funds, grades.get(t, []))
                if snap is None:
                    continue
                try:
                    res = compute_all(funds, snap, as_of=datetime(d.year, d.month, d.day))
                except Exception:
                    continue
                i = _asof_pos(closes.index, d)
                rows.append(
                    {
                        "ticker": t,
                        "fundamental_momentum": res["fundamental_momentum"],
                        "value_quality": res["value_quality"],
                        "insider_conviction": res["insider_conviction"],
                        "price_long": res["price_long"],
                        "snap": {k: snap.get(k) for k in _SNAP_KEYS},
                        "sector": snap.get("sector"),
                        "price_d": float(closes.iloc[i]),
                        "price_val": float(closes.iloc[-1]),
                    }
                )
            cache[hlabel] = {"spy_ret": spy_ret, "date": d.isoformat(), "rows": rows}
            print(f"  {hlabel} (D={d}): {len(rows)} tickers, SPY {spy_ret * 100:+.1f}%")

    with open(CACHE, "wb") as f:
        pickle.dump(cache, f)
    print(f"Cached -> {CACHE}")


# ── scoring (parameterized) ──────────────────────────────────────────────────

_TREND_KEYS = ("ticker_return_12m", "ticker_return_6m", "ticker_return_3m", "ticker_return_1m")


def _trend(snap: dict) -> float:
    r = snap.get("returns") or {}
    for k in _TREND_KEYS:
        if r.get(k) is not None:
            return r[k]
    return 0.0


def _quality(row: dict, w: dict) -> float | None:
    avail = {k: row[k]["score"] for k in w if row[k]["score"] is not None}
    tw = sum(w[k] for k in avail)
    if not avail or not tw:
        return None
    return sum(row[k]["score"] * w[k] / tw for k in avail)


def _dip_bonus(snap: dict, cfg: dict) -> float:
    day = snap.get("day_change_pct")
    wk = (snap.get("returns") or {}).get("ticker_return_1w")
    dd = max(-(day / 100), 0.0) if day is not None else 0.0
    wd = max(-wk, 0.0) if wk is not None else 0.0
    eff = max(dd * 2.2, wd)
    if eff <= 0:
        return 0.0
    beta = max(snap.get("beta") or 1.0, 0.5)
    return round(clamp(eff / beta / cfg["dip_ref_drop"], 0, 1) * cfg["dip_bonus_max"], 1)


def _action(score: float, cfg: dict) -> str:
    return next(lab for thr, lab in cfg["thresholds"] if score >= thr)


def _composite(row: dict, cfg: dict) -> tuple[float | None, str]:
    q = _quality(row, cfg["weights"])
    if q is None:
        return None, "N/A"
    pls = row["price_long"]["score"]
    price_attr = clamp((pls - 50) / 50, 0, 1) if pls is not None else 0.0
    mom = (row["snap"].get("returns") or {}).get("ticker_return_3m")
    mom_b = (
        clamp((mom or 0.0) / cfg["mom_ref"], 0, 1) * cfg["mom_boost_max"]
        if mom is not None
        else 0.0
    )
    score = clamp(
        q + price_attr * cfg["price_boost_max"] + _dip_bonus(row["snap"], cfg) + mom_b, 0, 100
    )
    if cfg["guardrail"]:
        rg = row["snap"].get("revenue_growth")
        if rg is not None and rg < 0:
            score = min(score, 79.9)
    score = round(score, 1)
    return score, _action(score, cfg)


def _buy_target(snap: dict, cfg: dict) -> dict | None:
    price, low = snap.get("price"), snap.get("week52_low")
    if not price or low is None or low <= 0:
        return None
    trend = _trend(snap)
    washed = (price - low) / price <= cfg["low_zone"]
    if washed and cfg.get("washout_confirm"):
        r1m = (snap.get("returns") or {}).get("ticker_return_1m")
        if r1m is None or r1m < cfg.get("confirm_thr", 0.0):
            washed = False  # near the low but still falling -> treat as falling, not "buy now"
    if washed:
        target = price
    elif trend >= 0:
        pull = snap.get("typical_pullback_pct")
        vol = clamp(pull / 0.10, 0.70, 1.40) if pull else 1.0
        dip = clamp(cfg["froth_k"] * math.log1p(trend) * vol, cfg["froth_min"], cfg["froth_max"])
        target = price * (1 - dip)
    else:
        target = low + cfg["fall_frac"] * (price - low)
        target = max(target, price * (1 - cfg["fall_max"]))
    return {
        "price": round(target, 2),
        "pct_from_current": round(target / price - 1, 4),
        "signal": "buy" if price <= target else "wait",
    }


def _label(bt: dict | None) -> str | None:
    if not bt:
        return None
    if bt["signal"] == "buy":
        return "COMPRAR"
    return "CASI" if bt["pct_from_current"] >= -0.04 else "ESPERAR"


# ── eval phase ────────────────────────────────────────────────────────────────

BASE = {
    "weights": {"fundamental_momentum": 0.40, "value_quality": 0.45, "insider_conviction": 0.15},
    "price_boost_max": 6.0,
    "dip_bonus_max": 10.0,
    "dip_ref_drop": 0.11,
    "mom_boost_max": 0.0,
    "mom_ref": 0.20,
    "guardrail": True,
    "thresholds": [(80, "STRONG-BUY"), (60, "BUY"), (40, "HOLD"), (20, "SELL"), (0, "STRONG-SELL")],
    "low_zone": 0.08,
    "froth_k": 0.045,
    "froth_min": 0.01,
    "froth_max": 0.11,
    "fall_frac": 0.45,
    "fall_max": 0.06,
    "washout_confirm": False,
    "confirm_thr": 0.0,
    "sizing": {
        ("STRONG-BUY", "COMPRAR"): 600,
        ("STRONG-BUY", "CASI"): 300,
        ("BUY", "COMPRAR"): 100,
    },
}


def cfg_with(**over) -> dict:
    c = {k: (dict(v) if isinstance(v, dict) else v) for k, v in BASE.items()}
    c.update(over)
    return c


def evaluate_horizon(hcache: dict, cfg: dict) -> dict:
    spy_ret = hcache["spy_ret"]
    inv = val = 0.0
    tier_ret: dict[str, list[float]] = {}
    picks = []
    for row in hcache["rows"]:
        score, action = _composite(row, cfg)
        if score is None:
            continue
        fwd = row["price_val"] / row["price_d"] - 1
        tier_ret.setdefault(action, []).append(fwd)
        label = _label(_buy_target(row["snap"], cfg))
        amt = cfg["sizing"].get((action, label), 0)
        if amt:
            inv += amt
            val += amt * (1 + fwd)
            picks.append((row["ticker"], action, label, score, fwd, amt))
    port_ret = (val / inv - 1) if inv else 0.0
    return {
        "port_ret": port_ret,
        "spy_ret": spy_ret,
        "alpha": port_ret - spy_ret,
        "inv": inv,
        "n": len(picks),
        "tier_ret": {k: sum(v) / len(v) for k, v in tier_ret.items()},
        "tier_n": {k: len(v) for k, v in tier_ret.items()},
        "picks": picks,
    }


# Carry-forward from iters 1-2: no dip, no insiders, growth tilt were the robust levers.
_W = {"fundamental_momentum": 0.50, "value_quality": 0.50, "insider_conviction": 0.0}
_G = {"weights": _W, "dip_bonus_max": 0.0}
_SIZE_SB = {("STRONG-BUY", "COMPRAR"): 600, ("STRONG-BUY", "CASI"): 300, ("BUY", "COMPRAR"): 100}
_SIZE_BUY = {("BUY", "COMPRAR"): 500, ("BUY", "CASI"): 300, ("STRONG-BUY", "COMPRAR"): 200}
_SIZE_COMPRAR = {
    ("STRONG-BUY", "COMPRAR"): 400,
    ("BUY", "COMPRAR"): 400,
    ("STRONG-BUY", "CASI"): 100,
    ("BUY", "CASI"): 100,
}

# CONFIGS: (name, cfg) — edit this list per iteration, re-run `eval`.
# Iteration 4: fine-tune around the champion (BUY-tier sizing + no-dip/no-insider/50-50).
_SIZE_BUY2 = {("BUY", "COMPRAR"): 600, ("BUY", "CASI"): 300, ("STRONG-BUY", "COMPRAR"): 100}
_SIZE_BUY3 = {
    ("BUY", "COMPRAR"): 400,
    ("BUY", "CASI"): 300,
    ("STRONG-BUY", "COMPRAR"): 200,
    ("STRONG-BUY", "CASI"): 100,
}
_TH_BUY55 = [(80, "STRONG-BUY"), (55, "BUY"), (40, "HOLD"), (20, "SELL"), (0, "STRONG-SELL")]
_TH_SB85 = [(85, "STRONG-BUY"), (60, "BUY"), (40, "HOLD"), (20, "SELL"), (0, "STRONG-SELL")]
CONFIGS = [
    ("champ (sBUY)", cfg_with(sizing=_SIZE_BUY, **_G)),
    ("champ_conf", cfg_with(sizing=_SIZE_BUY, washout_confirm=True, confirm_thr=0.02, **_G)),
    (
        "champ_mom4_conf",
        cfg_with(sizing=_SIZE_BUY, mom_boost_max=4.0, washout_confirm=True, confirm_thr=0.02, **_G),
    ),
    ("sBUY2", cfg_with(sizing=_SIZE_BUY2, **_G)),
    ("sBUY3", cfg_with(sizing=_SIZE_BUY3, **_G)),
    ("sBUY2_conf", cfg_with(sizing=_SIZE_BUY2, washout_confirm=True, confirm_thr=0.02, **_G)),
    ("champ_buy55", cfg_with(sizing=_SIZE_BUY, thresholds=_TH_BUY55, **_G)),
    ("champ_sb85", cfg_with(sizing=_SIZE_BUY, thresholds=_TH_SB85, **_G)),
    (
        "sBUY2_conf_buy55",
        cfg_with(
            sizing=_SIZE_BUY2, washout_confirm=True, confirm_thr=0.02, thresholds=_TH_BUY55, **_G
        ),
    ),
]

_TIERS = ("STRONG-BUY", "BUY", "HOLD", "SELL", "STRONG-SELL")


def _rank_quality(cache: dict, cfg: dict) -> float:
    """Avg over horizons of (STRONG-BUY tier fwd return − BUY tier fwd return). >0 = top tier ranks right."""
    spreads = []
    for h in HORIZONS:
        r = evaluate_horizon(cache[h], cfg)
        sb, b = r["tier_ret"].get("STRONG-BUY"), r["tier_ret"].get("BUY")
        if sb is not None and b is not None:
            spreads.append(sb - b)
    return sum(spreads) / len(spreads) if spreads else 0.0


def eval_all() -> None:
    with open(CACHE, "rb") as f:
        cache = pickle.load(f)

    spys = {h: cache[h]["spy_ret"] for h in HORIZONS}
    print("\nSPY: " + "  ".join(f"{h} {spys[h] * 100:+.1f}%" for h in HORIZONS))
    print(
        f"\n{'CONFIG':<18}"
        + "".join(f"{'α' + h:>8}" for h in HORIZONS)
        + f"{'avgα':>8}{'minα':>8}{'SB-BUY':>8}"
    )
    print("-" * 74)
    for name, cfg in CONFIGS:
        alphas = [evaluate_horizon(cache[h], cfg)["alpha"] for h in HORIZONS]
        avg = sum(alphas) / len(alphas)
        rq = _rank_quality(cache, cfg)
        cells = "".join(f"{a * 100:>+8.1f}" for a in alphas)
        print(f"{name:<18}{cells}{avg * 100:>+8.1f}{min(alphas) * 100:>+8.1f}{rq * 100:>+8.1f}")

    print(f"\nAvg fwd return by action tier — config: {CONFIGS[0][0]}")
    print(f"{'HORIZON':<8}" + "".join(f"{t:>15}" for t in _TIERS))
    for h in HORIZONS:
        r = evaluate_horizon(cache[h], CONFIGS[0][1])
        cells = ""
        for t in _TIERS:
            tr, n = r["tier_ret"].get(t), r["tier_n"].get(t, 0)
            cells += f"{tr * 100:>+10.1f}({n:>2})" if n else f"{'—':>15}"
        print(f"{h:<8}{cells}")


# ── factor analysis: which signals actually predict forward return? ──────────────


def _sub(axis: str, key: str):
    return lambda row: (row[axis].get("sub_scores") or {}).get(key)


def _axis(axis: str):
    return lambda row: row[axis]["score"]


def _ret(key: str):
    return lambda row: (row["snap"].get("returns") or {}).get(key)


# (name, extractor) — axes, key sub-scores, price momentum, and raw growth.
FACTORS = [
    ("AXIS fund_moment", _axis("fundamental_momentum")),
    ("AXIS value_qual", _axis("value_quality")),
    ("AXIS insider", _axis("insider_conviction")),
    ("AXIS price_long", _axis("price_long")),
    ("fm revenue_trend", _sub("fundamental_momentum", "revenue_trend")),
    ("fm ni_trajectory", _sub("fundamental_momentum", "ni_trajectory")),
    ("fm gm_expansion", _sub("fundamental_momentum", "gm_expansion")),
    ("fm growth_consist", _sub("fundamental_momentum", "growth_consistency")),
    ("fm estimate_rev", _sub("fundamental_momentum", "estimate_revisions")),
    ("vq profitability", _sub("value_quality", "profitability")),
    ("vq balance_sheet", _sub("value_quality", "balance_sheet")),
    ("vq margin_durab", _sub("value_quality", "margin_durability")),
    ("vq earnings_qual", _sub("value_quality", "earnings_quality")),
    ("pl fcf_yield", _sub("price_long", "fcf_yield")),
    ("pl analyst_upside", _sub("price_long", "analyst_upside")),
    ("pl valuation", _sub("price_long", "valuation")),
    ("MOM return_1m", _ret("ticker_return_1m")),
    ("MOM return_3m", _ret("ticker_return_3m")),
    ("MOM return_6m", _ret("ticker_return_6m")),
    ("MOM return_12m", _ret("ticker_return_12m")),
    ("revenue_growth", lambda row: row["snap"].get("revenue_growth")),
    ("typical_pullback", lambda row: row["snap"].get("typical_pullback_pct")),
]


def _quintile_spread(pairs: list[tuple[float, float]]) -> tuple[float, int]:
    """top-quintile avg fwd return − bottom-quintile avg fwd return (by factor value)."""
    pairs = [(v, f) for v, f in pairs if v is not None]
    n = len(pairs)
    if n < 20:
        return 0.0, n
    pairs.sort(key=lambda x: x[0])
    k = n // 5
    bot = sum(f for _, f in pairs[:k]) / k
    top = sum(f for _, f in pairs[-k:]) / k
    return top - bot, n


def factors() -> None:
    with open(CACHE, "rb") as f:
        cache = pickle.load(f)
    print("\nFactor predictiveness — top-quintile minus bottom-quintile forward return (%)")
    print("positive = higher factor -> higher forward return\n")
    print(f"{'FACTOR':<20}" + "".join(f"{h:>9}" for h in HORIZONS) + f"{'avg':>9}")
    print("-" * 58)
    rankable = []
    for name, fn in FACTORS:
        spreads = []
        for h in HORIZONS:
            fwds = [(fn(r), r["price_val"] / r["price_d"] - 1) for r in cache[h]["rows"]]
            sp, _ = _quintile_spread(fwds)
            spreads.append(sp)
        avg = sum(spreads) / len(spreads)
        rankable.append((avg, name, spreads))
        print(f"{name:<20}" + "".join(f"{s * 100:>+9.1f}" for s in spreads) + f"{avg * 100:>+9.1f}")
    print("\nRanked by |avg predictiveness|:")
    for avg, name, _ in sorted(rankable, key=lambda x: -abs(x[0])):
        print(f"  {name:<20}{avg * 100:>+7.1f}")


# ── iteration 6+: rank-based multi-factor model ─────────────────────────────────

_FN = dict(FACTORS)


def _pct_ranks(rows: list[dict], fn) -> list[float]:
    """Cross-sectional percentile rank [0,1] of a factor; missing -> 0.5 (neutral)."""
    present = sorted(
        ((i, fn(r)) for i, r in enumerate(rows) if fn(r) is not None), key=lambda x: x[1]
    )
    n = len(present)
    rank = {i: (pos / (n - 1) if n > 1 else 0.5) for pos, (i, _) in enumerate(present)}
    return [rank.get(i, 0.5) for i in range(len(rows))]


def eval_model(cache: dict, weights: dict, top_n: int, h: str) -> dict:
    rows = cache[h]["rows"]
    comp = [0.0] * len(rows)
    for fname, w in weights.items():
        ranks = _pct_ranks(rows, _FN[fname])
        for i, rk in enumerate(ranks):
            comp[i] += w * rk
    order = sorted(range(len(rows)), key=lambda i: -comp[i])[:top_n]
    fwds = [rows[i]["price_val"] / rows[i]["price_d"] - 1 for i in order]
    port = sum(fwds) / len(fwds) if fwds else 0.0
    return {"port": port, "spy": cache[h]["spy_ret"], "alpha": port - cache[h]["spy_ret"]}


# Iteration 11: TARGET RETURN 3M>=15% & 6M>=40% (absolute). Momentum is the strongest 3M+6M
# predictor -> momentum/growth-tilted + concentrated. IN-SAMPLE, high variance (see caveat).
MODELS = {
    "fcf+val": {"pl fcf_yield": 3, "pl valuation": 1},
    "fcf+mom6": {"pl fcf_yield": 3, "MOM return_6m": 2},
    "mom_fcf": {"pl fcf_yield": 2, "MOM return_6m": 2, "MOM return_3m": 1},
    "mom_growth": {
        "MOM return_6m": 2,
        "fm ni_trajectory": 2,
        "fm gm_expansion": 1,
        "pl fcf_yield": 2,
    },
    "mom_heavy": {"MOM return_6m": 3, "MOM return_3m": 2, "pl fcf_yield": 2},
    "growth_mom": {
        "fm ni_trajectory": 2,
        "fm gm_expansion": 2,
        "fm revenue_trend": 1,
        "MOM return_6m": 2,
    },
    "aggr": {
        "MOM return_6m": 3,
        "fm ni_trajectory": 2,
        "fm gm_expansion": 2,
        "pl fcf_yield": 2,
        "typical_pullback": -1,
    },
    "aggr+pengrow": {
        "MOM return_6m": 3,
        "fm ni_trajectory": 2,
        "fm gm_expansion": 2,
        "pl fcf_yield": 2,
        "revenue_growth": -1,
    },
}

TARGET = {"3M": 0.15, "6M": 0.40}  # required absolute portfolio return


def models_all(top_n: int = 15) -> None:
    with open(CACHE, "rb") as f:
        cache = pickle.load(f)
    spys = {h: cache[h]["spy_ret"] for h in HORIZONS}
    print(
        f"\nTarget-return models — top {top_n}, equal weight  (portfolio RETURN, target 3M>=15% 6M>=40%)"
    )
    print("SPY: " + "  ".join(f"{h} {spys[h] * 100:+.1f}%" for h in HORIZONS))
    print(f"\n{'MODEL':<16}" + "".join(f"{'r' + h:>8}" for h in HORIZONS) + f"{'hit?':>7}")
    print("-" * 50)
    for name, weights in MODELS.items():
        rets = {h: eval_model(cache, weights, top_n, h)["port"] for h in HORIZONS}
        hit = all(rets[h] >= TARGET[h] for h in TARGET)
        cells = "".join(f"{rets[h] * 100:>+8.1f}" for h in HORIZONS)
        print(f"{name:<16}{cells}{('YES' if hit else 'no'):>7}")


def _score_rows(rows: list[dict], weights: dict) -> list[float]:
    comp = [0.0] * len(rows)
    for fn, w in weights.items():
        for i, rk in enumerate(_pct_ranks(rows, _FN[fn])):
            comp[i] += w * rk
    return comp


def _ret(rows: list[dict], idxs: list[int]) -> float:
    return sum(rows[i]["price_val"] / rows[i]["price_d"] - 1 for i in idxs) / len(idxs) if idxs else 0.0


def _sel_equal(rows, comp, top_n):
    return sorted(range(len(rows)), key=lambda i: -comp[i])[:top_n]


def _sel_capped(rows, comp, top_n, max_sector):
    sel, cnt = [], {}
    for i in sorted(range(len(rows)), key=lambda i: -comp[i]):
        sec = rows[i].get("sector") or "?"
        if cnt.get(sec, 0) >= max_sector:
            continue
        sel.append(i)
        cnt[sec] = cnt.get(sec, 0) + 1
        if len(sel) >= top_n:
            break
    return sel


def explore(top_n: int = 10) -> None:
    """Can the target be hit WITHOUT a single-sector bet? Test sector caps, score-weighting,
    barbell (momentum + value), and exclude-top-sector."""
    with open(CACHE, "rb") as f:
        cache = pickle.load(f)
    aggr = MODELS["aggr"]
    fcfval = MODELS["fcf+val"]

    def line(name, fn):
        rets = {h: fn(h) for h in HORIZONS}
        hit = rets["3M"] >= TARGET["3M"] and rets["6M"] >= TARGET["6M"]
        cells = "".join(f"{rets[h] * 100:>+8.1f}" for h in HORIZONS)
        print(f"{name:<26}{cells}{('YES' if hit else 'no'):>6}")

    print(f"\nExploring robust ways to the target (top {top_n})  target 3M>=15% 6M>=40%")
    print(f"{'METHOD':<26}" + "".join(f"{'r' + h:>8}" for h in HORIZONS) + f"{'hit':>6}")
    print("-" * 54)

    def eq(w):
        return lambda h: _ret(cache[h]["rows"], _sel_equal(cache[h]["rows"], _score_rows(cache[h]["rows"], w), top_n))

    def cap(w, mx):
        return lambda h: _ret(cache[h]["rows"], _sel_capped(cache[h]["rows"], _score_rows(cache[h]["rows"], w), top_n, mx))

    line("aggr equal", eq(aggr))
    line("aggr cap2/sector", cap(aggr, 2))
    line("aggr cap1/sector", cap(aggr, 1))
    line("fcf+val cap2/sector", cap(fcfval, 2))

    # score-weighted position sizing
    def weighted(w):
        def f(h):
            rows = cache[h]["rows"]
            comp = _score_rows(rows, w)
            order = _sel_equal(rows, comp, top_n)
            tw = sum(comp[i] for i in order)
            return (
                sum((comp[i] / tw) * (rows[i]["price_val"] / rows[i]["price_d"] - 1) for i in order)
                if tw
                else 0.0
            )
        return f

    line("aggr score-weighted", weighted(aggr))

    # barbell: half momentum (aggr), half value (fcf+val), de-duped
    def barbell(h):
        rows = cache[h]["rows"]
        ca, cv = _score_rows(rows, aggr), _score_rows(rows, fcfval)
        half = top_n // 2
        a = _sel_equal(rows, ca, half)
        v = [i for i in sorted(range(len(rows)), key=lambda i: -cv[i]) if i not in a][: top_n - half]
        return _ret(rows, a + v)

    line("barbell aggr+fcfval", barbell)

    # exclude the single dominant sector among the picks (does the edge survive without it?)
    from collections import Counter

    def ex_top_sector(h):
        rows = cache[h]["rows"]
        comp = _score_rows(rows, aggr)
        top = _sel_equal(rows, comp, top_n)
        dom = Counter(rows[i].get("sector") or "?" for i in top).most_common(1)[0][0]
        cand = sorted(
            (i for i in range(len(rows)) if (rows[i].get("sector") or "?") != dom),
            key=lambda i: -comp[i],
        )
        return _ret(rows, cand[:top_n])

    line("aggr ex-top-sector", ex_top_sector)


def _pct_ranks_sn(rows: list[dict], fn) -> list[float]:
    """Sector-neutral percentile rank: rank each ticker's factor WITHIN its own sector, so the
    score rewards being the leader of a sector rather than being in the hottest sector."""
    from collections import defaultdict

    by_sec = defaultdict(list)
    for i, r in enumerate(rows):
        v = fn(r)
        if v is not None:
            by_sec[r.get("sector") or "?"].append((i, v))
    rank = {}
    for items in by_sec.values():
        items.sort(key=lambda x: x[1])
        n = len(items)
        for pos, (i, _) in enumerate(items):
            rank[i] = pos / (n - 1) if n > 1 else 0.5
    return [rank.get(i, 0.5) for i in range(len(rows))]


def _score_sn(rows: list[dict], weights: dict, sn_set: set) -> list[float]:
    comp = [0.0] * len(rows)
    for fn, w in weights.items():
        ranks = _pct_ranks_sn(rows, _FN[fn]) if fn in sn_set else _pct_ranks(rows, _FN[fn])
        for i, rk in enumerate(ranks):
            comp[i] += w * rk
    return comp


_MOM = {"MOM return_6m", "MOM return_3m"}


def sn(top_n: int = 10) -> None:
    """Sector-neutral scoring — diversify via the SCORE (rank factors within sector) not a cap."""
    with open(CACHE, "rb") as f:
        cache = pickle.load(f)
    spys = {h: cache[h]["spy_ret"] for h in HORIZONS}
    tests = [
        ("mom_growth global", MODELS["mom_growth"], set()),
        ("mom_growth SN-mom", MODELS["mom_growth"], _MOM),
        ("mom_growth SN-all", MODELS["mom_growth"], set(MODELS["mom_growth"])),
        ("aggr SN-mom", MODELS["aggr"], _MOM),
        ("aggr SN-all", MODELS["aggr"], set(MODELS["aggr"])),
        ("fcf+mom6 SN-mom", MODELS["fcf+mom6"], _MOM),
        ("mom_fcf SN-mom", MODELS["mom_fcf"], _MOM),
        ("mom_fcf SN-all", MODELS["mom_fcf"], set(MODELS["mom_fcf"])),
        # tuned to cross BOTH targets while sector-neutral (diversified via score, no cap)
        ("mom_fcf_g SN-mom", {"pl fcf_yield": 2, "MOM return_6m": 2, "MOM return_3m": 1, "fm ni_trajectory": 1, "fm gm_expansion": 1}, _MOM),
        ("bal_sn SN-mom", {"pl fcf_yield": 2, "MOM return_6m": 2, "fm ni_trajectory": 1, "fm gm_expansion": 1, "pl valuation": 1}, _MOM),
        ("momheavy_g SN-mom", {"MOM return_6m": 3, "MOM return_3m": 1, "fm ni_trajectory": 1, "fm gm_expansion": 1, "pl fcf_yield": 1}, _MOM),
    ]
    print(f"\nSector-neutral scoring — top {top_n} (no cap). #sec = distinct sectors in the book")
    print("SPY: " + "  ".join(f"{h} {spys[h] * 100:+.1f}%" for h in HORIZONS))
    print(f"\n{'MODEL':<20}" + "".join(f"{'r' + h:>8}" for h in HORIZONS) + f"{'#sec':>6}{'hit':>5}")
    print("-" * 60)
    for name, w, sn_set in tests:
        rets, secs = {}, []
        for h in HORIZONS:
            rows = cache[h]["rows"]
            comp = _score_sn(rows, w, sn_set)
            sel = sorted(range(len(rows)), key=lambda i: -comp[i])[:top_n]
            rets[h] = _ret(rows, sel)
            secs.append(len({rows[i].get("sector") or "?" for i in sel}))
        hit = rets["3M"] >= TARGET["3M"] and rets["6M"] >= TARGET["6M"]
        cells = "".join(f"{rets[h] * 100:>+8.1f}" for h in HORIZONS)
        print(f"{name:<20}{cells}{sum(secs) / len(secs):>6.1f}{('Y' if hit else '-'):>5}")


def frontier() -> None:
    """How high can a DIVERSIFIED book go? Scan models x sector-cap x top-N, report the ceiling."""
    with open(CACHE, "rb") as f:
        cache = pickle.load(f)
    spys = {h: cache[h]["spy_ret"] for h in HORIZONS}
    results = []
    for name, w in MODELS.items():
        comps = {h: _score_rows(cache[h]["rows"], w) for h in HORIZONS}
        for cap in (2, 3):
            for tn in (8, 10, 12, 15, 20):
                rets = {}
                for h in HORIZONS:
                    rows = cache[h]["rows"]
                    rets[h] = _ret(rows, _sel_capped(rows, comps[h], tn, cap))
                results.append((name, cap, tn, rets))

    print("\nDiversified frontier — sector cap limits names/sector. target 3M>=15% 6M>=40%")
    print("SPY: " + "  ".join(f"{h} {spys[h] * 100:+.1f}%" for h in HORIZONS))
    hdr = f"{'MODEL':<14}{'cap':>4}{'N':>4}" + "".join(f"{'r' + h:>8}" for h in HORIZONS) + f"{'hit':>5}"

    print("\n>> Top 12 by 6M return (diversified):")
    print(hdr)
    for name, cap, tn, rets in sorted(results, key=lambda x: -x[3]["6M"])[:12]:
        hit = rets["3M"] >= TARGET["3M"] and rets["6M"] >= TARGET["6M"]
        print(f"{name:<14}{cap:>4}{tn:>4}" + "".join(f"{rets[h] * 100:>+8.1f}" for h in HORIZONS) + f"{('Y' if hit else '-'):>5}")

    print("\n>> Top 8 by 3M return (diversified):")
    print(hdr)
    for name, cap, tn, rets in sorted(results, key=lambda x: -x[3]["3M"])[:8]:
        hit = rets["3M"] >= TARGET["3M"] and rets["6M"] >= TARGET["6M"]
        print(f"{name:<14}{cap:>4}{tn:>4}" + "".join(f"{rets[h] * 100:>+8.1f}" for h in HORIZONS) + f"{('Y' if hit else '-'):>5}")

    print("\n>> Best that hits BOTH targets while diversified (if any):")
    both = [r for r in results if r[3]["3M"] >= TARGET["3M"] and r[3]["6M"] >= TARGET["6M"]]
    if not both:
        print("  none — no diversified config hits both 3M>=15% and 6M>=40%")
    else:
        for name, cap, tn, rets in sorted(both, key=lambda x: -x[3]["6M"])[:8]:
            print(f"{name:<14}{cap:>4}{tn:>4}" + "".join(f"{rets[h] * 100:>+8.1f}" for h in HORIZONS))


def show_picks(model: str = "fcf+val", top_n: int = 15) -> None:
    with open(CACHE, "rb") as f:
        cache = pickle.load(f)
    weights = MODELS[model]
    print(f"\nPicks — model '{model}', top {top_n} per horizon")
    for h in HORIZONS:
        rows = cache[h]["rows"]
        comp = [0.0] * len(rows)
        for fname, w in weights.items():
            for i, rk in enumerate(_pct_ranks(rows, _FN[fname])):
                comp[i] += w * rk
        order = sorted(range(len(rows)), key=lambda i: -comp[i])[:top_n]
        names = [
            f"{rows[i]['ticker']}({(rows[i]['price_val'] / rows[i]['price_d'] - 1) * 100:+.0f}%)"
            for i in order
        ]
        print(f"  {h}: " + " ".join(names))


# ── iteration 9+: simplified composite (blend of the predictive SUB-scores) ─────
# Keeps each sub-score's existing definition; drops the noise sub-scores; reweights toward
# fcf_yield + valuation. spec = list of (axis, sub_key, weight); normalized by available max_pts.


def _simple_composite(row: dict, spec: list) -> float | None:
    num = den = 0.0
    for axis, key, w in spec:
        subs = row[axis].get("sub_scores") or {}
        mx = (row[axis].get("max_pts") or {}).get(key)
        v = subs.get(key)
        if v is not None and mx:
            num += w * (v / mx)
            den += w
    return 100 * num / den if den else None


SIMPLE = {
    "sv (fcf+val)": [("price_long", "fcf_yield", 3), ("price_long", "valuation", 2)],
    "sv+nitraj": [
        ("price_long", "fcf_yield", 3),
        ("price_long", "valuation", 2),
        ("fundamental_momentum", "ni_trajectory", 1),
    ],
    "sv+revtrend": [
        ("price_long", "fcf_yield", 3),
        ("price_long", "valuation", 2),
        ("fundamental_momentum", "revenue_trend", 1),
    ],
    "sv+gm": [
        ("price_long", "fcf_yield", 3),
        ("price_long", "valuation", 2),
        ("fundamental_momentum", "gm_expansion", 1),
    ],
    "sv+prof": [
        ("price_long", "fcf_yield", 3),
        ("price_long", "valuation", 2),
        ("value_quality", "profitability", 1),
    ],
    "sv+traj+gm": [
        ("price_long", "fcf_yield", 3),
        ("price_long", "valuation", 2),
        ("fundamental_momentum", "ni_trajectory", 1),
        ("fundamental_momentum", "gm_expansion", 1),
    ],
    "diversified": [
        ("price_long", "fcf_yield", 2),
        ("price_long", "valuation", 1.5),
        ("fundamental_momentum", "ni_trajectory", 1),
        ("fundamental_momentum", "revenue_trend", 1),
        ("fundamental_momentum", "gm_expansion", 1),
        ("value_quality", "profitability", 1),
    ],
    "fcf_heavy": [
        ("price_long", "fcf_yield", 5),
        ("price_long", "valuation", 2),
        ("fundamental_momentum", "ni_trajectory", 1),
    ],
    # implementation candidates: fcf+val dominant, light fundamental tail for regime robustness
    "impl_A": [
        ("price_long", "fcf_yield", 4),
        ("price_long", "valuation", 3),
        ("fundamental_momentum", "ni_trajectory", 1),
        ("fundamental_momentum", "gm_expansion", 1),
        ("value_quality", "profitability", 1),
    ],
    "impl_B": [
        ("price_long", "fcf_yield", 5),
        ("price_long", "valuation", 3),
        ("fundamental_momentum", "ni_trajectory", 1),
        ("value_quality", "profitability", 1),
    ],
}


def simple_all(top_n: int = 15) -> None:
    with open(CACHE, "rb") as f:
        cache = pickle.load(f)
    spys = {h: cache[h]["spy_ret"] for h in HORIZONS}
    print(f"\nSimplified composite (sub-score blend) — top {top_n} by score, equal weight")
    print("SPY: " + "  ".join(f"{h} {spys[h] * 100:+.1f}%" for h in HORIZONS))
    print(
        f"\n{'COMPOSITE':<16}"
        + "".join(f"{'α' + h:>8}" for h in HORIZONS)
        + f"{'avgα':>8}{'minα':>8}{'qspr':>8}"
    )
    print("-" * 64)
    for name, spec in SIMPLE.items():
        alphas, spreads = [], []
        for h in HORIZONS:
            rows = cache[h]["rows"]
            scored = [(_simple_composite(r, spec), r) for r in rows]
            scored = [(s, r) for s, r in scored if s is not None]
            scored.sort(key=lambda x: -x[0])
            sel = scored[:top_n]
            port = sum(r["price_val"] / r["price_d"] - 1 for _, r in sel) / len(sel) if sel else 0.0
            alphas.append(port - cache[h]["spy_ret"])
            sp, _ = _quintile_spread([(s, r["price_val"] / r["price_d"] - 1) for s, r in scored])
            spreads.append(sp)
        avg = sum(alphas) / len(alphas)
        qspr = sum(spreads) / len(spreads)
        print(
            f"{name:<16}"
            + "".join(f"{a * 100:>+8.1f}" for a in alphas)
            + f"{avg * 100:>+8.1f}{min(alphas) * 100:>+8.1f}{qspr * 100:>+8.1f}"
        )


def _value_signal(price_long: dict) -> float | None:
    """0..1 value signal from price_long's fcf_yield(3) + valuation(2) sub-scores."""
    subs = price_long.get("sub_scores") or {}
    mx = price_long.get("max_pts") or {}
    num = den = 0.0
    for k, w in (("fcf_yield", 3), ("valuation", 2)):
        v, m = subs.get(k), mx.get(k)
        if v is not None and m:
            num += w * (v / m)
            den += w
    return num / den if den else None


def _blend_composite(row: dict, wv: float, wf: float, wq: float) -> float | None:
    val = _value_signal(row["price_long"])
    fm = row["fundamental_momentum"]["score"]
    vq = row["value_quality"]["score"]
    parts = []
    if val is not None:
        parts.append((wv, val * 100))
    if fm is not None:
        parts.append((wf, fm))
    if vq is not None:
        parts.append((wq, vq))
    tw = sum(w for w, _ in parts)
    if not tw:
        return None
    score = sum(w * s for w, s in parts) / tw
    rg = row["snap"].get("revenue_growth")
    if rg is not None and rg < 0:
        score = min(score, 79.9)
    return round(score, 1)


_BLENDS = {
    "val55/fm25/vq20": (0.55, 0.25, 0.20),
    "val60/fm25/vq15": (0.60, 0.25, 0.15),
    "val50/fm30/vq20": (0.50, 0.30, 0.20),
    "val70/fm20/vq10": (0.70, 0.20, 0.10),
    "val45/fm30/vq25": (0.45, 0.30, 0.25),
    "val100 (pure)": (1.0, 0.0, 0.0),
}


def blend_all(top_n: int = 15) -> None:
    with open(CACHE, "rb") as f:
        cache = pickle.load(f)
    spys = {h: cache[h]["spy_ret"] for h in HORIZONS}
    print(f"\nAxis-blend composite (value_signal + fm + vq) — top {top_n} + tier monotonicity")
    print("SPY: " + "  ".join(f"{h} {spys[h] * 100:+.1f}%" for h in HORIZONS))
    print(
        f"\n{'BLEND':<18}"
        + "".join(f"{'α' + h:>8}" for h in HORIZONS)
        + f"{'avgα':>8}{'minα':>8}{'qspr':>8}"
    )
    print("-" * 66)
    for name, (wv, wf, wq) in _BLENDS.items():
        alphas, spreads = [], []
        for h in HORIZONS:
            rows = cache[h]["rows"]
            scored = [(_blend_composite(r, wv, wf, wq), r) for r in rows]
            scored = [(s, r) for s, r in scored if s is not None]
            scored.sort(key=lambda x: -x[0])
            sel = scored[:top_n]
            port = sum(r["price_val"] / r["price_d"] - 1 for _, r in sel) / len(sel) if sel else 0.0
            alphas.append(port - cache[h]["spy_ret"])
            sp, _ = _quintile_spread([(s, r["price_val"] / r["price_d"] - 1) for s, r in scored])
            spreads.append(sp)
        avg = sum(alphas) / len(alphas)
        print(
            f"{name:<18}"
            + "".join(f"{a * 100:>+8.1f}" for a in alphas)
            + f"{avg * 100:>+8.1f}{min(alphas) * 100:>+8.1f}{sum(spreads) / 3 * 100:>+8.1f}"
        )


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "eval"
    if mode == "build":
        asyncio.run(build())
    elif mode == "factors":
        factors()
    elif mode == "simple":
        simple_all(int(sys.argv[2]) if len(sys.argv) > 2 else 15)
    elif mode == "blend":
        blend_all(int(sys.argv[2]) if len(sys.argv) > 2 else 15)
    elif mode == "model":
        models_all(int(sys.argv[2]) if len(sys.argv) > 2 else 15)
    elif mode == "picks":
        show_picks()
    elif mode == "explore":
        explore(int(sys.argv[2]) if len(sys.argv) > 2 else 10)
    elif mode == "frontier":
        frontier()
    elif mode == "sn":
        sn(int(sys.argv[2]) if len(sys.argv) > 2 else 10)
    else:
        eval_all()
