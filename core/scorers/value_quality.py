from __future__ import annotations

from .base import all_annual, clamp, currency_mismatch, finalize_score, latest_quarters, ttm


def score(fundamentals: list[dict], snapshot: dict) -> dict:
    sub: dict[str, float | None] = {}
    max_pts: dict[str, float] = {
        "profitability": 35.0,
        "balance_sheet": 25.0,
        "capital_discipline": 8.0,
        "cash_runway": 15.0,
        "execution_track": 10.0,
        "margin_durability": 12.0,
        "earnings_quality": 10.0,
    }
    bonus_max: dict[str, float] = {
        "buyback_bonus": 2.0,
        "insider_ownership_bonus": 3.0,
    }

    # Banks/fintech run on leverage — assets are the loan book, not plant/inventory — so a
    # "great" ROA sits around 1.5%, not 10%, and D/E or current ratio don't read as risk signals.
    is_financial = snapshot.get("sector") == "Financial Services"

    # Foreign filers (TSM/ASML/CIB) report fundamentals in their local currency while price/
    # market_cap come in USD — any ratio mixing the two (P/S, buybacks/mcap) is meaningless.
    fx_mismatch = currency_mismatch(snapshot)

    # 1. Profitability quality (0-35)
    roe = snapshot.get("roe")
    roa = snapshot.get("roa")
    net_m = snapshot.get("net_margin")
    pts, avail = 0.0, 0.0
    if roe is not None:
        pts += 8 if roe >= 0.20 else (6 if roe >= 0.10 else (3 if roe >= 0 else 0))
        avail += 8
    if roa is not None:
        if is_financial:
            pts += 6 if roa >= 0.015 else (4 if roa >= 0.008 else (2 if roa >= 0 else 0))
        else:
            pts += 6 if roa >= 0.10 else (4 if roa >= 0.05 else (2 if roa >= 0 else 0))
        avail += 6
    if net_m is not None:
        # A net margin that wildly outpaces operating margin usually means a one-off gain
        # (asset sale, warrant/equity revaluation, tax benefit) is masking a core business
        # that's still losing money — don't award profitability credit for it.
        op_m = snapshot.get("operating_margin")
        suspect_net_m = op_m is not None and op_m < 0 and (net_m - op_m) > 0.20
        effective_net_m = 0.0 if suspect_net_m else net_m
        pts += (
            6
            if effective_net_m >= 0.15
            else (4 if effective_net_m >= 0.05 else (2 if effective_net_m >= 0 else 0))
        )
        avail += 6
    # Normalize by the max achievable from the metrics actually present (not the fixed
    # all-three max) so a company reporting only some of ROE/ROA/net_margin isn't capped
    # below the axis ceiling — same available-coverage convention as finalize_score.
    sub["profitability"] = round(clamp(pts / avail * 35, 0, 35), 1) if avail else None

    # 2. Cash position (0-15) — branches on whether the company is actually burning cash
    # (ttm_fcf < 0), not on GAAP profitability, so pre-revenue companies (whose net_margin
    # is a degenerate 0.0 when revenue is ~$0) still get evaluated correctly. Burning cash:
    # score survival runway in quarters. Not burning: score cash held relative to revenue —
    # a real liquidity-cushion signal instead of leaving this axis blank for the ~75% of the
    # watchlist that's profitable (LMT holds ~2.5% of revenue in cash, AVGO/MU ~26-28% —
    # that's a genuine difference this used to throw away).
    latest_q = latest_quarters(fundamentals, 1)
    cash = latest_q[0].get("cash") if latest_q else None
    ttm_fcf = ttm(fundamentals, "fcf")
    ttm_rev = ttm(fundamentals, "revenue")
    if ttm_fcf is not None and ttm_fcf < 0 and cash is not None:
        if cash <= 0:
            sub["cash_runway"] = 0.0
        else:
            runway_q = cash / (abs(ttm_fcf) / 4)
            sub["cash_runway"] = (
                15.0
                if runway_q >= 12
                else 12.0
                if runway_q >= 8
                else 8.0
                if runway_q >= 4
                else 4.0
                if runway_q >= 2
                else 0.0
            )
    elif cash is not None and ttm_rev:
        cushion = cash / ttm_rev
        sub["cash_runway"] = (
            15.0
            if cushion >= 0.30
            else 12.0
            if cushion >= 0.15
            else 8.0
            if cushion >= 0.05
            else 4.0
            if cushion >= 0.01
            else 0.0
        )
    else:
        sub["cash_runway"] = None

    # 3. Execution track record (0-10) — % of last 4 reported quarters where actual EPS beat
    # estimate. Orthogonal to profitability: a company still in the red that consistently beats
    # its own numbers is executing well, which profitability alone can't credit.
    beat_rate = snapshot.get("earnings_beat_rate")
    if beat_rate is not None:
        sub["execution_track"] = round(clamp(beat_rate, 0, 1) * 10, 1)
    else:
        sub["execution_track"] = None

    # Margin durability (0-12) — a single good quarter can flatter profitability; this asks
    # whether gross margin has actually held up across multiple years. Splits the path into a
    # trend component (rising/flat margins are never punished for having "moved") and a
    # residual-noise component (how far actual margins wander off that trend line, regardless
    # of direction) — a real mid-history dip shows up as noise even if the latest year recovered.
    # Banks/fintechs don't report gross_margin (no COGS concept) — fall back to net_margin
    # derived from revenue/net_income so financials aren't structurally locked out of this axis.
    annuals_chron = sorted(all_annual(fundamentals), key=lambda a: a.get("period", ""))
    margins = [a["gross_margin"] for a in annuals_chron if a.get("gross_margin") is not None]
    if not margins:
        margins = [
            a["net_income"] / a["revenue"]
            for a in annuals_chron
            if a.get("net_income") is not None and a.get("revenue")
        ]
    n = len(margins)
    if n >= 3:
        xs = list(range(n))
        mean_x = (n - 1) / 2
        mean_y = sum(margins) / n
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, margins, strict=True))
        den = sum((x - mean_x) ** 2 for x in xs)
        raw_slope = num / den if den else 0.0
        trend = raw_slope / abs(mean_y) if mean_y else 0.0
        residuals = [
            y - (mean_y + raw_slope * (x - mean_x)) for x, y in zip(xs, margins, strict=True)
        ]
        residual_cv = ((sum(r**2 for r in residuals) / n) ** 0.5) / abs(mean_y) if mean_y else None
        if trend < -0.03:
            sub["margin_durability"] = 3.0
        elif residual_cv is not None and residual_cv > 0.05:
            sub["margin_durability"] = 7.0
        else:
            sub["margin_durability"] = 12.0
    else:
        sub["margin_durability"] = None

    # Earnings quality (0-10) — is the accounting profit actually backed by cash? Only
    # evaluated when net income is positive (there's a profit to sanity-check); a company
    # whose operating cash flow trails its net income for a stretch is leaning on accruals
    # (revenue recognition, working-capital timing) rather than real cash generation.
    ttm_ocf = ttm(fundamentals, "operating_cash_flow")
    ttm_ni = ttm(fundamentals, "net_income")
    if ttm_ni is not None and ttm_ni > 0 and ttm_ocf is not None:
        cash_ratio = ttm_ocf / ttm_ni
        sub["earnings_quality"] = (
            10.0
            if cash_ratio >= 1.2
            else 7.0
            if cash_ratio >= 0.8
            else 4.0
            if cash_ratio >= 0.5
            else 1.0
            if cash_ratio >= 0
            else 0.0
        )
    else:
        sub["earnings_quality"] = None

    # 4. Balance sheet health (0-20) — current ratio & D/E skipped for Financial Services,
    # where leverage is the product, not a risk signal; interest coverage still applies to all
    ttm_ebit = ttm(fundamentals, "ebit")
    ttm_int = ttm(fundamentals, "interest_expense")
    pts, avail = 0.0, 0.0
    if not is_financial:
        cur_ratio = snapshot.get("current_ratio")
        d2e = snapshot.get("debt_to_equity")
        if cur_ratio is not None:
            pts += (
                7
                if cur_ratio >= 2.0
                else (5 if cur_ratio >= 1.5 else (3 if cur_ratio >= 1.0 else 0))
            )
            avail += 7
        if d2e is not None:
            pts += (
                7
                if d2e <= 50
                else (5 if d2e <= 100 else (3 if d2e <= 200 else (1 if d2e <= 400 else 0)))
            )
            avail += 7
    if ttm_ebit is not None and ttm_int is not None and ttm_int != 0:
        cov = ttm_ebit / abs(ttm_int)
        pts += 6 if cov >= 5 else (4 if cov >= 3 else (2 if cov >= 1.5 else (1 if cov >= 0 else 0)))
        avail += 6
    # Normalize by the max achievable from the metrics present (financials skip current
    # ratio & D/E), consistent with finalize_score's available-coverage convention.
    sub["balance_sheet"] = round(clamp(pts / avail * 25, 0, 25), 1) if avail else None

    # 5. Capital discipline — dilution rate only (0-8)
    dil = snapshot.get("dilution_rate")
    if dil is not None:
        pts = 5.0 + (3 if dil <= -0.02 else (1 if dil <= 0.01 else (-1 if dil <= 0.05 else -3)))
        sub["capital_discipline"] = round(clamp(pts, 0, 8), 1)
    else:
        sub["capital_discipline"] = None

    # Buyback bonus — extra credit only, doesn't penalize companies that don't buy back (0-2)
    mc = snapshot.get("market_cap") or 0
    buybacks = [
        q["buybacks"] for q in latest_quarters(fundamentals, 4) if q.get("buybacks") is not None
    ]
    if buybacks and mc > 0 and not fx_mismatch:
        net = sum(buybacks)
        buyback_bonus = (
            round(clamp(abs(net) / mc / 0.02, 0, bonus_max["buyback_bonus"]), 1) if net < 0 else 0.0
        )
    else:
        buyback_bonus = None

    # Insider ownership bonus — skin in the game, extra credit only (0-3). Low ownership
    # isn't penalized: at mega-cap scale even a founder-led company can show a tiny %, so
    # this only ever rewards high ownership, never punishes a low one.
    held_pct = snapshot.get("held_pct_insiders")
    if held_pct is not None:
        insider_ownership_bonus = round(
            clamp(held_pct / 0.15, 0, 1) * bonus_max["insider_ownership_bonus"], 1
        )
    else:
        insider_ownership_bonus = None

    total_bonus = (buyback_bonus or 0.0) + (insider_ownership_bonus or 0.0)
    result = finalize_score(sub, max_pts, bonus=total_bonus)
    result["sub_scores"]["buyback_bonus"] = buyback_bonus
    result["max_pts"]["buyback_bonus"] = bonus_max["buyback_bonus"]
    result["sub_scores"]["insider_ownership_bonus"] = insider_ownership_bonus
    result["max_pts"]["insider_ownership_bonus"] = bonus_max["insider_ownership_bonus"]
    return result
