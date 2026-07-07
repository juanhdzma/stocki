from __future__ import annotations


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def analyst_upside_pts(price: float | None, target_mean: float | None, max_pts: float) -> float | None:
    if not (price and target_mean and target_mean > 0 and price > 0):
        return None
    return clamp((target_mean - price) / price / 0.30, 0, 1) * max_pts


def all_annual(funds: list[dict]) -> list[dict]:
    return [f for f in funds if f.get("type") == "annual"]


def latest_quarters(funds: list[dict], n: int = 4) -> list[dict]:
    return [f for f in funds if f.get("type") == "quarterly"][:n]


def ttm(funds: list[dict], field: str) -> float | None:
    quarters = latest_quarters(funds, 4)
    values = [q[field] for q in quarters if q.get(field) is not None]
    return sum(values) if values else None


def finalize_score(sub: dict[str, float | None], max_pts: dict[str, float], min_coverage: float = 0.30) -> dict:
    available = {k: v for k, v in sub.items() if v is not None}
    if not available:
        return {"score": None, "sub_scores": sub}
    total_max      = sum(max_pts[k] for k in available)
    total_possible = sum(max_pts.values())
    if not total_possible or total_max / total_possible < min_coverage:
        return {"score": None, "sub_scores": sub}
    final = round(clamp(sum(available.values()) / total_max * 100, 0, 100), 1)
    return {"score": final, "sub_scores": sub}
