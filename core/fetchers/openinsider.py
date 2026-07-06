from __future__ import annotations

import requests
from bs4 import BeautifulSoup

_BASE_URL = "https://openinsider.com/screener"
_TIMEOUT = 15
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockDesk/1.0)"}

_COL_MAP = {
    "Filing Date": "filing_date",
    "Trade Date": "trade_date",
    "Insider Name": "insider_name",
    "Title": "title",
    "Trade Type": "trade_type",
    # Price, ΔOwn, Value intentionally kept as original names so
    # insider_score._normalize() parses them via _parse_usd / _parse_pct
}


def fetch_insider_transactions(ticker: str, days_back: int = 365) -> list[dict] | None:
    """Returns list of transactions, empty list if none found, or None on network error."""
    params = {
        "s": ticker,
        "fd": days_back,
        "xp": 1,
        "xs": 1,
        "cnt": 100,
        "sortcol": 8,
        "o": 0,
    }
    try:
        resp = requests.get(_BASE_URL, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", class_="tinytable")
    if not table:
        return []

    thead = table.find("thead")
    if not thead:
        return []
    raw_headers = [th.get_text(strip=True).replace("\xa0", " ") for th in thead.find_all("th")]

    tbody = table.find("tbody")
    if not tbody:
        return []

    rows = []
    for tr in tbody.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) != len(raw_headers):
            continue
        raw = dict(zip(raw_headers, cells))
        normalized = {_COL_MAP.get(k, k): v for k, v in raw.items()}
        rows.append(normalized)

    return rows
