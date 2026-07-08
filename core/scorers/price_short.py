from __future__ import annotations
from .base import clamp, finalize_score


def score(fundamentals: list[dict], snapshot: dict) -> dict:
    sub: dict[str, float | None] = {}
    max_pts: dict[str, float] = {
        "dip_signal":        50.0,
        "options_sentiment": 30.0,
        "short_setup":       20.0,
    }

    # 1. Dip signal — beta-adjusted 1W drop (0-50)
    pct_1w = snapshot.get("pct_from_1w_high")
    beta   = max(snapshot.get("beta") or 1.0, 0.5)
    if pct_1w is not None:
        sub["dip_signal"] = round(clamp(max(-pct_1w, 0) / beta / 0.05, 0, 1) * 50, 1)
    else:
        sub["dip_signal"] = None

    # 2. Options sentiment — high put/call = fear = contrarian buy (0-30)
    pcr = snapshot.get("put_call_ratio")
    if pcr is not None:
        sub["options_sentiment"] = float(
            30 if pcr >= 1.5 else (20 if pcr >= 1.0 else (12 if pcr >= 0.7 else (6 if pcr >= 0.5 else 0)))
        )
    else:
        sub["options_sentiment"] = None

    # 3. Short squeeze setup — short interest + days-to-cover (0-20)
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

    return finalize_score(sub, max_pts)
