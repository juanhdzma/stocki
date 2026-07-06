from core.insider_score import compute_insider_score


def score(snapshot: dict, _funds: list[dict]) -> float | None:
    txs = snapshot.get("insider_transactions") or []
    if not txs:
        return None
    market_cap  = snapshot.get("market_cap")
    week52_low  = snapshot.get("week52_low")
    week52_high = snapshot.get("week52_high")
    result = compute_insider_score(
        txs, market_cap=market_cap,
        week52_low=week52_low, week52_high=week52_high,
        days_back=90,
    )
    score_val = result["score"]
    if result["valid_buys"] == 0 and result["valid_sells"] == 0:
        return None if result["raw_count"] == 0 else 0.0
    return score_val
