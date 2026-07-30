from __future__ import annotations

from .base import analyst_upside_pts, clamp, currency_mismatch, finalize_score

_UPSIDE_BONUS_MAX = 8.0


def score(fundamentals: list[dict], snapshot: dict) -> dict:
    sub: dict[str, float | None] = {}
    # Valuation is the ONLY weighted sub-score; analyst_upside is an additive-only bonus (below).
    max_pts: dict[str, float] = {"valuation": 35.0}

    # This axis (user-facing label "Valuation") measures how cheap the stock is — the LEVEL of the
    # multiples the market pays. It is NOT market sentiment: across the real watchlist the sell-side
    # ratings (analyst_conviction) were a near-constant ~9 (herd, almost never "sell") and offered no
    # discrimination, so that sub-score was dropped. FCF yield lived here too and was removed earlier
    # (hard cash, not valuation; double-counted cheapness here and cash in value_quality's cash_runway).
    fx_mismatch = currency_mismatch(snapshot)

    # Valuation reasonableness (0-35, the primary signal) — how cheap the multiples are (the LEVEL, not the earnings
    #    trend): absolute forward P/E, PEG, growth-adj P/S. The old first term scored the fwd-vs-trailing
    #    P/E ratio, which rewards earnings GROWTH, not cheapness — a 40x name growing into it beat a 10x
    #    flat one. That's a trajectory signal leaking into the valuation axis (growth lives only in
    #    fundamental_momentum), and it made a cheap-but-decelerating name (NVO ~15x) score 0 here.
    fwd_pe = snapshot.get("forward_pe")
    peg = snapshot.get("peg_ratio")
    ps = snapshot.get("price_to_sales")
    rev_g = snapshot.get("revenue_growth")
    pts, avail = 0.0, 0.0
    if fwd_pe and fwd_pe > 0:
        pts += (
            12
            if fwd_pe < 15
            else (9 if fwd_pe < 22 else (6 if fwd_pe < 30 else (3 if fwd_pe < 40 else 0)))
        )
        avail += 12
    if peg is not None and peg > 0:
        pts += 8 if peg < 1.0 else (5 if peg < 1.5 else (2 if peg < 2.5 else 0))
        avail += 8
    if ps is not None and rev_g is not None and not fx_mismatch:
        adj_ps = ps / (1 + rev_g) if rev_g > -1 else ps
        pts += 6 if adj_ps < 2 else (4 if adj_ps < 5 else (2 if adj_ps < 10 else 0))
        avail += 6
    # Normalize by the max achievable from the metrics present (not the fixed all-three
    # max), consistent with finalize_score's available-coverage convention.
    sub["valuation"] = round(clamp(pts / avail * 35, 0, 35), 1) if avail else None

    # Analyst upside — additive-only bonus (0-12), never defines the axis. Sell-side targets skew
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

    result = finalize_score(sub, max_pts, bonus=upside_bonus or 0.0)
    result["sub_scores"]["analyst_upside"] = upside_bonus
    result["max_pts"]["analyst_upside"] = _UPSIDE_BONUS_MAX
    return result
