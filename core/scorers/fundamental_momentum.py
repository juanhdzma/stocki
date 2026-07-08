from __future__ import annotations
from .base import clamp, latest_quarters, finalize_score


def _slope_normalized(values: list[float]) -> float:
    """Linear regression slope as fraction of mean. Positive = uptrend."""
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(values) / n
    if my == 0:
        return 0.0
    num = sum((x - mx) * (y - my) for x, y in zip(xs, values))
    den = sum((x - mx) ** 2 for x in xs)
    return (num / den) / abs(my) if den else 0.0


def score(fundamentals: list[dict], snapshot: dict) -> dict:
    quarters = latest_quarters(fundamentals, 8)
    sub: dict[str, float | None] = {}
    max_pts: dict[str, float] = {
        "revenue_trend":  30.0,
        "ni_trajectory":  28.0,
        "gm_expansion":   20.0,
        "fcf_trajectory": 10.0,
        "rd_intensity":    6.0,
        "rule_of_40":      6.0,
    }

    rd_pairs = [(q["rd_expense"], q["revenue"]) for q in quarters
                if q.get("rd_expense") is not None and q.get("revenue") is not None and q["revenue"] != 0]

    # 1. Revenue trend (0-30) — slope over up to 8 quarters, chronological
    rev_chron = list(reversed([q["revenue"] for q in quarters if q.get("revenue") is not None]))
    if len(rev_chron) >= 2:
        s = _slope_normalized(rev_chron)
        # s ≈ +0.10/quarter = strong; s ≈ -0.10 = shrinking
        sub["revenue_trend"] = round(clamp((s / 0.10 + 1) / 2 * 30, 0, 30), 1)
    else:
        sub["revenue_trend"] = None

    # 2. Net income trajectory (0-20) — direction matters even if negative
    ni_all = [q["net_income"] for q in quarters if q.get("net_income") is not None]
    if len(ni_all) >= 2:
        ni_recent = ni_all[0]
        ni_older  = ni_all[-1]
        delta     = ni_recent - ni_older
        rev_scale = rev_chron[-1] if rev_chron else None
        if rev_scale and rev_scale != 0:
            delta_pct = delta / abs(rev_scale)
            ni_s = clamp((delta_pct / 0.05 + 1) / 2 * 28, 0, 28)
        else:
            ni_s = 18.0 if delta > 0 else 10.0
        if ni_older < 0 and ni_recent > 0:   ni_s = min(28, ni_s + 4)
        elif ni_older < 0 < delta:            ni_s = min(28, ni_s + 2)
        sub["ni_trajectory"] = round(ni_s, 1)
    else:
        sub["ni_trajectory"] = None

    # 3. Gross margin expansion (0-20)
    # If GM fell but R&D intensity grew, treat as neutral (intentional investment, not erosion)
    gm_all = [q["gross_margin"] for q in quarters if q.get("gross_margin") is not None]
    if len(gm_all) >= 2:
        gm_delta = gm_all[0] - gm_all[-1]
        if gm_delta < 0 and len(rd_pairs) >= 2:
            rd_pcts = [rd / rev for rd, rev in rd_pairs]
            rd_growing = rd_pcts[0] > rd_pcts[-1]
            if rd_growing:
                gm_delta = 0.0
        sub["gm_expansion"] = round(clamp((gm_delta / 0.05 + 1) / 2 * 20, 0, 20), 1)
    else:
        sub["gm_expansion"] = None

    # 4. FCF trajectory (0-15)
    fcf_all = [q["fcf"] for q in quarters if q.get("fcf") is not None]
    if len(fcf_all) >= 2:
        delta     = fcf_all[0] - fcf_all[-1]
        rev_scale = rev_chron[-1] if rev_chron else None
        if rev_scale and rev_scale != 0:
            sub["fcf_trajectory"] = round(clamp((delta / abs(rev_scale) / 0.05 + 1) / 2 * 10, 0, 10), 1)
        else:
            sub["fcf_trajectory"] = 6.0 if delta > 0 else 3.0
    else:
        sub["fcf_trajectory"] = None

    # 5. R&D intensity (0-6)
    if len(rd_pairs) >= 2:
        pcts = [rd / rev for rd, rev in rd_pairs]
        base_pts  = clamp(pcts[0] * 100, 0, 3)
        trend_pts = clamp((pcts[0] - pcts[-1]) / 0.05 * 3, 0, 3)
        sub["rd_intensity"] = round(base_pts + trend_pts, 1)
    else:
        sub["rd_intensity"] = None

    # 6. Rule of 40 (0-5)
    rev_g = snapshot.get("revenue_growth")
    op_m  = snapshot.get("operating_margin")
    if rev_g is not None and op_m is not None:
        r40 = rev_g * 100 + op_m * 100
        sub["rule_of_40"] = 6.0 if r40 >= 40 else (3.0 if r40 >= 20 else (1.0 if r40 >= 0 else 0.0))
    else:
        sub["rule_of_40"] = None

    return finalize_score(sub, max_pts)
