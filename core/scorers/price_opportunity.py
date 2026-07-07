from __future__ import annotations
from .base import clamp, finalize_score, analyst_upside_pts, latest_quarters


def score(fundamentals: list[dict], snapshot: dict) -> dict:
    sub: dict[str, float | None] = {}
    max_pts: dict[str, float] = {
        "dip_signal":        30.0,
        "short_setup":       20.0,
        "price_discount":    20.0,
        "buyback_signal":    15.0,
        "options_sentiment": 15.0,
        "analyst_upside":    15.0,
    }

    # 1. Dip signal — beta-adjusted recent + annual range (0-30)
    pct_1w  = snapshot.get("pct_from_1w_high")
    pct_52h = snapshot.get("pct_from_52w_high")
    beta    = max(snapshot.get("beta") or 1.0, 0.5)
    pts = 0.0
    if pct_1w is not None:
        pts += clamp(max(-pct_1w, 0) / beta / 0.05, 0, 1) * 15
    if pct_52h is not None:
        pts += clamp(abs(pct_52h) / 0.50, 0, 1) * 15
    sub["dip_signal"] = round(clamp(pts, 0, 30), 1) if (pct_1w is not None or pct_52h is not None) else None

    # 2. Short squeeze setup — high short interest + days-to-cover (0-20)
    short_pct   = snapshot.get("short_percent_of_float")
    short_ratio = snapshot.get("short_ratio")
    pts, cnt = 0.0, 0
    if short_pct is not None:
        pts += 10 if short_pct >= 0.20 else (6 if short_pct >= 0.10 else (3 if short_pct >= 0.05 else 0))
        cnt += 1
    if short_ratio is not None:
        pts += 10 if short_ratio >= 10 else (7 if short_ratio >= 5 else (4 if short_ratio >= 3 else 1))
        cnt += 1
    sub["short_setup"] = round(clamp(pts, 0, 20), 1) if cnt else None

    # 4. Price discount — distance from 52W high + analyst upside (0-20)
    pct_52h     = snapshot.get("pct_from_52w_high")
    price_pd    = snapshot.get("price")
    target_mean = snapshot.get("target_mean")
    pts_pd = 0.0
    if pct_52h is not None:
        pts_pd += clamp(abs(pct_52h) / 0.30, 0, 1) * 10
    up_pd = analyst_upside_pts(price_pd, target_mean, 10.0)
    if up_pd is not None:
        pts_pd += up_pd
    sub["price_discount"] = round(clamp(pts_pd, 0, 20), 1) if (pct_52h is not None or up_pd is not None) else None

    # 5. Buyback signal — yield as % of market cap; management buying own stock = cheap (0-15)
    mc_po = snapshot.get("market_cap") or 0
    bb_vals = [q["buybacks"] for q in latest_quarters(fundamentals, 4) if q.get("buybacks") is not None]
    if bb_vals and mc_po > 0:
        total_bb = sum(bb_vals)
        sub["buyback_signal"] = round(clamp(abs(total_bb) / mc_po / 0.03 * 15, 0, 15), 1) if total_bb < 0 else 0.0
    else:
        sub["buyback_signal"] = None

    # 6. Options sentiment — high put/call = fear = contrarian buy (0-15)
    pcr = snapshot.get("put_call_ratio")
    if pcr is not None:
        sub["options_sentiment"] = float(
            15 if pcr >= 1.5 else (10 if pcr >= 1.0 else (6 if pcr >= 0.7 else (3 if pcr >= 0.5 else 0)))
        )
    else:
        sub["options_sentiment"] = None

    # 7. Analyst upside weighted by coverage (0-15)
    price        = snapshot.get("price")
    target_mean  = snapshot.get("target_mean")
    analyst_cnt  = snapshot.get("analyst_count") or 0
    up = analyst_upside_pts(price, target_mean, 15.0)
    if up is not None:
        cov_adj = clamp(analyst_cnt / 10, 0.3, 1.0) if analyst_cnt else 0.5
        sub["analyst_upside"] = round(up * cov_adj, 1)
    else:
        sub["analyst_upside"] = None

    return finalize_score(sub, max_pts)
