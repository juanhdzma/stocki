from __future__ import annotations


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def aggregate(sub_scores: dict[str, float | None], weights: dict[str, float]) -> dict:
    available = {k: v for k, v in sub_scores.items() if v is not None}
    if not available:
        return {"score": None, "sub_scores": sub_scores}
    total_w = sum(weights[k] for k in available)
    if total_w == 0:
        return {"score": None, "sub_scores": sub_scores}
    score = sum(v * weights[k] / total_w for k, v in available.items())
    return {"score": round(score, 2), "sub_scores": sub_scores}


def latest_annual(funds: list[dict]) -> dict | None:
    for f in funds:
        if f.get("type") == "annual":
            return f
    return None


def all_annual(funds: list[dict]) -> list[dict]:
    return [f for f in funds if f.get("type") == "annual"]


def latest_quarters(funds: list[dict], n: int = 4) -> list[dict]:
    return [f for f in funds if f.get("type") == "quarterly"][:n]


def ttm(funds: list[dict], field: str) -> float | None:
    quarters = latest_quarters(funds, 4)
    values = [q[field] for q in quarters if q.get(field) is not None]
    return sum(values) if values else None
