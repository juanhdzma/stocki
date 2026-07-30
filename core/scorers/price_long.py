from __future__ import annotations

from .base import analyst_upside_pts, clamp, currency_mismatch, finalize_score

_UPSIDE_BONUS_MAX = 8.0


def score(fundamentals: list[dict], snapshot: dict) -> dict:
    sub: dict[str, float | None] = {}
    # The four valuation multiples are weighted sub-scores; analyst_upside is an additive-only bonus
    # (below). Each metric is exposed separately (rather than blended into one "valuation" bar) so the
    # axis breaks out like every other one — the frontend shows each multiple individually.
    max_pts: dict[str, float] = {
        "fwd_pe": 12.0,
        "ev_ebitda": 10.0,
        "peg": 8.0,
        "growth_adj_ps": 6.0,
        "ev_sales": 6.0,
    }

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

    # EV/EBITDA — robust to depressed/negative net earnings and capital structure (EBITDA excludes
    # interest, taxes, D&A), so it values cyclically-depressed names (e.g. BA) that P/E alone misreads
    # as expensive. None on negative EBITDA (multiple not meaningful), same as a negative P/E.
    # Tiers calibrated to the actual universe (growth/tech-heavy: median EV/EBITDA ~27, p25 ~16, p75
    # ~43), NOT a textbook ~12-fair anchor — the latter dumped ~60% of names at 0, making the metric a
    # near-constant that just deflated everything (the same non-discriminating failure that killed
    # analyst_conviction). These place the watchlist median near the neutral tier so it actually spreads.
    ev_ebitda = snapshot.get("ev_to_ebitda")
    if ev_ebitda is not None and ev_ebitda > 0:
        sub["ev_ebitda"] = (
            10.0
            if ev_ebitda < 15
            else (
                7.0
                if ev_ebitda < 22
                else (5.0 if ev_ebitda < 30 else (2.0 if ev_ebitda < 42 else 0.0))
            )
        )
    else:
        sub["ev_ebitda"] = None

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

    # EV/Sales — the sales multiple that DOES apply to pre-profit names (no earnings/EBITDA needed),
    # so it gives the speculative tail a real valuation signal instead of leaving every earnings-based
    # bar null. EV (not price) accounts for debt/cash. Growth-adjusted like P/S; falls back to the raw
    # ratio when revenue_growth is absent, and mixing EV (price ccy) with local revenue is invalid so
    # it's skipped on currency mismatch. Same tiers as growth_adj_ps — same metric kind, kept consistent.
    ev_sales = snapshot.get("ev_to_revenue")
    if ev_sales is not None and ev_sales > 0 and not fx_mismatch:
        adj_evs = ev_sales / (1 + rev_g) if (rev_g is not None and rev_g > -1) else ev_sales
        sub["ev_sales"] = (
            6.0 if adj_evs < 2 else (4.0 if adj_evs < 5 else (2.0 if adj_evs < 10 else 0.0))
        )
    else:
        sub["ev_sales"] = None

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

    # min_coverage 0.1: a single present multiple (the smallest, ev_sales/growth_adj_ps at 6/42=0.14)
    # still scores — for a valuation axis even one real multiple is signal, and it preserves the old
    # single-blended-sub-score behaviour where any one metric qualified the axis.
    result = finalize_score(sub, max_pts, min_coverage=0.1, bonus=upside_bonus or 0.0)
    result["sub_scores"]["analyst_upside"] = upside_bonus
    result["max_pts"]["analyst_upside"] = _UPSIDE_BONUS_MAX
    return result
