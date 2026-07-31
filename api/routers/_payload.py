from __future__ import annotations

import logging
import re
from datetime import date, timedelta

log = logging.getLogger(__name__)

_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")
_MAX_TICKERS = 200


def parse_ticker_csv(tickers: str) -> list[str]:
    """Parse a comma-separated ticker query param into an upper-cased, de-blanked, capped list."""
    return [t.strip().upper() for t in tickers.split(",") if t.strip()][:_MAX_TICKERS]


def build_payload(
    ticker: str,
    snap: dict,
    funds: list[dict],
    refreshed_at: str | None = None,
    week_ago_scores: dict | None = None,
    full: bool = True,
) -> dict:
    from core.scorers.composite import compute_all, diff_scores

    current_year = str(date.today().year)
    annuals = [f for f in funds if f.get("type") == "annual" and f.get("period") != current_year][
        :4
    ]
    quarterlies = [f for f in funds if f.get("type") == "quarterly"][:4]
    snap_data = {k: v for k, v in snap.items() if k not in ("returns", "insider_transactions")}
    market_cap = snap.get("market_cap")
    recent_fcf = next((f.get("fcf") for f in annuals if f.get("fcf") is not None), None)
    snap_data["fcf_yield"] = (
        (recent_fcf / market_cap) if (recent_fcf is not None and market_cap) else None
    )
    try:
        scores = compute_all(funds, snap)
    except Exception as exc:
        log.warning("[%s] score computation failed: %s", ticker, exc)
        scores = None
    score_change = diff_scores(week_ago_scores, scores) if scores is not None else None

    # The multi-ticker home payload (full=False) never renders annuals/quarterlies and only shows
    # the last ~2 ET days of insider filings (events.js), yet the whole thing stays resident in
    # state.watchlistData for the session. Trim it: the detail view re-fetches with full=1.
    insider_tx = snap.get("insider_transactions", [])
    if not full:
        cutoff = (date.today() - timedelta(days=3)).isoformat()
        insider_tx = [t for t in insider_tx if (t.get("filing_date") or "")[:10] >= cutoff]

    return {
        "snapshot": snap_data,
        "returns": snap.get("returns", {}),
        "annuals": [
            {"period": f["period"], **{k: v for k, v in f.items() if k not in ("type", "period")}}
            for f in annuals
        ]
        if full
        else [],
        "quarterlies": [
            {"period": f["period"], **{k: v for k, v in f.items() if k not in ("type", "period")}}
            for f in quarterlies
        ]
        if full
        else [],
        "insider_transactions": insider_tx,
        "scores": scores,
        "score_change": score_change,
        "refreshed_at": refreshed_at,
        "data_ready": len(quarterlies) >= 2,
    }
