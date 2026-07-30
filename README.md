# Stocki

Personal stock research dashboard. Pulls market data, fundamentals, and insider transactions from Yahoo Finance and OpenInsider, scores each ticker across several dimensions, and displays everything in a single-page UI.

## Requirements

- Docker + Docker Compose

That's it. No Python environment needed on the host.

## Running

```bash
docker compose up -d --build
```

Open [http://localhost:8503](http://localhost:8503).

To stop:

```bash
docker compose down
```

> The database lives in a named Docker volume (`stock_data`), so it survives `docker compose down` and restarts. It's wiped only by `docker compose down -v`.

## Loading tickers

The watchlist starts empty. To populate it:

1. Create a plain text file with tickers separated by commas:
   ```
   NVDA,MSFT,AAPL,GOOGL,META
   ```
2. Click **↑ Import** in the top-right corner of the app.
3. Select the file. A confirmation dialog will warn you that this replaces all current tickers.
4. The page reloads with the new list.

Tickers can also be added one at a time via the search input in the header.

## Refreshing data

Click **↻ Refresh** to fetch fresh snapshots, fundamentals, and insider transactions for all tickers in the list. The status lights next to each ticker show per-data-type freshness:

| Light | Meaning |
|-------|---------|
| 🟢 Green | Data available |
| 🟡 Yellow | Fetch in progress |
| 🔴 Red | Last fetch failed |
| ⚪ Gray | No data yet |

Columns: **snap** (price snapshot) · **fund** (annual fundamentals) · **qtrs** (quarterly fundamentals) · **ins** (insider transactions) · **score** (composite score ready)

## Ticker detail

Click any ticker row to open its detail view: price target bar, revenue/net income chart, key ratios, insider activity, and score breakdown.

## Market cards

A row of cards at the top gives market context: **VIX** (with a calm→fear range bar), **S&P 500**, **Nasdaq 100**, and the **10Y yield** (each with its day change and 52-week range position), plus two watchlist-derived cards — **Opportunities** (how many of your names are a BUY verdict / at their entry price) and **Pulse** (your list's average move today).

## Reading the table

**Scores (0–100)** — hover any for the full breakdown:
- **Growth** — revenue/earnings trajectory. **Quality** — profitability, balance sheet, durability. **Insiders** — conviction-weighted buy/sell activity. **Valuation** — how cheaply it trades: forward P/E, EV/EBITDA, PEG, and two sales multiples (P/S, EV/Sales), plus an analyst-upside bonus (high = cheap, low = expensive). **Long** — the weighted composite that drives the verdict.

**Verdict** (per Long score): Strong Buy ≥80 · Buy ≥60 · Hold ≥40 · Sell ≥20 · Strong Sell <20.

**Buy Target** — is it time to buy, or wait for a dip? The target is a conservative entry price: the ~10th percentile of analyst price targets (or, for names with <10 analysts, 30% off the 52-week high), discounted further for volatile names. Hover the cell for the full breakdown.
- **BUY** (green) — the price is at/below the target.
- **NEAR −X%** (amber) — almost; a small dip (≤4%) away.
- **WAIT −X%** (red) — still expensive; wait for that dip.

**Filters** — above the watchlist, filter rows by Action (verdict), Signal (buy/wait), and Sector. The count shows how many of the full list match.

**Risk flags** (next to the verdict):
- `REV↓` revenue shrinking · `CYCLICAL` growth is a likely cycle peak, not durable · `$$$` expensive valuation · `E-Nd` earnings in N days · `PRICE?` quote looks wrong (>50% off prior close).

**Status symbol**: `✓` data ok · `⟳` fetching · `✕` a fetch failed · `·` pending.

In the **portfolio** table, a `⚠` next to your gain/loss means you're in profit but the verdict has decayed to Hold/Sell — the thesis rotted while it ran.

## Environment

Optional `.env` file at the repo root:

```env
POSTGRES_PASSWORD=yourpassword
```

If omitted, the password defaults to `stocki`.

## API

The backend is a FastAPI app. Interactive docs available at [http://localhost:8503/docs](http://localhost:8503/docs).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/lists` | All tickers with their list type (watchlist / portfolio) |
| `POST` | `/api/lists/{ticker}` | Add a ticker (`?list_type=watchlist\|portfolio`) |
| `DELETE` | `/api/lists/{ticker}` | Remove a ticker |
| `PATCH` | `/api/lists/{ticker}` | Move a ticker between lists (`?list_type=...`) |
| `POST` | `/api/lists/import` | Replace all tickers (JSON array of strings) |
| `GET` | `/api/watchlist` | Scored data for a comma-separated list of tickers |
| `GET` | `/api/portfolio` | Scored data for all portfolio tickers |
| `GET` | `/api/lookup/{ticker}` | Live fetch + cache for a single ticker |
| `POST` | `/api/refresh` | Trigger background refresh for all tickers |
| `POST` | `/api/refresh/{ticker}` | Trigger refresh for a single ticker |
| `GET` | `/api/status` | Data freshness per ticker (`?tickers=A,B,C`) |
| `GET` | `/api/system/info` | Runtime info (yfinance auth status, DB counts) |
| `GET` | `/api/market` | Market-context data (VIX, S&P 500, Nasdaq 100, 10Y yield) for the top cards |
