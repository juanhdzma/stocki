from __future__ import annotations

import logging
import os
import warnings
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
import pandas as pd
import requests.exceptions
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)

# yfinance references requests.exceptions.DNSError (a curl_cffi attr) when falling
# back to requests — patch it so it doesn't blow up at call time.
if not hasattr(requests.exceptions, "DNSError"):
    requests.exceptions.DNSError = requests.exceptions.ConnectionError

logging.getLogger("yfinance").addFilter(
    type(
        "_NoCurlWarning",
        (logging.Filter,),
        {"filter": lambda self, r: "curl_cffi" not in r.getMessage()},
    )()
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


def _period_data(
    inc: pd.DataFrame | None, bs: pd.DataFrame | None, cf: pd.DataFrame | None, col: Any, kind: str
) -> dict:
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
    net_income = g(
        inc, "Net Income", "Net Income Common Stockholders", "Net Income Continuous Operations"
    )
    rd = g(
        inc, "Research And Development", "Research And Development Expenses", "Research Development"
    )
    tax = g(inc, "Tax Provision", "Income Tax Expense", "Income Tax Expense Benefit")
    pretax = g(inc, "Pretax Income", "Income Before Tax", "Pre Tax Income")
    interest_exp = g(
        inc,
        "Interest Expense",
        "Interest Expense Non Operating",
        "Interest Expense Operating",
        "Net Non Operating Interest Income Expense",
        "Total Other Finance Cost",
        "Net Interest Income",
    )

    total_assets = g(bs, "Total Assets")
    current_assets = g(bs, "Current Assets")
    current_liabilities = g(bs, "Current Liabilities")
    retained_earnings = g(bs, "Retained Earnings")
    total_debt = g(bs, "Total Debt", "Long Term Debt")
    total_equity = g(
        bs, "Stockholders Equity", "Total Equity Gross Minority Interest", "Common Stock Equity"
    )
    total_liabilities = g(bs, "Total Liabilities Net Minority Interest", "Total Liabilities")
    shares = g(bs, "Ordinary Shares Number", "Share Issued", "Common Stock")
    cash = g(
        bs,
        "Cash And Cash Equivalents",
        "Cash Cash Equivalents And Short Term Investments",
        "Cash And Short Term Investments",
    )

    fcf = g(cf, "Free Cash Flow")
    buybacks = g(
        cf,
        "Repurchase Of Capital Stock",
        "Common Stock Repurchase",
        "Repurchase Of Common Stock",
        "Purchase Of Stock",
        "Repurchase Of Capital Stock And Equity",
        "Purchase Of Business",
    )
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


def batch_download_history(tickers: list[str], period: str = "2y") -> pd.DataFrame:
    """Single bulk download: all tickers + SPY. Returns MultiIndex DataFrame."""
    all_syms = list(dict.fromkeys([t.upper() for t in tickers] + ["SPY"]))
    return yf.download(all_syms, period=period, interval="1d", auto_adjust=True, progress=False)


def fetch_price_history(ticker: str, period: str = "1y") -> list[dict]:
    """Daily close prices for charting. Live fetch, not cached."""
    raw = yf.download(ticker, period=period, interval="1d", auto_adjust=True, progress=False)
    if raw.empty:
        return []
    closes = raw["Close"]
    if isinstance(closes, pd.DataFrame):
        closes = closes[ticker] if ticker in closes.columns else closes.iloc[:, 0]
    closes = closes.dropna()
    return [{"date": ts.strftime("%Y-%m-%d"), "close": float(v)} for ts, v in closes.items()]


# ── 1W high ───────────────────────────────────────────────────────────────────


def _compute_1w_pct(
    ticker: str, price: float | None, hist: pd.DataFrame | None = None
) -> float | None:
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
    except Exception as exc:
        log.debug("[%s] 1w-high computation failed: %s", ticker, exc)
        return None


# ── Price returns vs SPY ──────────────────────────────────────────────────────


def _compute_returns(ticker: str, hist: pd.DataFrame | None = None) -> dict[str, float | None]:
    try:
        if hist is not None and not hist.empty:
            closes = hist["Close"]
        else:
            raw = yf.download(
                [ticker, "SPY"], period="2y", interval="1d", auto_adjust=True, progress=False
            )
            closes = raw["Close"]
            if isinstance(closes, pd.Series):
                closes = closes.to_frame(name=ticker)

        result: dict[str, float | None] = {}
        periods = {"1w": 5, "1m": 21, "3m": 63, "6m": 126, "12m": 252}

        for label, days in periods.items():
            for sym in [ticker, "SPY"]:
                key = f"ticker_return_{label}" if sym == ticker else f"spy_return_{label}"
                try:
                    series = (
                        closes[sym].dropna() if sym in closes.columns else pd.Series(dtype=float)
                    )
                    if len(series) > days:
                        base = series.iloc[-days]
                        result[key] = float((series.iloc[-1] - base) / base) if base else None
                    elif label == "1m" and len(series) >= 2:
                        # A name younger than a month (fresh IPO/spinoff) has no 21-day-ago price:
                        # show the return since its first close ("1M or however long it's traded")
                        # instead of a blank. Only 1m falls back — 12m stays None so the NEW flag,
                        # which keys off ticker_return_12m is None, still fires for sub-year names.
                        base = series.iloc[0]
                        result[key] = float((series.iloc[-1] - base) / base) if base else None
                    else:
                        result[key] = None
                except Exception:
                    result[key] = None

        return result
    except Exception as exc:
        log.debug("[%s] returns computation failed: %s", ticker, exc)
        return {}


# ── Realized volatility (for buy_target's margin of safety) ───────────────────


_VOL_WINDOWS = {"1m": 21, "6m": 126, "12m": 252}  # trading days per horizon
_VOL_MIN_OBS = 20  # min closes for a trustworthy annualized stdev: below ~1 month, sqrt(252) on a
# tiny sample amplifies noise into absurd numbers (SKHY, 12 days → 183%), so return None → "n/d" tier


def _closes_series(ticker: str, hist: pd.DataFrame | None = None) -> pd.Series | None:
    """Adjusted daily closes for `ticker`: from the shared bulk `hist` if given, else a 1y download.
    Returns None only when a standalone download comes back empty (bulk-hist misses → empty Series)."""
    if hist is not None and not hist.empty:
        closes_all = hist["Close"]
        closes = closes_all[ticker] if ticker in closes_all.columns else pd.Series(dtype=float)
        return closes.dropna()
    raw = yf.download(ticker, period="1y", interval="1d", auto_adjust=True, progress=False)
    if raw.empty:
        return None
    closes = raw["Close"]
    if isinstance(closes, pd.DataFrame):
        closes = closes[ticker] if ticker in closes.columns else closes.iloc[:, 0]
    return closes.dropna()


def _compute_realized_vol(ticker: str, hist: pd.DataFrame | None = None) -> dict[str, float] | None:
    """Annualized realized volatility (stdev of daily returns) over 1m/6m/12m windows → dict.

    A robust "how much does this actually move" measure over three horizons; buy_target averages
    them for its margin-of-safety tier. The yfinance `beta` field is null for exactly the movers
    that matter (recent spinoffs/IPOs like SNDK), so this is used instead.
    """
    try:
        closes = _closes_series(ticker, hist)
        if closes is None:
            return None
        c = closes.to_numpy()
        if len(c) < _VOL_MIN_OBS:
            return None
        out = {}
        for name, w in _VOL_WINDOWS.items():
            seg = c[-w:]
            if len(seg) < _VOL_MIN_OBS:
                continue
            rets = np.diff(seg) / seg[:-1]
            out[name] = float(np.std(rets) * np.sqrt(252))
        return out or None
    except Exception as exc:
        log.debug("[%s] realized-vol computation failed: %s", ticker, exc)
        return None


_SMA_WINDOWS = {"50": 50, "200": 200}  # trading days per moving average


def _compute_moving_averages(
    ticker: str, hist: pd.DataFrame | None = None
) -> dict[str, float] | None:
    """Simple moving averages (50/200-day) of adjusted close → {window: sma}.

    A trend-support price level for buy_target's thin-analyst fallback anchor — a price-based
    level that, unlike analyst targets, carries no systematic upward bias. A window is emitted
    only when there are at least that many closes (SMA200 needs ~a full year of history).
    """
    try:
        closes = _closes_series(ticker, hist)
        if closes is None:
            return None
        c = closes.to_numpy()
        out = {name: float(np.mean(c[-w:])) for name, w in _SMA_WINDOWS.items() if len(c) >= w}
        return out or None
    except Exception as exc:
        log.debug("[%s] moving-average computation failed: %s", ticker, exc)
        return None


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
    except Exception as exc:
        log.debug("dilution-rate computation failed: %s", exc)
        return None


# ── Earnings dates ────────────────────────────────────────────────────────────


def _compute_earnings_dates(t: yf.Ticker, limit: int = 12) -> list[str]:
    try:
        df = t.get_earnings_dates(limit=limit)
        if df is None or df.empty:
            return []
        return sorted(d.strftime("%Y-%m-%d") for d in df.index if pd.notna(d))
    except Exception as exc:
        log.debug("earnings-dates fetch failed: %s", exc)
        return []


# ── Earnings execution track record ───────────────────────────────────────────


def _compute_earnings_beat_rate(t: yf.Ticker, quarters: int = 4) -> float | None:
    try:
        df = t.earnings_history
        if df is None or df.empty:
            return None
        recent = df.tail(quarters)
        vals = [
            (a, e)
            for a, e in zip(recent["epsActual"], recent["epsEstimate"], strict=False)
            if pd.notna(a) and pd.notna(e)
        ]
        if not vals:
            return None
        beats = sum(1 for a, e in vals if a > e)
        return beats / len(vals)
    except Exception as exc:
        log.debug("earnings-beat-rate computation failed: %s", exc)
        return None


# ── Analyst estimate revisions ────────────────────────────────────────────────


def _compute_eps_estimate_revision(t: yf.Ticker) -> tuple[float | None, float | None]:
    try:
        df = t.eps_trend
        if df is None or df.empty or "0y" not in df.index:
            return None, None
        row = df.loc["0y"]
        current = _f(row.get("current"))
        ago_90d = _f(row.get("90daysAgo"))
        return current, ago_90d
    except Exception as exc:
        log.debug("eps-estimate-revision fetch failed: %s", exc)
        return None, None


def _fetch_fx_rate(from_ccy: str | None, to_ccy: str | None) -> float | None:
    """Spot rate to convert `from_ccy` into `to_ccy` (e.g. DKK->USD for a Danish filer with a
    USD-priced ADR). Only fetched for foreign filers; None when same currency or unavailable."""
    if not from_ccy or not to_ccy or from_ccy == to_ccy:
        return None
    try:
        fi = yf.Ticker(f"{from_ccy}{to_ccy}=X").fast_info
        rate = fi.get("lastPrice") if hasattr(fi, "get") else fi.last_price
        return float(rate) if rate else None
    except Exception as exc:
        log.debug("fx-rate fetch %s->%s failed: %s", from_ccy, to_ccy, exc)
        return None


def _fetch_recommendation_counts(t: yf.Ticker) -> dict:
    try:
        df = t.recommendations
        if df is not None and not df.empty:
            cur = df[df["period"] == "0m"]
            if not cur.empty:
                row = cur.iloc[0]
                return {
                    "rec_strong_buy": int(row.get("strongBuy", 0)),
                    "rec_buy": int(row.get("buy", 0)),
                    "rec_hold": int(row.get("hold", 0)),
                    "rec_sell": int(row.get("sell", 0)),
                    "rec_strong_sell": int(row.get("strongSell", 0)),
                }
    except Exception as exc:
        log.debug("recommendation-counts fetch failed: %s", exc)
    return {}


# ── Public API ────────────────────────────────────────────────────────────────


def fetch_market_snapshot(ticker: str, hist: pd.DataFrame | None = None) -> dict:
    t = yf.Ticker(ticker)
    info = t.info or {}
    if not info.get("currentPrice") and not info.get("regularMarketPrice"):
        log.warning("[%s] info empty — re-authing and retrying", ticker)
        init_auth()
        t = yf.Ticker(ticker)
        info = t.info or {}

    price = _f(info.get("currentPrice") or info.get("regularMarketPrice"))
    market_cap = _f(info.get("marketCap"))

    # All yf.Ticker calls must happen before _compute_returns — yf.download invalidates the
    # crumb. These are independent Yahoo endpoints, so fan them out instead of running them
    # serially (measured ~5.8s/ticker serial). Each gets its own yf.Ticker instance — sharing
    # one across threads serializes internally (a shared session/cache lock), erasing the gain.
    with ThreadPoolExecutor(max_workers=4) as ex:
        fut_dilution = ex.submit(_compute_dilution_rate, yf.Ticker(ticker))
        fut_beat = ex.submit(_compute_earnings_beat_rate, yf.Ticker(ticker))
        fut_eps = ex.submit(_compute_eps_estimate_revision, yf.Ticker(ticker))
        fut_rec = ex.submit(_fetch_recommendation_counts, yf.Ticker(ticker))
        dilution_rate = fut_dilution.result()
        earnings_beat_rate = fut_beat.result()
        eps_estimate_curr_fy, eps_estimate_curr_fy_90d_ago = fut_eps.result()
        _rec_counts = fut_rec.result()

    returns = _compute_returns(ticker, hist)
    pct_from_1w_high = _compute_1w_pct(ticker, price, hist)
    realized_vol_windows = _compute_realized_vol(ticker, hist)
    realized_vol = (
        sum(realized_vol_windows.values()) / len(realized_vol_windows)
        if realized_vol_windows
        else None
    )
    moving_averages = _compute_moving_averages(ticker, hist)

    # Price sanity: a spurious quote (split-mismatch, bad tick) deviates wildly from the prior
    # close. Flag it so scores built on it can be treated with suspicion instead of silently
    # trusted — and don't let such a spike self-clamp the 52w high (which would hide it).
    prev_close = _f(info.get("regularMarketPreviousClose") or info.get("previousClose"))
    price_suspect = bool(prev_close and price and abs(price / prev_close - 1) > 0.5)

    week52_high = _f(info.get("fiftyTwoWeekHigh"))
    if price and week52_high and price > week52_high and not price_suspect:
        week52_high = price
    pct_from_52w_high = (price - week52_high) / week52_high if (price and week52_high) else None

    day_change_pct = _f(info.get("regularMarketChangePercent"))

    ath = week52_high

    return {
        # Price & market
        "name": info.get("longName") or info.get("shortName"),
        "price": price,
        "market_cap": market_cap,
        "enterprise_value": _f(info.get("enterpriseValue")),
        "week52_low": _f(info.get("fiftyTwoWeekLow")),
        "week52_high": week52_high,
        "pct_from_52w_high": pct_from_52w_high,
        "pct_from_1w_high": pct_from_1w_high,
        "realized_vol": realized_vol,
        "realized_vol_windows": realized_vol_windows,
        "moving_averages": moving_averages,
        "day_change_pct": day_change_pct,
        "ath": ath,
        "beta": _f(info.get("beta")),
        "average_volume": _f(info.get("averageVolume")),
        "shares_outstanding": _f(
            info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
        ),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("currency"),
        "financial_currency": info.get("financialCurrency"),
        # FX rate financial_currency -> price currency, so scores can convert local-currency
        # fundamentals (FCF) into the price currency instead of dropping the signal entirely.
        "fx_rate": _fetch_fx_rate(info.get("financialCurrency"), info.get("currency")),
        # Valuation multiples (current)
        "trailing_pe": _f(info.get("trailingPE")),
        "forward_pe": _f(info.get("forwardPE")),
        "peg_ratio": _f(info.get("pegRatio")),
        "eps_ttm": _f(info.get("trailingEps")),
        "price_to_sales": _f(info.get("priceToSalesTrailing12Months")),
        "ev_to_revenue": _f(info.get("enterpriseToRevenue")),
        "ev_to_ebitda": _f(info.get("enterpriseToEbitda")),
        # Margins & returns (current)
        "gross_margin": _f(info.get("grossMargins")),
        "operating_margin": _f(info.get("operatingMargins")),
        "net_margin": _f(info.get("profitMargins")),
        "roe": _f(info.get("returnOnEquity")),
        "roa": _f(info.get("returnOnAssets")),
        # Growth (YoY)
        "revenue_growth": _f(info.get("revenueGrowth")),
        "earnings_growth": _f(info.get("earningsGrowth")),
        "dilution_rate": dilution_rate,
        "earnings_beat_rate": earnings_beat_rate,
        "eps_estimate_curr_fy": eps_estimate_curr_fy,
        "eps_estimate_curr_fy_90d_ago": eps_estimate_curr_fy_90d_ago,
        # Liquidity & leverage (current)
        "current_ratio": _f(info.get("currentRatio")),
        "quick_ratio": _f(info.get("quickRatio")),
        "debt_to_equity": _f(info.get("debtToEquity")),
        # Ownership
        "held_pct_insiders": _f(info.get("heldPercentInsiders")),
        "held_pct_institutions": _f(info.get("heldPercentInstitutions")),
        "short_percent_of_float": _f(info.get("shortPercentOfFloat")),
        "short_ratio": _f(info.get("shortRatio")),
        # Analyst
        "target_low": _f(info.get("targetLowPrice")),
        "target_mean": _f(info.get("targetMeanPrice")),
        "target_median": _f(info.get("targetMedianPrice")),
        "target_high": _f(info.get("targetHighPrice")),
        "analyst_count": _f(info.get("numberOfAnalystOpinions")),
        "recommendation_mean": _f(info.get("recommendationMean")),
        "recommendation_key": info.get("recommendationKey"),
        **_rec_counts,
        "price_suspect": price_suspect,
        "returns": returns,
        "insider_transactions": [],
        "earnings_dates": [],
    }


def fetch_earnings_dates(ticker: str) -> list[str]:
    return _compute_earnings_dates(yf.Ticker(ticker))


def fetch_grade_history(ticker: str) -> list[dict]:
    """Dated analyst rating/target changes (yfinance upgrades_downgrades). Each firm's most
    recent row on/before a date is its active rating+target then — enough to reconstruct the
    recommendation distribution and mean target as they stood on any past date (backtesting)."""
    try:
        df = yf.Ticker(ticker).upgrades_downgrades
        if df is None or df.empty:
            return []
        out = []
        for gd, row in df.iterrows():
            out.append(
                {
                    "date": gd.strftime("%Y-%m-%d"),
                    "firm": str(row.get("Firm") or "").strip(),
                    "to_grade": str(row.get("ToGrade") or "").strip(),
                    "target": _f(row.get("currentPriceTarget")),
                }
            )
        return out
    except Exception as exc:
        log.debug("[%s] grade-history fetch failed: %s", ticker, exc)
        return []


def fetch_fundamentals(ticker: str) -> list[tuple[str, dict]]:
    """Returns list of (period_key, data) ready for write_fundamentals()."""
    t = yf.Ticker(ticker)

    def _safe_df(attr: str) -> pd.DataFrame | None:
        try:
            df = getattr(t, attr, None)
            if df is None:
                return None
            return df if not df.empty else None
        except Exception as exc:
            log.debug("[%s] fundamentals dataframe '%s' unavailable: %s", ticker, attr, exc)
            return None

    def _first(*attrs: str) -> pd.DataFrame | None:
        for attr in attrs:
            df = _safe_df(attr)
            if df is not None:
                return df
        return None

    q_inc = _first("quarterly_income_stmt", "quarterly_financials")
    q_bs = _safe_df("quarterly_balance_sheet")
    q_cf = _safe_df("quarterly_cashflow")
    a_inc = _first("income_stmt", "financials")
    a_bs = _safe_df("balance_sheet")
    a_cf = _safe_df("cashflow")

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
