# StockDesk

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

> The database is ephemeral by default — data is lost when the containers are removed. That's intentional for local dev.

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

## Environment

Optional `.env` file at the repo root:

```env
POSTGRES_PASSWORD=yourpassword
```

If omitted, the password defaults to `stockdesk`.

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
