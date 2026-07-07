"""
Insider conviction score (-100 to +100) for a single ticker.
"""
from __future__ import annotations
import re
import bisect
from datetime import datetime, timedelta, timezone


# ── Role classification ───────────────────────────────────────────────────────

_ROLE_ORDER = [
    ("CEO",   ["CEO", "CHIEF EXECUTIVE", "PRESIDENT", "CHAIRMAN"]),
    ("CFO",   ["CFO", "CHIEF FINANCIAL"]),
    ("COO",   ["COO", "CTO", "CHIEF OPERATING", "CHIEF TECHNOLOGY"]),
    ("SVP",   ["SVP", "EVP", "SR. VP", "SENIOR VP", "GC", "GENERAL COUNSEL", "CHIEF "]),
    ("DIR",   ["DIRECTOR", " DIR", ",DIR"]),
    ("10PCT", ["10%", "10 %", "BENEFICIAL OWNER"]),
    ("VP",    ["VP", "VICE PRES", "OFFICER", "PRINCIPAL"]),
]

_CONV_MULT = {"CEO": 1.00, "CFO": 0.90, "COO": 0.85, "SVP": 0.80,
              "DIR": 0.55, "VP": 0.40, "10PCT": 0.30, "OTHER": 0.25}
_ROLE_PTS  = {"CEO": 20,   "CFO": 17,   "COO": 15,   "SVP": 11,
              "DIR": 8,    "VP": 5,     "10PCT": 3,   "OTHER": 2}


def _role(title: str) -> str:
    t = (" " + (title or "").upper() + " ")
    for role, patterns in _ROLE_ORDER:
        if any(p in t for p in patterns):
            return role
    return "OTHER"


# ── Parse helpers ─────────────────────────────────────────────────────────────

def _parse_type(raw: str) -> str:
    raw = (raw or "").strip()
    if "+OE" in raw:
        return "S+OE"
    m = re.match(r"^([A-Z])", raw)
    return m.group(1) if m else raw


def _parse_dt(v) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(v)[:19], fmt)
        except ValueError:
            pass
    return None


def _parse_pct(v) -> float | None:
    try:
        return float(str(v).replace("%", "").replace("+", "").strip()) / 100
    except Exception:
        return None


def _parse_usd(v) -> float | None:
    try:
        return abs(float(re.sub(r"[^\d.-]", "", str(v))))
    except Exception:
        return None


# ── Step 1: Filter ────────────────────────────────────────────────────────────

_EXCLUDE = {"A", "G", "W", "F", "D", "C"}


def normalize(raw: list[dict]) -> list[dict]:
    out = []
    for t in raw:
        out.append({
            "insider_name": str(t.get("insider_name") or t.get("Insider Name") or ""),
            "title":        str(t.get("title")        or t.get("Title")         or ""),
            "trade_type":   _parse_type(str(t.get("trade_type") or t.get("Trade Type") or "")),
            "delta_own":    t["delta_own"] if "delta_own" in t and t["delta_own"] is not None
                            else _parse_pct(t.get("ΔOwn")),
            "value_usd":    t["value_usd"] if "value_usd" in t and t["value_usd"] is not None
                            else _parse_usd(t.get("Value")),
            "price":        t["price"] if "price" in t and t["price"] is not None
                            else _parse_usd(t.get("Price")),
            "trade_date":   _parse_dt(t.get("trade_date") or t.get("Trade Date")),
            "filing_date":  _parse_dt(t.get("filing_date") or t.get("Filing Date")),
        })
    return out


def _filter(txs: list[dict], market_cap: float | None = None) -> list[dict]:
    # Index S dates per insider for M/X retention check
    s_dates: dict[str, list[datetime]] = {}
    for tx in txs:
        if tx["trade_type"] == "S" and tx["trade_date"]:
            s_dates.setdefault(tx["insider_name"], []).append(tx["trade_date"])

    valid = []
    for tx in txs:
        tt  = tx["trade_type"]
        own = tx["delta_own"]
        nm  = tx["insider_name"]
        td  = tx["trade_date"]

        if tt in _EXCLUDE:
            continue

        if tt == "S+OE":
            # Only include if ΔOwn < -10% (meaningful position reduction)
            if own is None or own >= -0.10:
                continue

        elif tt == "S":
            cap = market_cap or 1e12
            if cap < 10e9:    threshold = -0.03
            elif cap < 500e9: threshold = -0.05
            else:             threshold = -0.10
            if own is None or own > threshold:
                continue

        elif tt in ("M", "X"):
            # Bullish retention: no S within 2 days after exercise
            has_s_after = any(
                timedelta(0) <= s_dt - td <= timedelta(days=2)
                for s_dt in s_dates.get(nm, [])
            ) if td else False
            if has_s_after:
                continue
            tx = {**tx, "trade_type": "P_RETENTION"}

        elif tt != "P":
            continue

        valid.append(tx)

    return valid


# ── Step 2: Transaction score (0-100) ─────────────────────────────────────────

def _tx_score(tx: dict, market_cap: float | None,
              w52_low: float | None, w52_high: float | None) -> float:
    role   = _role(tx["title"])
    own_a  = abs(tx["delta_own"] or 0)
    val    = tx["value_usd"] or 0
    tt     = tx["trade_type"]
    price  = tx["price"] or 0
    td     = tx["trade_date"]
    fd     = tx["filing_date"]
    is_buy = tt in ("P", "P_RETENTION")

    # CONVICTION (0-30) × role multiplier
    if own_a > 0.50:   c = 30
    elif own_a > 0.40: c = 24
    elif own_a > 0.30: c = 18
    elif own_a > 0.20: c = 12
    elif own_a > 0.10: c =  6
    else:
        # Floor by absolute value when ΔOwn ≈ 0% (e.g. large holder, tiny % change)
        if val > 500_000:   c = 4
        elif val > 200_000: c = 2
        elif val > 100_000: c = 1
        else:               c = 0
    conviction = c * _CONV_MULT.get(role, 0.25)

    # WEIGHT (0-20) × cap adjustment
    if val > 50_000_000:   w = 20
    elif val > 10_000_000: w = 16
    elif val > 5_000_000:  w = 12
    elif val > 1_000_000:  w =  8
    elif val > 500_000:    w =  5
    elif val > 100_000:    w =  2
    else:                  w =  0

    cap = market_cap or 0
    if cap < 2e9:     cm = 1.5
    elif cap < 10e9:  cm = 1.2
    elif cap < 100e9: cm = 1.0
    elif cap < 500e9: cm = 0.7
    else:             cm = 0.5
    weight = min(20, w * cm)

    # ROLE (0-20) — penalize mega cap (routine comp sales inflate score)
    role_pts = _ROLE_PTS.get(role, 2)
    if (market_cap or 0) >= 500e9:
        role_pts = int(role_pts * 0.6)

    # URGENCY (0-10)
    urgency = 0
    if fd and td:
        delay = (fd - td).days
        if delay <= 1:   urgency += 5
        elif delay <= 3: urgency += 3
        elif delay <= 5: urgency += 1

    if price:
        if is_buy and w52_low and price <= w52_low * 1.10:
            urgency += 3
        if not is_buy and w52_high and price >= w52_high * 0.90:
            urgency += 2

    if tx.get("first_trade"):
        urgency += 2

    urgency = min(10, urgency)

    return min(100.0, conviction + weight + role_pts + urgency)


# ── Step 3: Cluster & Persistence ─────────────────────────────────────────────

def _cluster(txs: list[dict]) -> float:
    if not txs:
        return 0.0
    dated = sorted(
        [(tx["trade_date"], tx) for tx in txs if tx.get("trade_date")],
        key=lambda x: x[0],
    )
    if not dated:
        return 0.0

    dates = [d for d, _ in dated]
    window = timedelta(days=60)
    best_n, best_ceo = 0, False
    for i, (anchor, _) in enumerate(dated):
        j = bisect.bisect_right(dates, anchor + window)
        in_w = [tx for _, tx in dated[i:j]]
        names = {tx["insider_name"] for tx in in_w}
        if len(names) > best_n:
            best_n   = len(names)
            best_ceo = any(_role(tx["title"]) == "CEO" for tx in in_w)

    if best_n >= 10:  pts = 30
    elif best_n >= 6: pts = 22
    elif best_n >= 4: pts = 15
    elif best_n == 3: pts = 10
    elif best_n == 2: pts =  5
    else:             pts =  0

    if best_n >= 4:
        pts = min(30, int(pts * 1.4))

    return min(20.0, pts + (5 if best_ceo else 0))


def _persistence(txs: list[dict]) -> float:
    if not txs:
        return 0.0
    by_insider: dict[str, list[datetime]] = {}
    for tx in txs:
        if tx.get("trade_date"):
            by_insider.setdefault(tx["insider_name"], []).append(tx["trade_date"])

    best = 0.0
    for dates in by_insider.values():
        n = len(dates)
        if n >= 4:   pts = 10
        elif n == 3: pts =  7
        elif n == 2: pts =  4
        else:        pts =  0

        if n >= 2:
            dates_s = sorted(dates)
            if (dates_s[-1] - dates_s[0]).days < 30:
                pts = min(10, pts + 3)
        best = max(best, pts)
    return best


# ── Step 4: Final score ───────────────────────────────────────────────────────

def compute_insider_score(
    transactions_raw: list[dict],
    market_cap: float | None = None,
    week52_low: float | None = None,
    week52_high: float | None = None,
    days_back: int = 365,
    _already_normalized: bool = False,
) -> dict:
    """
    Returns dict with keys: score (-100..+100), bull, bear, valid_buys, valid_sells.
    transactions_raw fields (OpenInsider naming or normalized):
        insider_name / Insider Name
        title / Title
        trade_type / Trade Type  (raw string like 'P - Purchase')
        delta_own / ΔOwn         (fraction or '%-string')
        value_usd / Value        (number or '$-string')
        price / Price
        trade_date / Trade Date
        filing_date / Filing Date
    Pass _already_normalized=True when the caller has already run normalize() on the data.
    """
    txs = transactions_raw if _already_normalized else normalize(transactions_raw)
    # .replace(tzinfo=None): normalize() always produces naive trade_date; cutoff must match
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_back)
    txs = [tx for tx in txs if tx.get("trade_date") and tx["trade_date"] >= cutoff]
    raw_count = len(txs)
    valid = _filter(txs, market_cap)

    # Mark first trade per insider (chronological)
    seen: set[str] = set()
    for tx in sorted(valid, key=lambda x: x["trade_date"] or datetime.min):
        tx["first_trade"] = tx["insider_name"] not in seen
        seen.add(tx["insider_name"])

    buys  = [tx for tx in valid if tx["trade_type"] in ("P", "P_RETENTION")]
    sells = [tx for tx in valid if tx["trade_type"] in ("S", "S+OE")]

    def _group_score(group: list[dict]) -> float:
        if not group:
            return 0.0
        scores  = [_tx_score(tx, market_cap, week52_low, week52_high) for tx in group]
        best_tx = max(scores)
        avg_tx  = sum(scores) / len(scores)
        rep_tx  = best_tx * 0.8 + avg_tx * 0.2
        return rep_tx + _cluster(group) + _persistence(group)

    raw_bull = _group_score(buys)
    raw_bear = _group_score(sells)

    MAX_RAW = 130.0  # max: rep_tx(100) + cluster(20) + persist(10) = 130
    bull_norm = min(100.0, (raw_bull / MAX_RAW) * 100)
    bear_norm = min(100.0, (raw_bear / MAX_RAW) * 100)

    if buys and not sells:
        final = +bull_norm
    elif sells and not buys:
        final = -bear_norm
    else:
        final = bull_norm - bear_norm

    return {
        "score":       round(final, 1),
        "bull":        round(raw_bull, 1),
        "bear":        round(raw_bear, 1),
        "valid_buys":  len(buys),
        "valid_sells": len(sells),
        "raw_count":   raw_count,
    }
