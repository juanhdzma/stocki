from __future__ import annotations
from .base import clamp, finalize_score, analyst_upside_pts, ttm, currency_mismatch


def score(fundamentals: list[dict], snapshot: dict) -> dict:
    sub: dict[str, float | None] = {}
    max_pts: dict[str, float] = {
        "fcf_yield":          45.0,
        "analyst_upside":     30.0,
        "valuation":          20.0,
        "analyst_conviction":  8.0,
    }

    # Foreign filers (TSM/ASML/CIB) report fundamentals in local currency while price/market_cap
    # come in USD — any ratio mixing the two (FCF yield, growth-adj P/S) is meaningless.
    fx_mismatch = currency_mismatch(snapshot)

    # 1. FCF yield (0-45) — real cash generation vs. price, no analyst subjectivity involved.
    # For a foreign filer, FCF is in local currency and market_cap in the price currency:
    # convert with fx_rate so the yield is valid instead of dropping this (45pt) signal. If the
    # rate is unavailable, fall back to excluding it rather than mixing currencies.
    mc      = snapshot.get("market_cap")
    ttm_fcf = ttm(fundamentals, "fcf")
    if fx_mismatch:
        fx = snapshot.get("fx_rate")
        ttm_fcf = ttm_fcf * fx if (ttm_fcf is not None and fx) else None
    if ttm_fcf is not None and mc and mc > 0:
        sub["fcf_yield"] = round(clamp((ttm_fcf / mc) / 0.06, 0, 1) * 45, 1)
    else:
        sub["fcf_yield"] = None

    # 3. Analyst upside weighted by coverage (0-30) — kept small: sell-side targets skew
    #    bullish and herd toward consensus, so this is a supporting signal, not the driver
    price       = snapshot.get("price")
    target_mean = snapshot.get("target_mean")
    analyst_cnt = snapshot.get("analyst_count") or 0
    up = analyst_upside_pts(price, target_mean, 30.0)
    if up is not None:
        cov_adj = clamp(analyst_cnt / 10, 0.3, 1.0) if analyst_cnt else 0.5
        sub["analyst_upside"] = round(up * cov_adj, 1)
    else:
        sub["analyst_upside"] = None

    # 4. Valuation reasonableness (0-20) — forward vs trailing PE, PEG, growth-adj P/S
    fwd_pe = snapshot.get("forward_pe")
    trl_pe = snapshot.get("trailing_pe")
    peg    = snapshot.get("peg_ratio")
    ps     = snapshot.get("price_to_sales")
    rev_g  = snapshot.get("revenue_growth")
    pts, cnt = 0.0, 0
    if fwd_pe and trl_pe and fwd_pe > 0 and trl_pe > 0:
        ratio  = trl_pe / fwd_pe  # > 1 means earnings expected to grow
        pts   += clamp((ratio - 1) / 0.20, 0, 1) * 6 + (6 if ratio > 1 else 0)
        cnt   += 1
    if peg is not None and peg > 0:
        pts += 8 if peg < 1.0 else (5 if peg < 1.5 else (2 if peg < 2.5 else 0))
        cnt += 1
    if ps is not None and rev_g is not None and not fx_mismatch:
        adj_ps = ps / (1 + rev_g) if rev_g > -1 else ps
        pts += 6 if adj_ps < 2 else (4 if adj_ps < 5 else (2 if adj_ps < 10 else 0))
        cnt += 1
    sub["valuation"] = round(clamp(pts / (12 + 8 + 6) * 20, 0, 20), 1) if cnt else None

    # 5. Analyst conviction — bull vs bear distribution (0-8)
    sb = snapshot.get("rec_strong_buy", 0) or 0
    b  = snapshot.get("rec_buy",        0) or 0
    h  = snapshot.get("rec_hold",       0) or 0
    s  = snapshot.get("rec_sell",       0) or 0
    ss = snapshot.get("rec_strong_sell",0) or 0
    total = sb + b + h + s + ss
    if total > 0:
        net_bull     = (sb + b - s - ss) / total
        strong_bonus = sb / total * 0.2
        sub["analyst_conviction"] = round(clamp((net_bull + 1) / 2 * 8 + strong_bonus, 0, 8), 1)
    else:
        sub["analyst_conviction"] = None

    return finalize_score(sub, max_pts)
