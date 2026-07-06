from __future__ import annotations
from .base import clamp


def score(snapshot: dict) -> dict:
    sub: dict[str, float | None] = {}
    max_pts: dict[str, float] = {
        "dip_signal":        30.0,
        "spy_divergence":    20.0,
        "short_setup":       20.0,
        "options_sentiment": 15.0,
        "analyst_upside":    15.0,
    }

    # 1. Dip signal — beta-adjusted recent + annual range (0-30)
    pct_1w  = snapshot.get("pct_from_1w_high")
    pct_52h = snapshot.get("pct_from_52w_high")
    beta    = max(snapshot.get("beta") or 1.0, 0.5)
    pts = 0.0
    if pct_1w is not None:
        # Normalize drop by beta: beta=2 stock needs a 2x larger drop to count
        pts += clamp(abs(pct_1w) / beta / 0.05, 0, 1) * 15
    if pct_52h is not None:
        # Distance from 52W high → proximity to annual lows
        pts += clamp(abs(pct_52h) / 0.50, 0, 1) * 15
    sub["dip_signal"] = round(clamp(pts, 0, 30), 1) if (pct_1w is not None or pct_52h is not None) else None

    # 2. SPY divergence — underperformance vs SPY = mean reversion potential (0-20)
    r    = snapshot.get("returns", {})
    t3m  = r.get("ticker_return_3m")
    s3m  = r.get("spy_return_3m")
    t1m  = r.get("ticker_return_1m")
    s1m  = r.get("spy_return_1m")
    pts  = 0.0
    cnt  = 0
    if t3m is not None and s3m is not None:
        pts += clamp((s3m - t3m) / 0.15, 0, 1) * 12
        cnt += 1
    if t1m is not None and s1m is not None:
        pts += clamp((s1m - t1m) / 0.10, 0, 1) * 8
        cnt += 1
    sub["spy_divergence"] = round(clamp(pts, 0, 20), 1) if cnt else None

    # 3. Short squeeze setup — high short interest + days-to-cover (0-20)
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

    # 4. Options sentiment — high put/call = fear = contrarian buy (0-15)
    pcr = snapshot.get("put_call_ratio")
    if pcr is not None:
        sub["options_sentiment"] = float(
            15 if pcr >= 1.5 else (10 if pcr >= 1.0 else (6 if pcr >= 0.7 else (3 if pcr >= 0.5 else 0)))
        )
    else:
        sub["options_sentiment"] = None

    # 5. Analyst upside weighted by coverage (0-15)
    price        = snapshot.get("price")
    target_mean  = snapshot.get("target_mean")
    analyst_cnt  = snapshot.get("analyst_count") or 0
    if price and target_mean and target_mean > 0 and price > 0:
        upside  = (target_mean - price) / price
        base    = clamp(upside / 0.30, 0, 1) * 15
        cov_adj = clamp(analyst_cnt / 10, 0.3, 1.0) if analyst_cnt else 0.5
        sub["analyst_upside"] = round(base * cov_adj, 1)
    else:
        sub["analyst_upside"] = None

    available = {k: v for k, v in sub.items() if v is not None}
    if not available:
        return {"score": None, "sub_scores": sub}
    total_max      = sum(max_pts[k] for k in available)
    total_possible = sum(max_pts.values())
    if total_max / total_possible < 0.30:
        return {"score": None, "sub_scores": sub}
    final     = round(clamp(sum(available.values()) / total_max * 100, 0, 100), 1)
    return {"score": final, "sub_scores": sub}
