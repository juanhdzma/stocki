from __future__ import annotations
from .fundamental_momentum import score as fm_score
from .value_quality import score as vq_score
from .price_short import score as ps_score
from .price_long import score as pl_score
from core.insider_score import compute_insider_score, normalize

_BASE_WEIGHTS = {
    "fundamental_momentum": 0.25,
    "value_quality":        0.30,
    "insider_conviction":   0.20,
}

_PRICE_WEIGHT = 0.25

_THRESHOLDS = [
    (60, "BUY"),
    (40, "HOLD"),
    (0,  "SELL"),
]

_INSIDER_MAP = [
    (-100, 0), (-60, 5), (-10, 45), (0, 50), (40, 90), (100, 100),
]


def _map_insider(raw: float) -> float:
    for i in range(len(_INSIDER_MAP) - 1):
        x0, y0 = _INSIDER_MAP[i]
        x1, y1 = _INSIDER_MAP[i + 1]
        if x0 <= raw <= x1:
            t = (raw - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return 0.0 if raw < -100 else 100.0


def _insider(snapshot: dict) -> dict:
    txs  = snapshot.get("insider_transactions", [])
    mc   = snapshot.get("market_cap")
    w52l = snapshot.get("week52_low")
    w52h = snapshot.get("week52_high")

    normalized = normalize(txs)
    r3m = compute_insider_score(normalized, market_cap=mc, week52_low=w52l,
                                week52_high=w52h, days_back=90,  _already_normalized=True)
    r1y = compute_insider_score(normalized, market_cap=mc, week52_low=w52l,
                                week52_high=w52h, days_back=365, _already_normalized=True)

    sub = {
        "score_3m":       r3m["score"],
        "score_1y":       r1y["score"],
        "valid_buys_3m":  r3m["valid_buys"],
        "valid_sells_3m": r3m["valid_sells"],
    }

    if not txs:
        return {"score": 50.0, "sub_scores": sub}
    if r1y["valid_buys"] + r1y["valid_sells"] == 0:
        return {"score": None, "sub_scores": sub}

    r3m_has_data = r3m["valid_buys"] + r3m["valid_sells"] > 0
    raw_blend = (r3m["score"] * 0.7 + r1y["score"] * 0.3) if r3m_has_data else r1y["score"]

    reversal_bonus = 0.0
    if r3m_has_data and r1y["score"] < 0 and r3m["score"] > 0:
        reversal_bonus = min(20.0, (r3m["score"] - r1y["score"]) / 5)

    raw_final = max(-100.0, min(100.0, raw_blend + reversal_bonus))
    return {
        "score": round(_map_insider(raw_final), 1),
        "sub_scores": sub,
    }


def _composite(base_scores: dict, price_score: dict, price_key: str) -> dict:
    all_scores = {**base_scores, price_key: price_score}
    weights    = {**_BASE_WEIGHTS, price_key: _PRICE_WEIGHT}
    weights_pct = {k: round(v * 100) for k, v in weights.items()}

    available = {k: v for k, v in all_scores.items() if v["score"] is not None}
    if not available:
        return {"score": None, "action": "N/A", "weights": weights_pct}

    total_w   = sum(weights[k] for k in available)
    score     = round(sum(v["score"] * weights[k] / total_w for k, v in available.items()), 1)
    action    = next(label for threshold, label in _THRESHOLDS if score >= threshold)
    return {"score": score, "action": action, "weights": weights_pct}


def compute_all(fundamentals: list[dict], snapshot: dict) -> dict:
    base = {
        "fundamental_momentum": fm_score(fundamentals, snapshot),
        "value_quality":        vq_score(fundamentals, snapshot),
        "insider_conviction":   _insider(snapshot),
    }
    price_short = ps_score(fundamentals, snapshot)
    price_long  = pl_score(fundamentals, snapshot)

    return {
        **base,
        "price_short":      price_short,
        "price_long":       price_long,
        "composite_short":  _composite(base, price_short, "price_short"),
        "composite_long":   _composite(base, price_long,  "price_long"),
    }
