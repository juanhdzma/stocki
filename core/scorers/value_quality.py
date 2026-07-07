from __future__ import annotations
from .base import clamp, ttm, latest_quarters, finalize_score, analyst_upside_pts


def score(fundamentals: list[dict], snapshot: dict) -> dict:
    sub: dict[str, float | None] = {}
    max_pts: dict[str, float] = {
        "profitability":      20.0,
        "valuation":          20.0,
        "balance_sheet":      20.0,
        "capital_discipline": 10.0,
        "analyst_conviction": 10.0,
    }

    # 1. Profitability quality (0-20)
    roe   = snapshot.get("roe")
    roa   = snapshot.get("roa")
    net_m = snapshot.get("net_margin")
    pts, cnt = 0.0, 0
    if roe is not None:
        pts += 8 if roe >= 0.20 else (6 if roe >= 0.10 else (3 if roe >= 0 else 0))
        cnt += 1
    if roa is not None:
        pts += 6 if roa >= 0.10 else (4 if roa >= 0.05 else (2 if roa >= 0 else 0))
        cnt += 1
    if net_m is not None:
        pts += 6 if net_m >= 0.15 else (4 if net_m >= 0.05 else (2 if net_m >= 0 else 0))
        cnt += 1
    sub["profitability"] = round(clamp(pts / (8 + 6 + 6) * 20, 0, 20), 1) if cnt else None

    # 2. Valuation reasonableness (0-20) — forward vs trailing PE, PEG, growth-adj P/S
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
    if ps is not None and rev_g is not None:
        adj_ps = ps / (1 + rev_g) if rev_g > -1 else ps
        pts += 6 if adj_ps < 2 else (4 if adj_ps < 5 else (2 if adj_ps < 10 else 0))
        cnt += 1
    sub["valuation"] = round(clamp(pts / (12 + 8 + 6) * 20, 0, 20), 1) if cnt else None

    # 4. Balance sheet health — current ratio, D/E, interest coverage (0-20)
    cur_ratio = snapshot.get("current_ratio")
    d2e       = snapshot.get("debt_to_equity")
    ttm_ebit  = ttm(fundamentals, "ebit")
    ttm_int   = ttm(fundamentals, "interest_expense")
    pts, cnt = 0.0, 0
    if cur_ratio is not None:
        pts += 7 if cur_ratio >= 2.0 else (5 if cur_ratio >= 1.5 else (3 if cur_ratio >= 1.0 else 0))
        cnt += 1
    if d2e is not None:
        pts += 7 if d2e <= 50 else (5 if d2e <= 100 else (3 if d2e <= 200 else (1 if d2e <= 400 else 0)))
        cnt += 1
    if ttm_ebit is not None and ttm_int is not None and ttm_int != 0:
        cov  = ttm_ebit / abs(ttm_int)
        pts += 6 if cov >= 5 else (4 if cov >= 3 else (2 if cov >= 1.5 else (1 if cov >= 0 else 0)))
        cnt += 1
    sub["balance_sheet"] = round(clamp(pts / (7 + 7 + 6) * 20, 0, 20), 1) if cnt else None

    # 5. Capital discipline — dilution rate + buyback yield (0-10)
    dil = snapshot.get("dilution_rate")
    mc  = snapshot.get("market_cap") or 0
    buybacks = [q["buybacks"] for q in latest_quarters(fundamentals, 4) if q.get("buybacks") is not None]
    has_cd_data = dil is not None or (bool(buybacks) and mc > 0)
    pts = 5.0
    if dil is not None:
        pts += 3 if dil <= -0.02 else (1 if dil <= 0.01 else (-1 if dil <= 0.05 else -3))
    if buybacks and mc > 0:
        net = sum(buybacks)
        if net < 0:
            pts += clamp(abs(net) / mc / 0.02, 0, 2)
    sub["capital_discipline"] = round(clamp(pts, 0, 10), 1) if has_cd_data else None

    # 6. Analyst conviction — bull vs bear distribution (0-10)
    sb = snapshot.get("rec_strong_buy", 0) or 0
    b  = snapshot.get("rec_buy",        0) or 0
    h  = snapshot.get("rec_hold",       0) or 0
    s  = snapshot.get("rec_sell",       0) or 0
    ss = snapshot.get("rec_strong_sell",0) or 0
    total = sb + b + h + s + ss
    if total > 0:
        net_bull     = (sb + b - s - ss) / total
        strong_bonus = sb / total * 0.2
        sub["analyst_conviction"] = round(clamp((net_bull + 1) / 2 * 10 + strong_bonus, 0, 10), 1)
    else:
        sub["analyst_conviction"] = None

    return finalize_score(sub, max_pts)
