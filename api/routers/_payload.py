from __future__ import annotations
import logging
from datetime import date

log = logging.getLogger(__name__)


def build_payload(
    ticker: str,
    snap: dict,
    funds: list[dict],
    refreshed_at: str | None = None,
) -> dict:
    from core.scorers.composite import compute_all

    current_year = str(date.today().year)
    annuals     = [f for f in funds if f.get("type") == "annual" and f.get("period") != current_year][:4]
    quarterlies = [f for f in funds if f.get("type") == "quarterly"][:4]
    snap_data   = {k: v for k, v in snap.items() if k not in ("returns", "insider_transactions")}
    market_cap  = snap.get("market_cap")
    recent_fcf  = next((f.get("fcf") for f in annuals if f.get("fcf") is not None), None)
    snap_data["fcf_yield"] = (recent_fcf / market_cap) if (recent_fcf and market_cap) else None
    try:
        scores = compute_all(funds, snap)
    except Exception as exc:
        log.warning("[%s] score computation failed: %s", ticker, exc)
        scores = None
    return {
        "snapshot":             snap_data,
        "returns":              snap.get("returns", {}),
        "annuals":              [{"period": f["period"], **{k: v for k, v in f.items() if k not in ("type", "period")}} for f in annuals],
        "quarterlies":          [{"period": f["period"], **{k: v for k, v in f.items() if k not in ("type", "period")}} for f in quarterlies],
        "insider_transactions": snap.get("insider_transactions", []),
        "scores":               scores,
        "refreshed_at":         refreshed_at,
        "data_ready":           len(quarterlies) >= 2,
    }
