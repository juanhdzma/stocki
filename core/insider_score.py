"""
Insider conviction score (0-100).
50 = neutral | >50 = net buying | <50 = net selling
"""
from __future__ import annotations
import re
import math
from datetime import datetime, timedelta, timezone
from statistics import mean, stdev


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

_ROLE_WEIGHT = {
    "CEO": 1.00, "CFO": 0.90, "COO": 0.85, "SVP": 0.70,
    "DIR": 0.50, "VP": 0.40, "10PCT": 0.15, "OTHER": 0.20,
}


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
    s = str(v or "").replace("%", "").replace("+", "").strip()
    if ">" in s or "<" in s:
        return None  # >999% = new position; treated as max conviction in _tx_strength
    try:
        return float(s) / 100
    except Exception:
        return None


def _parse_usd(v) -> float | None:
    try:
        return abs(float(re.sub(r"[^\d.-]", "", str(v))))
    except Exception:
        return None


# ── Normalize ─────────────────────────────────────────────────────────────────

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


# ── Filter ────────────────────────────────────────────────────────────────────

_EXCLUDE = {"A", "G", "W", "F", "D", "C"}


def _min_value(market_cap: float | None) -> float:
    cap = market_cap or 0
    if cap < 1e9:    return 5_000
    if cap < 10e9:   return 15_000
    if cap < 100e9:  return 25_000
    return 50_000


def _filter(txs: list[dict], market_cap: float | None) -> list[dict]:
    min_val = _min_value(market_cap)
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
        val = tx["value_usd"] or 0

        if tt in _EXCLUDE:
            continue
        if val < min_val:
            continue

        if tt == "S+OE":
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


# ── Scheduled selling detection ───────────────────────────────────────────────

def _schedule_discount(trades: list[dict]) -> float:
    """Bear multiplier 0..1 for this insider. Lower = more routine/scheduled."""
    dates = sorted([t["trade_date"] for t in trades if t.get("trade_date")])
    if len(dates) < 3:
        return 1.0
    intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    m = mean(intervals)
    if m <= 0:
        return 1.0
    s = stdev(intervals) if len(intervals) > 1 else 0.0
    cv = s / m
    if 5 <= m <= 35:
        if cv < 0.30:  return 0.20  # highly scheduled → 80% discount
        if cv < 0.60:  return 0.50  # partially scheduled → 50% discount
    return 1.0


_POST_EARNINGS_WINDOW_DAYS = 10


def _is_post_earnings(trade_date: datetime | None, earnings_dates: list[str] | None) -> bool:
    if not trade_date or not earnings_dates:
        return False
    return any(
        (ed := _parse_dt(raw)) and 0 <= (trade_date - ed).days <= _POST_EARNINGS_WINDOW_DAYS
        for raw in earnings_dates
    )


# ── Transaction strength (0-100) ──────────────────────────────────────────────

def _tx_strength(
    tx: dict,
    market_cap: float | None,
    w52_low: float | None,
    w52_high: float | None,
) -> float:
    role   = _role(tx["title"])
    val    = tx["value_usd"] or 0
    own    = tx["delta_own"]
    price  = tx["price"] or 0
    td     = tx["trade_date"]
    fd     = tx["filing_date"]
    tt     = tx["trade_type"]
    is_buy = tt in ("P", "P_RETENTION")
    cap    = market_cap or 0

    # Size score (0-70) — relative to market cap; absolute fallback
    if cap > 0:
        rel = val / cap
        if rel > 0.01:      s = 70
        elif rel > 0.005:   s = 55
        elif rel > 0.001:   s = 40
        elif rel > 0.0002:  s = 25
        elif rel > 0.00005: s = 15
        else:               s = 5
    else:
        if val > 50_000_000:    s = 70
        elif val > 10_000_000:  s = 55
        elif val > 1_000_000:   s = 40
        elif val > 500_000:     s = 25
        elif val > 100_000:     s = 15
        else:                   s = 5

    # Conviction (0-20) — None means new position (>999% ΔOwn)
    if own is None:
        c = 20 if is_buy else 10
    elif abs(own) > 0.50: c = 20
    elif abs(own) > 0.30: c = 15
    elif abs(own) > 0.15: c = 10
    elif abs(own) > 0.05: c =  5
    else:                 c =  2

    # Urgency (0-10)
    u = 0
    if fd and td:
        delay = (fd - td).days
        if delay <= 1:    u += 4
        elif delay <= 3:  u += 2
        elif delay <= 5:  u += 1
    if is_buy and price and w52_low and price <= w52_low * 1.10:
        u += 4
    if not is_buy and price and w52_high and price >= w52_high * 0.90:
        u += 2
    u = min(10, u)

    return min(100.0, (s + c + u) * _ROLE_WEIGHT.get(role, 0.20))


# ── Time decay ────────────────────────────────────────────────────────────────

_HALF_LIFE_DAYS = 90.0


def _decay(trade_date: datetime, now: datetime) -> float:
    days = max(0, (now - trade_date).days)
    return math.pow(0.5, days / _HALF_LIFE_DAYS)


# ── Cluster bonus ─────────────────────────────────────────────────────────────

def _cluster_bonus(buys: list[dict]) -> float:
    dated = sorted(
        [tx for tx in buys if tx.get("trade_date")],
        key=lambda x: x["trade_date"],
    )
    if not dated:
        return 0.0
    best = 0
    window = timedelta(days=30)
    for anchor_tx in dated:
        anchor = anchor_tx["trade_date"]
        insiders = {
            tx["insider_name"] for tx in dated
            if timedelta(0) <= tx["trade_date"] - anchor <= window
        }
        best = max(best, len(insiders))
    if best >= 5:  return 25.0
    if best >= 3:  return 12.0
    return 0.0


# ── Post-earnings bonus ───────────────────────────────────────────────────────
# A trade placed shortly after earnings means the insider acted on fresh, real results.
# For buys that's a much higher-conviction bullish signal, so it gets amplified hard.
# For sells it's a much weaker signal — post-earnings selling is routine (diversification,
# tax planning) far more often than it's a bearish tell — so the bump stays small.
# Added flat (like the cluster bonus above) instead of multiplying inside _tx_strength,
# so it isn't swallowed by decay or the bull/bear ratio before it can move the needle.

_POST_EARNINGS_BUY_MULTIPLIER  = 1.8
_POST_EARNINGS_SELL_MULTIPLIER = 0.3


def _post_earnings_bonus(
    txs: list[dict],
    earnings_dates: list[str] | None,
    market_cap: float | None,
    w52_low: float | None,
    w52_high: float | None,
    multiplier: float,
    discounts: dict[str, float] | None = None,
) -> float:
    if not earnings_dates:
        return 0.0
    total = 0.0
    for tx in txs:
        if not _is_post_earnings(tx.get("trade_date"), earnings_dates):
            continue
        discount = discounts.get(tx["insider_name"], 1.0) if discounts else 1.0
        total += _tx_strength(tx, market_cap, w52_low, w52_high) * discount
    return multiplier * total


# ── Final score ───────────────────────────────────────────────────────────────

_MAX_ONE_SIDE = 150.0


def compute_insider_score(
    transactions_raw: list[dict],
    market_cap: float | None = None,
    week52_low: float | None = None,
    week52_high: float | None = None,
    days_back: int = 365,
    _already_normalized: bool = False,
    earnings_dates: list[str] | None = None,
) -> dict:
    """
    Returns dict with keys: score (0..100), valid_buys, valid_sells.
    50 = neutral | >50 = net buying | <50 = net selling.
    """
    txs = transactions_raw if _already_normalized else normalize(transactions_raw)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(days=days_back)
    txs = [tx for tx in txs if tx.get("trade_date") and tx["trade_date"] >= cutoff]
    valid = _filter(txs, market_cap)

    buys  = [tx for tx in valid if tx["trade_type"] in ("P", "P_RETENTION")]
    sells = [tx for tx in valid if tx["trade_type"] in ("S", "S+OE")]

    # Per-insider schedule discount; 10% holders get additional 50% cut
    by_seller: dict[str, list[dict]] = {}
    for tx in sells:
        by_seller.setdefault(tx["insider_name"], []).append(tx)

    discounts: dict[str, float] = {}
    for name, trades in by_seller.items():
        d = _schedule_discount(trades)
        if _role(trades[0]["title"]) == "10PCT":
            d *= 0.50
        discounts[name] = d

    bull_power = sum(
        _tx_strength(tx, market_cap, week52_low, week52_high) * _decay(tx["trade_date"], now)
        for tx in buys if tx.get("trade_date")
    ) + _cluster_bonus(buys) + _post_earnings_bonus(
        buys, earnings_dates, market_cap, week52_low, week52_high, _POST_EARNINGS_BUY_MULTIPLIER
    )

    bear_power = sum(
        _tx_strength(tx, market_cap, week52_low, week52_high)
        * _decay(tx["trade_date"], now)
        * discounts.get(tx["insider_name"], 1.0)
        for tx in sells if tx.get("trade_date")
    ) + _post_earnings_bonus(
        sells, earnings_dates, market_cap, week52_low, week52_high, _POST_EARNINGS_SELL_MULTIPLIER, discounts
    )

    if not buys and not sells:
        final = 50.0
    elif buys and not sells:
        final = 50.0 + min(50.0, bull_power / _MAX_ONE_SIDE * 50.0)
    elif sells and not buys:
        final = 50.0 - min(50.0, bear_power / _MAX_ONE_SIDE * 50.0)
    else:
        total = bull_power + bear_power
        final = (bull_power / total) * 100.0

    return {
        "score":       round(max(0.0, min(100.0, final)), 1),
        "valid_buys":  len(buys),
        "valid_sells": len(sells),
    }
