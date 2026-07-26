from __future__ import annotations


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def currency_mismatch(snapshot: dict) -> bool:
    cur, fin_cur = snapshot.get("currency"), snapshot.get("financial_currency")
    return bool(cur and fin_cur and cur != fin_cur)


def analyst_upside_pts(
    price: float | None, target_mean: float | None, max_pts: float
) -> float | None:
    if not (price and target_mean and target_mean > 0 and price > 0):
        return None
    return clamp((target_mean - price) / price / 0.30, 0, 1) * max_pts


def linreg_slope(values: list[float]) -> float:
    """Least-squares slope (change per step) over the series. Uses every point, so one
    noisy endpoint can't dominate the trend the way a first-minus-last delta does."""
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(values) / n
    den = sum((x - mx) ** 2 for x in xs)
    if not den:
        return 0.0
    num = sum((x - mx) * (y - my) for x, y in zip(xs, values, strict=True))
    return num / den


def slope_normalized(values: list[float]) -> float:
    """Linear regression slope as fraction of mean. Positive = uptrend."""
    my = sum(values) / len(values) if values else 0.0
    if my == 0:
        return 0.0
    return linreg_slope(values) / abs(my)


def all_annual(funds: list[dict]) -> list[dict]:
    return [f for f in funds if f.get("type") == "annual"]


def latest_quarters(funds: list[dict], n: int = 4) -> list[dict]:
    return [f for f in funds if f.get("type") == "quarterly"][:n]


def ttm(funds: list[dict], field: str) -> float | None:
    """Trailing-twelve-month total = a 4-quarter-equivalent sum. With fewer than 4
    quarters populated, annualize from what's present so a partial year isn't treated
    as a full one (a raw partial sum understates burn/flow — e.g. cash_runway divides
    the TTM by 4 to get quarterly burn)."""
    quarters = latest_quarters(funds, 4)
    values = [q[field] for q in quarters if q.get(field) is not None]
    if not values:
        return None
    return sum(values) / len(values) * 4


def finalize_score(
    sub: dict[str, float | None],
    max_pts: dict[str, float],
    min_coverage: float = 0.30,
    bonus: float = 0.0,
) -> dict:
    available = {k: v for k, v in sub.items() if v is not None}
    if not available:
        return {"score": None, "sub_scores": sub, "max_pts": max_pts}
    total_max = sum(max_pts[k] for k in available)
    total_possible = sum(max_pts.values())
    if not total_possible or total_max / total_possible < min_coverage:
        return {"score": None, "sub_scores": sub, "max_pts": max_pts}
    final = round(clamp(sum(available.values()) / total_max * 100 + bonus, 0, 100), 1)
    return {"score": final, "sub_scores": sub, "max_pts": max_pts}
