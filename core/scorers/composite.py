from __future__ import annotations
from .base import clamp
from .fundamental_momentum import score as fm_score
from .value_quality import score as vq_score
from .price_opportunity import score as po_score
from core.insider_score import compute_insider_score, _normalize

_WEIGHTS = {
    "fundamental_momentum": 0.30,
    "value_quality":        0.30,
    "insider_conviction":   0.25,
    "price_opportunity":    0.15,
}

_THRESHOLDS = [
    (60, "BUY"),
    (40, "HOLD"),
    (0,  "SELL"),
]


def _insider(snapshot: dict) -> dict:
    txs  = snapshot.get("insider_transactions", [])
    mc   = snapshot.get("market_cap")
    w52l = snapshot.get("week52_low")
    w52h = snapshot.get("week52_high")

    normalized = _normalize(txs)
    r3m = compute_insider_score(normalized, market_cap=mc, week52_low=w52l,
                                week52_high=w52h, days_back=90,  _already_normalized=True)
    r1y = compute_insider_score(normalized, market_cap=mc, week52_low=w52l,
                                week52_high=w52h, days_back=365, _already_normalized=True)

    sub = {
        "score_3m":      r3m["score"],
        "score_1y":      r1y["score"],
        "valid_buys_3m": r3m["valid_buys"],
        "valid_sells_3m":r3m["valid_sells"],
    }

    if r1y["valid_buys"] + r1y["valid_sells"] == 0:
        return {"score": None, "sub_scores": sub}

    raw_blend = r3m["score"] * 0.7 + r1y["score"] * 0.3
    return {
        "score": round((raw_blend + 100) / 2, 1),  # -100..+100 → 0..100
        "sub_scores": sub,
    }


def compute_all(fundamentals: list[dict], snapshot: dict) -> dict:
    scores = {
        "fundamental_momentum": fm_score(fundamentals, snapshot),
        "value_quality":        vq_score(fundamentals, snapshot),
        "insider_conviction":   _insider(snapshot),
        "price_opportunity":    po_score(snapshot),
    }

    weights_pct = {k: round(v * 100) for k, v in _WEIGHTS.items()}

    available = {k: v for k, v in scores.items() if v["score"] is not None}
    if not available:
        return {**scores, "composite": {"score": None, "action": "N/A", "weights": weights_pct}}

    total_w   = sum(_WEIGHTS[k] for k in available)
    composite = round(sum(v["score"] * _WEIGHTS[k] / total_w for k, v in available.items()), 1)
    action    = next(label for threshold, label in _THRESHOLDS if composite >= threshold)

    return {**scores, "composite": {"score": composite, "action": action, "weights": weights_pct}}
