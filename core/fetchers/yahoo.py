from __future__ import annotations
import os
import logging
import warnings
from typing import Any

import requests.exceptions
import yfinance as yf
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

# yfinance references requests.exceptions.DNSError (a curl_cffi attr) when falling
# back to requests — patch it so it doesn't blow up at call time.
if not hasattr(requests.exceptions, "DNSError"):
    requests.exceptions.DNSError = requests.exceptions.ConnectionError

logging.getLogger("yfinance").addFilter(
    type("_NoCurlWarning", (logging.Filter,), {
        "filter": lambda self, r: "curl_cffi" not in r.getMessage()
    })()
)

log = logging.getLogger(__name__)


def init_auth() -> bool:
    """Refresh Yahoo Finance crumb. Safe to call before every ticker fetch."""
    t = os.getenv("YAHOO_COOKIE_T", "").strip()
    y = os.getenv("YAHOO_COOKIE_Y", "").strip()
    if not (t and y):
        return False
    try:
        auth = yf.Auth()
        ok = auth.set_login_cookies(t, y)
        if ok:
            log.info("Yahoo Finance auth OK (tier: %s)", auth.subscription_tier())
        else:
            log.warning("Yahoo Finance auth failed — check T and Y cookie values")
        return ok
    except Exception as exc:
        log.error("Yahoo Finance auth error: %s", exc)
        return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if not pd.isna(x) else None
    except (TypeError, ValueError):
        return None


def _row(df: pd.DataFrame, *names: str) -> pd.Series | None:
    for name in names:
        if name in df.index:
            return df.loc[name]
    return None


def _period_key(ts: Any, kind: str) -> str:
    try:
        q = (ts.month - 1) // 3 + 1
        return f"{ts.year}-Q{q}" if kind == "quarterly" else str(ts.year)
    except Exception:
        return str(ts)


def _period_data(inc: pd.DataFrame | None, bs: pd.DataFrame | None,
                 cf: pd.DataFrame | None, col: Any, kind: str) -> dict:
    def g(df, *names):
        if df is None:
            return None
        s = _row(df, *names)
        if s is None:
            return None
        return _f(s.get(col))

    revenue = g(inc, "Total Revenue", "Revenue")
    gross_profit = g(inc, "Gross Profit", "Gross profit")
    ebit = g(inc, "EBIT", "Operating Income", "Ebit")
    net_income = g(inc, "Net Income", "Net Income Common Stockholders", "Net Income Continuous Operations")
    rd = g(inc, "Research And Development", "Research And Development Expenses", "Research Development")
    tax = g(inc, "Tax Provision", "Income Tax Expense", "Income Tax Expense Benefit")
    pretax = g(inc, "Pretax Income", "Income Before Tax", "Pre Tax Income")
    interest_exp = g(inc, "Interest Expense",
                     "Interest Expense Non Operating",
                     "Interest Expense Operating",
                     "Net Non Operating Interest Income Expense",
                     "Total Other Finance Cost",
                     "Net Interest Income")

    total_assets = g(bs, "Total Assets")
    current_assets = g(bs, "Current Assets")
    current_liabilities = g(bs, "Current Liabilities")
    retained_earnings = g(bs, "Retained Earnings")
    total_debt = g(bs, "Total Debt", "Long Term Debt")
    total_equity = g(bs, "Stockholders Equity", "Total Equity Gross Minority Interest",
                     "Common Stock Equity")
    total_liabilities = g(bs, "Total Liabilities Net Minority Interest", "Total Liabilities")
    shares = g(bs, "Ordinary Shares Number", "Share Issued", "Common Stock")
    cash = g(bs, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments",
             "Cash And Short Term Investments")

    fcf = g(cf, "Free Cash Flow")
    buybacks = g(cf, "Repurchase Of Capital Stock", "Common Stock Repurchase",
                 "Repurchase Of Common Stock", "Purchase Of Stock",
                 "Repurchase Of Capital Stock And Equity",
                 "Purchase Of Business")
    ocf = g(cf, "Operating Cash Flow", "Cash From Operating Activities")

    gross_margin = (gross_profit / revenue) if (revenue and gross_profit) else None

    return {
        "type": kind,
        "revenue": revenue,
        "gross_profit": gross_profit,
        "gross_margin": gross_margin,
        "ebit": ebit,
        "net_income": net_income,
        "rd_expense": rd,
        "income_tax_expense": tax,
        "pretax_income": pretax,
        "total_assets": total_assets,
        "current_assets": current_assets,
        "current_liabilities": current_liabilities,
        "retained_earnings": retained_earnings,
        "total_debt": total_debt,
        "total_equity": total_equity,
        "total_liabilities": total_liabilities,
        "shares_outstanding": shares,
        "cash": cash,
        "fcf": fcf,
        "buybacks": buybacks,
        "interest_expense": interest_exp,
        "operating_cash_flow": ocf,
    }


# ── Bulk price download ───────────────────────────────────────────────────────

def batch_download_history(tickers: list[str]) -> pd.DataFrame:
    """Single bulk download: all tickers + SPY, 2y daily. Returns MultiIndex DataFrame."""
    all_syms = list(dict.fromkeys([t.upper() for t in tickers] + ["SPY"]))
    return yf.download(all_syms, period="2y", interval="1d", auto_adjust=True, progress=False)


# ── 1W high ───────────────────────────────────────────────────────────────────

def _compute_1w_pct(ticker: str, price: float | None, hist: pd.DataFrame | None = None) -> float | None:
    try:
        if hist is not None and not hist.empty:
            highs_all = hist["High"]
            highs = highs_all[ticker] if ticker in highs_all.columns else pd.Series(dtype=float)
            highs = highs.dropna().tail(5)
        else:
            raw = yf.download(ticker, period="5d", interval="1d", auto_adjust=True, progress=False)
            if raw.empty:
                return None
            highs = raw["High"]
            if isinstance(highs, pd.DataFrame):
                highs = highs[ticker]
            highs = highs.dropna()

        if highs.empty or not price:
            return None
        h1w = float(highs.max())
        return (price - h1w) / h1w
    except Exception:
        return None


# ── Price returns vs SPY ──────────────────────────────────────────────────────

def _compute_returns(ticker: str, hist: pd.DataFrame | None = None) -> dict[str, float | None]:
    try:
        if hist is not None and not hist.empty:
            closes = hist["Close"]
        else:
            raw = yf.download([ticker, "SPY"], period="2y", interval="1d", auto_adjust=True, progress=False)
            closes = raw["Close"]
            if isinstance(closes, pd.Series):
                closes = closes.to_frame(name=ticker)

        result: dict[str, float | None] = {}
        periods = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}

        for label, days in periods.items():
            for sym in [ticker, "SPY"]:
                key = f"ticker_return_{label}" if sym == ticker else f"spy_return_{label}"
                try:
                    series = closes[sym].dropna() if sym in closes.columns else pd.Series(dtype=float)
                    if len(series) > days:
                        r = (series.iloc[-1] - series.iloc[-days]) / series.iloc[-days]
                        result[key] = float(r)
                    else:
                        result[key] = None
                except Exception:
                    result[key] = None

        return result
    except Exception:
        return {}


# ── Dilution rate (YoY shares change) ────────────────────────────────────────

def _compute_dilution_rate(t: yf.Ticker) -> float | None:
    try:
        bs = t.balance_sheet
        if bs is None or bs.empty:
            return None
        row = _row(bs, "Ordinary Shares Number", "Share Issued", "Common Stock")
        if row is None:
            return None
        vals = [_f(v) for v in row]
        vals = [v for v in vals if v is not None]
        if len(vals) < 2:
            return None
        return (vals[0] - vals[1]) / vals[1]
    except Exception:
        return None


# ── Put/Call ratio ────────────────────────────────────────────────────────────

def _compute_put_call(t: yf.Ticker, max_expirations: int = 8) -> float | None:  # noqa: E501
    try:
        expirations = t.options[:max_expirations]
        if not expirations:
            return None
        total_calls = 0
        total_puts = 0
        for exp in expirations:
            chain = t.option_chain(exp)
            total_calls += chain.calls["openInterest"].fillna(0).sum()
            total_puts += chain.puts["openInterest"].fillna(0).sum()
        if total_calls == 0:
            return None
        return round(total_puts / total_calls, 4)
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_market_snapshot(ticker: str, hist: pd.DataFrame | None = None) -> dict:
    t = yf.Ticker(ticker)
    info = t.info or {}

    price = _f(info.get("currentPrice") or info.get("regularMarketPrice"))
    market_cap = _f(info.get("marketCap"))

    # All yf.Ticker calls must happen before _compute_returns — yf.download invalidates the crumb
    pc_ratio = _compute_put_call(t)
    dilution_rate = _compute_dilution_rate(t)

    _rec_counts: dict = {}
    try:
        df = t.recommendations
        if df is not None and not df.empty:
            cur = df[df["period"] == "0m"]
            if not cur.empty:
                row = cur.iloc[0]
                _rec_counts = {
                    "rec_strong_buy":  int(row.get("strongBuy",  0)),
                    "rec_buy":         int(row.get("buy",        0)),
                    "rec_hold":        int(row.get("hold",       0)),
                    "rec_sell":        int(row.get("sell",       0)),
                    "rec_strong_sell": int(row.get("strongSell", 0)),
                }
    except Exception:
        pass

    returns = _compute_returns(ticker, hist)
    pct_from_1w_high = _compute_1w_pct(ticker, price, hist)

    week52_high = _f(info.get("fiftyTwoWeekHigh"))
    pct_from_52w_high = (price - week52_high) / week52_high if (price and week52_high) else None

    return {
        # Price & market
        "name":                       info.get("longName") or info.get("shortName"),
        "price":                      price,
        "market_cap":                 market_cap,
        "enterprise_value":           _f(info.get("enterpriseValue")),
        "week52_low":                 _f(info.get("fiftyTwoWeekLow")),
        "week52_high":                week52_high,
        "pct_from_52w_high":          pct_from_52w_high,
        "pct_from_1w_high":           pct_from_1w_high,
        "beta":                       _f(info.get("beta")),
        "average_volume":             _f(info.get("averageVolume")),
        "shares_outstanding":         _f(info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")),
        "sector":                     info.get("sector"),
        "industry":                   info.get("industry"),
        # Valuation multiples (current)
        "trailing_pe":                _f(info.get("trailingPE")),
        "forward_pe":                 _f(info.get("forwardPE")),
        "peg_ratio":                  _f(info.get("pegRatio")),
        "eps_ttm":                    _f(info.get("trailingEps")),
        "price_to_sales":             _f(info.get("priceToSalesTrailing12Months")),
        "ev_to_revenue":              _f(info.get("enterpriseToRevenue")),
        # Margins & returns (current)
        "gross_margin":               _f(info.get("grossMargins")),
        "operating_margin":           _f(info.get("operatingMargins")),
        "net_margin":                 _f(info.get("profitMargins")),
        "roe":                        _f(info.get("returnOnEquity")),
        "roa":                        _f(info.get("returnOnAssets")),
        # Growth (YoY)
        "revenue_growth":             _f(info.get("revenueGrowth")),
        "earnings_growth":            _f(info.get("earningsGrowth")),
        "dilution_rate":              dilution_rate,
        # Liquidity & leverage (current)
        "current_ratio":              _f(info.get("currentRatio")),
        "quick_ratio":                _f(info.get("quickRatio")),
        "debt_to_equity":             _f(info.get("debtToEquity")),
        # Ownership
        "held_pct_insiders":          _f(info.get("heldPercentInsiders")),
        "held_pct_institutions":      _f(info.get("heldPercentInstitutions")),
        "short_percent_of_float":     _f(info.get("shortPercentOfFloat")),
        "short_ratio":                _f(info.get("shortRatio")),
        # Analyst
        "target_low":                 _f(info.get("targetLowPrice")),
        "target_mean":                _f(info.get("targetMeanPrice")),
        "target_high":                _f(info.get("targetHighPrice")),
        "analyst_count":              _f(info.get("numberOfAnalystOpinions")),
        "recommendation_mean":        _f(info.get("recommendationMean")),
        "recommendation_key":         info.get("recommendationKey"),
        **_rec_counts,
        # Options
        "put_call_ratio": pc_ratio,
        "returns": returns,
        "insider_transactions": [],
    }


def fetch_fundamentals(ticker: str) -> list[tuple[str, dict]]:
    """Returns list of (period_key, data) ready for write_fundamentals()."""
    t = yf.Ticker(ticker)

    def _safe_df(attr: str) -> pd.DataFrame | None:
        try:
            df = getattr(t, attr, None)
            if df is None:
                return None
            return df if not df.empty else None
        except Exception:
            return None

    def _first(*attrs: str) -> pd.DataFrame | None:
        for attr in attrs:
            df = _safe_df(attr)
            if df is not None:
                return df
        return None

    q_inc = _first("quarterly_income_stmt", "quarterly_financials")
    q_bs  = _safe_df("quarterly_balance_sheet")
    q_cf  = _safe_df("quarterly_cashflow")
    a_inc = _first("income_stmt", "financials")
    a_bs  = _safe_df("balance_sheet")
    a_cf  = _safe_df("cashflow")

    results: list[tuple[str, dict]] = []

    ref_df = q_inc if q_inc is not None else (q_bs if q_bs is not None else q_cf)
    if ref_df is not None:
        for col in ref_df.columns:
            key = _period_key(col, "quarterly")
            data = _period_data(q_inc, q_bs, q_cf, col, "quarterly")
            results.append((key, data))

    ref_df = a_inc if a_inc is not None else (a_bs if a_bs is not None else a_cf)
    if ref_df is not None:
        for col in ref_df.columns:
            key = _period_key(col, "annual")
            data = _period_data(a_inc, a_bs, a_cf, col, "annual")
            results.append((key, data))

    return results
