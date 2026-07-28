from __future__ import annotations

from datetime import UTC, datetime

from core.insider_score import compute_insider_score, normalize

from .base import all_annual, clamp
from .fundamental_momentum import score as fm_score
from .price_long import score as pl_score
from .value_quality import score as vq_score

# insider_conviction now returns None (not a neutral 50) when there's no real signal, so its
# weight only bites when there IS conviction data — which makes it worth more than the old 10%
# it got as a permanent drag-to-middle. Quality gives up 5 pts for it: 40/45/15.
_QUALITY_WEIGHTS_LONG = {
    "fundamental_momentum": 0.40,
    "value_quality": 0.45,
    "insider_conviction": 0.15,
}

_THRESHOLDS = [
    (80, "STRONG-BUY"),
    (60, "BUY"),
    (40, "HOLD"),
    (20, "SELL"),
    (0, "STRONG-SELL"),
]


def _insider(snapshot: dict, as_of: datetime | None = None) -> dict:
    txs = snapshot.get("insider_transactions", [])
    mc = snapshot.get("market_cap")
    w52l = snapshot.get("week52_low")
    w52h = snapshot.get("week52_high")

    if not txs:
        return {"score": None, "sub_scores": {}}

    result = compute_insider_score(
        normalize(txs),
        market_cap=mc,
        week52_low=w52l,
        week52_high=w52h,
        days_back=365,
        _already_normalized=True,
        earnings_dates=snapshot.get("earnings_dates"),
        as_of=as_of,
    )

    # No transactions survive the value/role/routine filters → no signal, not "neutral".
    # Return None so it drops out of the weighted composite instead of dragging every
    # score toward 50 purely for lack of insider data.
    if result.get("valid_buys", 0) + result.get("valid_sells", 0) == 0:
        return {"score": None, "sub_scores": result}

    return {"score": result["score"], "sub_scores": result}


def _action(score: float) -> str:
    return next(label for threshold, label in _THRESHOLDS if score >= threshold)


def _quality_score(base: dict) -> float | None:
    weights = _QUALITY_WEIGHTS_LONG
    available = {k: base[k] for k in weights if base[k]["score"] is not None}
    total_w = sum(weights[k] for k in available)
    if not available or not total_w:
        return None
    return sum(v["score"] * weights[k] / total_w for k, v in available.items())


_PRICE_BOOST_MAX = 6.0
_DIP_BONUS_MAX = 10.0
_DIP_REF_DROP = 0.11  # beta-adjusted drop (at beta=1) that earns the full dip bonus


def _dip_bonus(snapshot: dict) -> float:
    # A fundamentally strong stock selling off hard is a buying opportunity, not a red
    # flag — but "hard" is relative to the stock's own volatility: a low-beta name
    # dropping 5% in a day is as notable as a high-beta name dropping ~20% in a week.
    # Day-drop is weighted up (x2.2) since an equal % move in a single day is rarer
    # than over a week; whichever timeframe shows the bigger relative move wins.
    day_pct = snapshot.get("day_change_pct")
    week_ret = (snapshot.get("returns") or {}).get("ticker_return_1w")
    day_drop = max(-(day_pct / 100), 0.0) if day_pct is not None else 0.0
    week_drop = max(-week_ret, 0.0) if week_ret is not None else 0.0
    effective_drop = max(day_drop * 2.2, week_drop)
    if effective_drop <= 0:
        return 0.0
    beta = max(snapshot.get("beta") or 1.0, 0.5)
    return round(clamp(effective_drop / beta / _DIP_REF_DROP, 0, 1) * _DIP_BONUS_MAX, 1)


def _composite_long(base: dict, price_long: dict, snapshot: dict) -> dict:
    # Long ranks businesses by quality (fm/vq/insiders) first — price and recent dips are
    # bounded modifiers on top, never enough to let a mediocre "statistically cheap" business
    # (often driven by optimistic analyst targets) outrank a genuinely better one. A cheap
    # price or a beta-adjusted dip can still tip a good-not-great business into STRONG-BUY,
    # but neither can rescue a bad business — that only happens by raising quality itself.
    weights_pct = {k: round(v * 100) for k, v in _QUALITY_WEIGHTS_LONG.items()}
    quality = _quality_score(base)
    if quality is None:
        return {"score": None, "action": "N/A", "weights": weights_pct}

    pl = price_long["score"]
    price_attractive = clamp((pl - 50) / 50, 0, 1) if pl is not None else 0.0
    dip_bonus = _dip_bonus(snapshot)

    score = round(clamp(quality + price_attractive * _PRICE_BOOST_MAX + dip_bonus, 0, 100), 1)

    # Trailing profitability/balance-sheet strength describes where a business has been,
    # not where it's going — a business with genuinely shrinking revenue shouldn't reach
    # STRONG-BUY on quality alone, no matter how clean its margins or balance sheet are.
    rev_g = snapshot.get("revenue_growth")
    if rev_g is not None and rev_g < 0:
        score = min(score, 79.9)

    return {"score": score, "action": _action(score), "weights": weights_pct}


# buy_target answers: buy now, or wait for a dip to $X? Two anchors, one shared volatility discount.
# Anchor: with ≥_BT_MIN_ANALYSTS covering it, the ~10th percentile of the analyst price-target
# distribution (interpolated LOW→MEDIAN) — a conservative, outlier-robust level grounded in forward
# fundamentals rather than a single 52-week-high print (which a momentum name's bubble peak makes
# meaningless — SNDK ran 40→2354 in a year, so 80% of its high = $1888 was a nonsense "buy" above the
# current price). With thin/absent coverage (~23% of names) it falls back to the −30%-off-52w-high
# zone, an out-of-sample-validated mean-reversion entry (entry_lab.py: the deeper the trigger the
# stronger the rebound — −30% off the high gave ~+19pp/6m vs ~+10pp for −20%, at 30% vs 43% coverage).
# Either anchor is then discounted by a margin of safety keyed to how much the name moves
# (realized_vol = the average of its 1m/6m/12m annualized realized vol, so a recent-only or year-long
# spike alone can't dominate), in three discrete tiers — low/mid/high vol → 0/12/25% extra discount. A calm name
# (AAPL ~25%) buys at the raw anchor; a wild one (SNDK ~110%) needs a 25%-deeper entry. Tried and
# dropped: an analyst-count weighting (arbitrary; the percentile encodes conservatism directly) and a
# momentum widener (double-counts with vol on the bubble names — bt_lab). NOT return-validated (analyst
# targets aren't in a price-only backtest) — behavior-tuned; the knobs below are hand-picked.
_BUY_TARGET_DEEP_DD = -0.30  # fallback drawdown from the 52w high when analyst targets aren't trusted
_BT_MIN_ANALYSTS = 10  # below this, the target distribution is too thin to build a percentile from
_BT_PERCENTILE = 0.10  # target the ~p10 of the analyst distribution: low + (p/0.5)*(median − low)
_BT_VOL_MID = 0.40  # realized vol ≥ this → "mid" tier; below → "low"
_BT_VOL_HIGH = 0.75  # realized vol ≥ this → "high" tier
_BT_VOL_MOS = {"low": 0.0, "mid": 0.12, "high": 0.25}  # extra margin of safety per volatility tier


def _vol_tier(vol: float | None) -> tuple[str, float]:
    """Discrete volatility level + its margin-of-safety discount. Unmeasurable vol (too little price
    history — a freshly-listed name) is NOT low vol: assume high risk and demand the full discount."""
    if vol is None:
        return "n/a", _BT_VOL_MOS["high"]
    if vol >= _BT_VOL_HIGH:
        return "high", _BT_VOL_MOS["high"]
    if vol >= _BT_VOL_MID:
        return "mid", _BT_VOL_MOS["mid"]
    return "low", _BT_VOL_MOS["low"]


def _buy_target(snapshot: dict) -> dict | None:
    price = snapshot.get("price")
    if not price:
        return None

    vol = snapshot.get("realized_vol")
    vol_level, mos = _vol_tier(vol)

    low = snapshot.get("target_low")
    p50 = snapshot.get("target_median") or snapshot.get("target_mean")  # true p50, mean as a fallback
    nac = int(snapshot.get("analyst_count") or 0)
    if nac >= _BT_MIN_ANALYSTS and low and low > 0 and p50 and p50 > 0:
        anchor = low + (_BT_PERCENTILE / 0.5) * (p50 - low)  # interpolate the low percentile p0→p50
        detail = {"method": "p10", "analysts": nac, "low": round(low, 2), "p50": round(p50, 2)}
    else:
        w52h = snapshot.get("week52_high")
        if not w52h or w52h <= 0:
            return None
        anchor = w52h * (1 + _BUY_TARGET_DEEP_DD)
        detail = {"method": "drawdown", "analysts": nac, "week52_high": round(w52h, 2), "dd": _BUY_TARGET_DEEP_DD}

    target = anchor * (1 - mos)  # same volatility discount on either anchor
    vw = snapshot.get("realized_vol_windows") or {}
    detail.update({
        "anchor": round(anchor, 2),
        "vol": round(vol, 4) if vol else None,  # average of the windows — drives the tier
        "vol_windows": {k: round(v, 4) for k, v in vw.items()},
        "vol_level": vol_level,
        "vol_mid": _BT_VOL_MID,
        "vol_high": _BT_VOL_HIGH,
        "mos": round(mos, 4),
    })

    return {
        "price": round(target, 2),
        "pct_from_current": round(target / price - 1, 4),
        "signal": "buy" if price <= target else "wait",
        **detail,
    }


_CATEGORY_LABELS = {
    "fundamental_momentum": "Growth",
    "value_quality": "Quality",
    "insider_conviction": "Insiders",
    "price_long": "Sentiment",
}

_MOVER_MIN_DELTA = 0.05


def diff_scores(old: dict | None, new: dict | None) -> dict | None:
    """Compare two compute_all() outputs for the same ticker and surface what moved.

    Used to show "score change since last refresh" — old/new must come from the
    same snapshot shape (compute_all's return), not partial/derived data.
    """
    if not old or not new:
        return None
    old_score = old.get("composite_long", {}).get("score")
    new_score = new.get("composite_long", {}).get("score")
    if old_score is None or new_score is None:
        return None

    categories: dict[str, dict] = {}
    movers: list[dict] = []
    for key, label in _CATEGORY_LABELS.items():
        o, n = old.get(key, {}), new.get(key, {})
        os_, ns_ = o.get("score"), n.get("score")
        if os_ is None or ns_ is None:
            continue
        categories[key] = {"label": label, "old": os_, "new": ns_, "delta": round(ns_ - os_, 1)}

        if key == "insider_conviction":
            continue  # sub_scores here are counts (valid_buys/valid_sells), not comparable point deltas
        o_sub, n_sub = o.get("sub_scores", {}), n.get("sub_scores", {})
        for sub_key, nv in n_sub.items():
            ov = o_sub.get(sub_key)
            if ov is None or nv is None:
                continue
            sub_delta = round(nv - ov, 2)
            if abs(sub_delta) < _MOVER_MIN_DELTA:
                continue
            movers.append({"category": label, "key": sub_key, "delta": sub_delta})

    movers.sort(key=lambda m: -abs(m["delta"]))
    return {
        "composite": {"old": old_score, "new": new_score, "delta": round(new_score - old_score, 1)},
        "categories": categories,
        "movers": movers[:5],
    }


# Risk flags — surfaced next to the verdict so silent logic (the revenue cap) and timing
# hazards (earnings, bad quote, rich price) become visible decision inputs, not surprises.
_EARNINGS_SOON_DAYS = 7


def _days_to_earnings(dates: list | None, as_of: datetime | None = None) -> int | None:
    if not dates:
        return None
    today = as_of.date() if as_of is not None else datetime.now(UTC).date()
    future = []
    for ds in dates:
        try:
            dt = datetime.strptime(str(ds)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if dt >= today:
            future.append((dt - today).days)
    return min(future) if future else None


def _is_cyclical_surge(fundamentals: list[dict], snapshot: dict) -> bool:
    """A big revenue surge coming off a prior down-year is a cyclical recovery, not durable
    growth — the classic memory/semis trap where a name looks best right at the cycle peak.
    A secular grower never declines YoY; a cyclical oscillates. So: surging now AND a real
    (>10%) down-year somewhere in the annual history → treat the growth read with suspicion."""
    rev_g = snapshot.get("revenue_growth")
    if rev_g is None or rev_g < 0.40:
        return False
    revs = [a["revenue"] for a in all_annual(fundamentals) if a.get("revenue") is not None]
    if len(revs) < 3:
        return False
    chron = revs[::-1]  # oldest → newest
    latest = chron[-1]
    if latest <= 0:
        return False
    # A real cycle oscillates around a comparable level: an EARLIER year that peaked at
    # ≥50% of today's revenue, then a LATER year fell >10% below it. This excludes early-
    # stage noise / a one-off reset (NBIS post-divestiture) where the prior "peak" is
    # immaterial vs. today — that's not a cycle, just a small base or a corporate action.
    for i in range(len(chron) - 1):
        peak = chron[i]
        if peak >= 0.50 * latest and any(chron[j] < peak * 0.90 for j in range(i + 1, len(chron))):
            return True
    return False


_EXPENSIVE_FWD_PE = 30.0  # profitable: forward P/E above this AND ...
_EXPENSIVE_ADJ_PS = 8.0  # ... growth-adjusted P/S above this → expensive (needs BOTH)
_EXPENSIVE_PREPROFIT_PS = 20.0  # pre-profit: raw P/S above this is the expensive tell


def _is_expensive(snapshot: dict) -> bool:
    """Rich valuation — but confirmed on TWO independent bases so single-metric artifacts don't misfire:
    a high P/E from *depressed* earnings (high PE, ordinary sales multiple) and a high P/S from *fat
    margins* (rich sales, ordinary PE) each fail the AND. Profitable names must be rich on both forward
    earnings AND growth-adjusted sales; pre-profit names have no earnings anchor, so a high RAW sales
    multiple is the tell (the growth-adjustment is unreliable off a near-zero revenue base). Deliberately
    NOT derived from price_long's `valuation` sub-score — that mixes in earnings-trend momentum, so it
    flagged cheap-but-decelerating names (NVO at 15.6x PE) and missed expensive-but-growing ones (TSLA)."""
    fwd = snapshot.get("forward_pe")
    ps = snapshot.get("price_to_sales")
    if ps is None:
        return False
    if fwd is not None and fwd > 0:
        rg = snapshot.get("revenue_growth")
        adj_ps = ps / (1 + rg) if (rg is not None and rg > -1) else ps
        return fwd > _EXPENSIVE_FWD_PE and adj_ps > _EXPENSIVE_ADJ_PS
    return ps > _EXPENSIVE_PREPROFIT_PS


def _risk_flags(
    fundamentals: list[dict], snapshot: dict, as_of: datetime | None = None
) -> list[dict]:
    flags: list[dict] = []
    rev_g = snapshot.get("revenue_growth")
    if rev_g is not None and rev_g < 0:
        flags.append(
            {
                "key": "rev",
                "label": "REV↓",
                "title": f"Revenue shrinking ({rev_g:+.0%} YoY) — score capped below STRONG-BUY",
            }
        )

    if _is_cyclical_surge(fundamentals, snapshot):
        flags.append(
            {
                "key": "cyclical",
                "label": "CYCLICAL",
                "title": f"Revenue +{rev_g:.0%} off a prior down-year — likely a cycle peak, "
                "not durable growth (Growth score may be inflated)",
            }
        )

    days = _days_to_earnings(snapshot.get("earnings_dates"), as_of)
    if days is not None and days <= _EARNINGS_SOON_DAYS:
        flags.append(
            {
                "key": "earnings",
                "label": "E today" if days == 0 else f"E-{days}d",
                "title": ("Earnings today" if days == 0 else f"Earnings in ~{days} day(s)")
                + " — event risk before any entry",
            }
        )

    if _is_expensive(snapshot):
        flags.append(
            {
                "key": "expensive",
                "label": "$$$",
                "title": "Rich valuation — expensive on both forward earnings and sales",
            }
        )

    if snapshot.get("price_suspect"):
        flags.append(
            {
                "key": "price",
                "label": "PRICE?",
                "title": "Quote deviates >50% from prior close — data may be wrong",
            }
        )
    return flags


def compute_all(fundamentals: list[dict], snapshot: dict, as_of: datetime | None = None) -> dict:
    base = {
        "fundamental_momentum": fm_score(fundamentals, snapshot),
        "value_quality": vq_score(fundamentals, snapshot),
        "insider_conviction": _insider(snapshot, as_of),
    }
    price_long = pl_score(fundamentals, snapshot)

    return {
        **base,
        "price_long": price_long,
        "composite_long": _composite_long(base, price_long, snapshot),
        "buy_target": _buy_target(snapshot),
        "flags": _risk_flags(fundamentals, snapshot, as_of),
    }
