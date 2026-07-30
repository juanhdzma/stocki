from __future__ import annotations

from .base import analyst_upside_pts, clamp, currency_mismatch, finalize_score

_UPSIDE_BONUS_MAX = 8.0


def score(fundamentals: list[dict], snapshot: dict) -> dict:
    sub: dict[str, float | None] = {}
    # The three valuation multiples are weighted sub-scores; analyst_upside is an additive-only bonus
    # (below). Each metric is exposed separately (rather than blended into one "valuation" bar) so the
    # axis breaks out like every other one — the frontend can show Forward P/E / PEG / P/S individually.
    max_pts: dict[str, float] = {"fwd_pe": 12.0, "peg": 8.0, "growth_adj_ps": 6.0}

    # This axis (user-facing label "Valuation") measures how cheap the stock is — the LEVEL of the
    # multiples the market pays. It is NOT market sentiment: across the real watchlist the sell-side
    # ratings (analyst_conviction) were a near-constant ~9 (herd, almost never "sell") and offered no
    # discrimination, so that sub-score was dropped. FCF yield lived here too and was removed earlier
    # (hard cash, not valuation; double-counted cheapness here and cash in value_quality's cash_runway).
    # Each multiple scores the cheapness of its LEVEL, not any earnings trend — the old first term scored
    # the fwd-vs-trailing P/E ratio, which rewards earnings GROWTH not cheapness (a 40x name growing into
    # it beat a flat 10x one), leaking a trajectory signal into the valuation axis (growth lives only in
    # fundamental_momentum) and scoring a cheap-but-decelerating name (NVO ~15x) at 0.
    fx_mismatch = currency_mismatch(snapshot)

    fwd_pe = snapshot.get("forward_pe")
    peg = snapshot.get("peg_ratio")
    ps = snapshot.get("price_to_sales")
    rev_g = snapshot.get("revenue_growth")

    if fwd_pe and fwd_pe > 0:
        sub["fwd_pe"] = (
            12.0
            if fwd_pe < 15
            else (9.0 if fwd_pe < 22 else (6.0 if fwd_pe < 30 else (3.0 if fwd_pe < 40 else 0.0)))
        )
    else:
        sub["fwd_pe"] = None

    if peg is not None and peg > 0:
        sub["peg"] = 8.0 if peg < 1.0 else (5.0 if peg < 1.5 else (2.0 if peg < 2.5 else 0.0))
    else:
        sub["peg"] = None

    if ps is not None and rev_g is not None and not fx_mismatch:
        adj_ps = ps / (1 + rev_g) if rev_g > -1 else ps
        sub["growth_adj_ps"] = (
            6.0 if adj_ps < 2 else (4.0 if adj_ps < 5 else (2.0 if adj_ps < 10 else 0.0))
        )
    else:
        sub["growth_adj_ps"] = None

    # Analyst upside — additive-only bonus (0-8), never defines the axis. Sell-side targets skew
    # bullish, herd, and saturate for high-upside names, so on their own they're hope, not cheapness:
    # they can only LIFT a measured valuation, never manufacture one. A name with no valuation data
    # (pre-profit, no usable multiple) has no base -> excluded, instead of scoring a perfect 100 off
    # analyst optimism alone; a wildly overvalued name (valuation ~0) can't be floored high by it.
    price = snapshot.get("price")
    target_mean = snapshot.get("target_mean")
    analyst_cnt = snapshot.get("analyst_count") or 0
    up = analyst_upside_pts(price, target_mean, _UPSIDE_BONUS_MAX)
    if up is not None:
        cov_adj = clamp(analyst_cnt / 10, 0.3, 1.0) if analyst_cnt else 0.5
        upside_bonus = round(up * cov_adj, 1)
    else:
        upside_bonus = None

    # min_coverage 0.2: a single present multiple (e.g. growth_adj_ps alone, 6/26=0.23) still scores,
    # preserving the old single-blended-sub-score behaviour where any one metric qualified the axis.
    result = finalize_score(sub, max_pts, min_coverage=0.2, bonus=upside_bonus or 0.0)
    result["sub_scores"]["analyst_upside"] = upside_bonus
    result["max_pts"]["analyst_upside"] = _UPSIDE_BONUS_MAX
    return result
