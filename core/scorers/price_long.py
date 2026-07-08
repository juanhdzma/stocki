from __future__ import annotations
from .base import clamp, finalize_score, analyst_upside_pts, latest_quarters


def score(fundamentals: list[dict], snapshot: dict) -> dict:
    sub: dict[str, float | None] = {}
    max_pts: dict[str, float] = {
        "price_discount": 40.0,
        "analyst_upside": 35.0,
        "buyback_signal": 25.0,
    }

    # 1. Price discount — distance from 52W high only (0-40)
    pct_52h = snapshot.get("pct_from_52w_high")
    if pct_52h is not None:
        sub["price_discount"] = round(clamp(abs(pct_52h) / 0.40, 0, 1) * 40, 1)
    else:
        sub["price_discount"] = None

    # 2. Analyst upside weighted by coverage (0-35)
    price       = snapshot.get("price")
    target_mean = snapshot.get("target_mean")
    analyst_cnt = snapshot.get("analyst_count") or 0
    up = analyst_upside_pts(price, target_mean, 35.0)
    if up is not None:
        cov_adj = clamp(analyst_cnt / 10, 0.3, 1.0) if analyst_cnt else 0.5
        sub["analyst_upside"] = round(up * cov_adj, 1)
    else:
        sub["analyst_upside"] = None

    # 3. Buyback signal — yield as % of market cap (0-25)
    mc = snapshot.get("market_cap") or 0
    bb_vals = [q["buybacks"] for q in latest_quarters(fundamentals, 4) if q.get("buybacks") is not None]
    if bb_vals and mc > 0:
        total_bb = sum(bb_vals)
        sub["buyback_signal"] = round(clamp(abs(total_bb) / mc / 0.03 * 25, 0, 25), 1) if total_bb < 0 else 0.0
    else:
        sub["buyback_signal"] = None

    return finalize_score(sub, max_pts)
