# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is
Personal stock watchlist + portfolio tracker. Fetches fundamentals, market data, and insider transactions; computes composite scores; displays everything in a single-page table with tooltips.

## Stack
- **Backend**: FastAPI + asyncpg + SQLAlchemy (async), Python 3.12
- **DB**: PostgreSQL 16 (Docker)
- **Refresh**: manual/on-demand only, triggered via the API (`POST /api/refresh*`) and run as background asyncio tasks in `scheduler/worker.py`. There is **no** running scheduler despite the module name — `apscheduler` is a leftover dep and nothing starts a timer.
- **Frontend**: Vanilla JS + CSS, no framework
- **Deploy**: Docker Compose → Portainer on `juanhdzma@192.168.78.250`, port 8503

## Commands

### Run (primary workflow — Docker)
```bash
docker compose up -d --build   # rebuild + start; code is COPYed into the image, no bind mount
docker compose down
```
App at http://localhost:8503. DB is a named volume (`stock_data`) — survives `down`, wiped only by `down -v`.
Static assets are cache-busted by an MD5 hash in `api/main.py` (`_build_index_html`, cached after first request): `style.css` by its own hash, and the ES-module entry `js/main.js` by a hash of the **whole `js/` tree** (since its sibling imports carry no version query). A plain browser refresh after rebuild picks up the entry; if a change to a leaf module ever looks stale, one hard-refresh clears it.

### Run locally without Docker
```bash
./run.sh   # uvicorn --reload on :8000, needs DATABASE_URL pointing at a reachable Postgres
```

### Tests
```bash
python3 -m pytest tests/                              # all tests
python3 -m pytest tests/test_fixes.py -k test_name     # single test
```
Uses `pytest` + `pytest-asyncio` (`@pytest.mark.asyncio` on async tests) — installed in the dev environment, not listed in `requirements.txt` (runtime deps only).

Lint/format is `ruff` (config in `pyproject.toml`): `python3 -m ruff check .` and `python3 -m ruff format .`. The format pass drops manual column-alignment, so run it on touched files at the end of a change rather than mixing it with logic edits. `E701` (compact one-liner guards/ladders) is intentionally ignored.

## Project layout
```
api/
  main.py                  # FastAPI app, mounts routers, serves static/index.html with cache-busted asset URLs
  routers/
    watchlist.py           # GET /api/watchlist, /api/lists, PATCH/POST/DELETE
    portfolio.py           # GET /api/portfolio/prices
    refresh.py             # POST /api/refresh
    lookup.py              # ticker search
    status.py, system.py
    _payload.py            # build_payload() — shared snapshot+fundamentals+scores response shape used by watchlist/portfolio/lookup
core/
  insider_score.py         # compute_insider_score() — full insider conviction logic
  fetchers/
    yahoo.py                # market snapshot, fundamentals, dilution, put/call — yfinance
    openinsider.py          # insider transaction scraping
  scorers/
    base.py                 # clamp/ttm/latest_quarters/all_annual/analyst_upside_pts/slope_normalized/currency_mismatch + finalize_score() shared by every scorer
    composite.py            # compute_all() — assembles all sub-scores + composites
    fundamental_momentum.py
    value_quality.py
    price_long.py
db/
  models.py                # SQLAlchemy ORM: MarketSnapshot, Watchlist, etc.
  cache.py                 # DB read/write helpers
scheduler/
  worker.py                # refresh orchestration: refresh_one()/refresh_all()/refresh_portfolio_prices() + spawn_background(). NOT a running scheduler — see note below
static/
  js/                      # frontend as native ES modules (loaded via <script type="module" src="js/main.js">)
    state.js               # shared mutable `state` object (module imports are read-only, so cross-module state is routed through it)
    format.js colors.js    # pure formatters / score-color + badge helpers
    overlay.js charts.js   # tooltip positioning / all SVG charts
    tooltips.js cards.js    # hover+score tooltips / detail-view render pipeline
    tables.js api.js        # watchlist+portfolio tables / fetch wrappers
    main.js                # stateful glue: handlers, router, window.* exports, bootstrap
  style.css
  index.html
```
util.py                    # shared datetime/ticker helpers (utcnow_iso, ensure_aware, parse_iso_aware, today_and_week_ago)

## Score system

All scores are **0–100**. `compute_all()` in `composite.py` returns:

| Key | Component | Description |
|-----|-----------|-------------|
| `fundamental_momentum` | Growth | Revenue trend, NI trajectory, GM expansion, FCF trajectory, R&D intensity, Rule-of-40, estimate revisions, growth consistency (accel/decel) |
| `value_quality` | Quality | Profitability, cash position, execution track, margin durability, earnings quality, balance sheet, capital discipline, buyback + insider-ownership bonuses |
| `insider_conviction` | Insiders | Conviction-weighted buy/sell activity (see below) — `None` (excluded) when no trades survive filtering, not a neutral 50 |
| `price_long` | Sentiment | FCF yield, analyst upside, valuation, analyst conviction (key is still `price_long`; user-facing label is "Sentiment") |
| `composite_long` | Long | Weighted composite — the only investment horizon this app scores (no Short) |
| `buy_target` | — | Buy-now vs wait-for-a-dip signal (see below), not a 0–100 score |
| `flags` | — | Risk flags surfaced next to the verdict (see Tags reference) |

Growth/Quality/Insiders/Sentiment are deliberately independent axes — valuation and analyst signals live only in `price_long` (not `value_quality`), trajectory-only signals live only in `fundamental_momentum`, and level/durability-only signals live only in `value_quality`. Don't let a "quality" fix leak a price or sentiment input back in, or vice versa.

### `composite_long` (`core/scorers/composite.py`)

Quality-ranked: `fundamental_momentum`/`value_quality`/`insider_conviction` weighted **40/45/15** (`_QUALITY_WEIGHTS_LONG`, missing components excluded and the rest renormalized) forms a `quality` figure that dominates the score. (Insiders is 15% — not the old 10% — because `insider_conviction` now returns `None` when there's no real signal instead of a permanent neutral 50, so its weight only bites when there's actual conviction data.) Price and a recent-dip bonus are small, *bounded* additive modifiers on top (`_PRICE_BOOST_MAX = 6`, `_DIP_BONUS_MAX = 10`), not a ceiling-setter. A cheap price (via `price_long`, itself leaning on analyst targets the code's own comment flags as bullish-skewed) or a beta-adjusted recent selloff (`_dip_bonus` — day return ×2.2 vs. week return, whichever is larger, divided by beta) can tip a good-not-great business into STRONG-BUY, but neither can outrank a materially better business or rescue a bad one — quality gaps ≥ 7 points are mathematically un-invertible by price alone (boost max 6 < 7).

**Guardrail**: if `snapshot.revenue_growth < 0`, the final score is capped at 79.9 (just under STRONG-BUY) regardless of how high trailing profitability/balance-sheet quality scores — a business with genuinely shrinking revenue shouldn't hit the top tier on trailing quality alone (real case: QCOM at -3.5% YoY revenue was hitting 84.9 STRONG-BUY purely on `value_quality`=98).

### Scorer implementation pattern (`core/scorers/*.py` + `base.py`)

Each scorer builds a `sub` dict of raw sub-score values and a matching `max_pts` dict of ceilings, then calls `finalize_score(sub, max_pts)`, which sums the available (non-`None`) sub-scores, divides by the sum of *their* `max_pts`, and scales to 0–100.

**Gotcha**: `max_pts[key]` must equal the actual achievable ceiling of that sub-score's own formula — not just an intended weight written down separately. If a formula's internal clamp/scale caps below (or above) its declared `max_pts`, the category score is silently capped below 100 (or that component gets over-weighted) even with ideal input data, and it's easy to miss because nothing errors. Found this in `value_quality.py`: `profitability` and `balance_sheet` were declared at 35/25 but their formulas hardcoded a `*20` scale — `value_quality` topped out around 81/100 no matter how good the inputs were.

**Coverage convention inside a multi-metric sub-score**: `profitability`, `balance_sheet` (`value_quality.py`) and `valuation` (`price_long.py`) each blend several metrics (e.g. ROE/ROA/net_margin) that may be individually absent. They normalize by the sum of the *present* metrics' max points (an `avail` accumulator), not a fixed all-metrics denominator — the same available-coverage convention `finalize_score` uses across sub-scores. Normalizing by the fixed max would cap a partial-coverage company below the axis ceiling even with perfect data.

**Convention — `None` vs `0.0`**: a sub-score is `None` when the metric doesn't *apply* to this company right now (e.g. `cash_runway`'s survival-runway branch when the company isn't burning cash; `earnings_quality` when net income is negative; `margin_durability` with under 3–4 years of history) — it's excluded from the weighted average, never dragging the category down. A sub-score is a real `0.0` when the metric *does* apply and the company scores at the bottom of it (e.g. a company genuinely burning cash with no runway left). Getting this backwards either hides a real risk signal as "N/A" or unfairly zeroes out a company the metric doesn't apply to.

`finalize_score()` also accepts an optional `bonus` param — added *after* normalization and clamped so the total never exceeds 100. Use this for signals that should only ever help, never hurt, a score: `buyback_bonus`/`insider_ownership_bonus` in `value_quality.py`, `short_squeeze_bonus` in `price_long.py`. A company with no buybacks/low insider ownership/low short interest scores the same as before; one with the favorable trait gets added points. Multiple bonuses on one scorer just sum before the final clamp (see `value_quality.py`'s `total_bonus`). The bonus sub-score is still returned in `sub_scores` (outside the weighted `max_pts` sum) so the frontend can render it distinctly — see `bonusRow()` in `static/js/tooltips.js`, styled apart from the normal `subScoreBar()` rows.

### Sub-score reference

**`fundamental_momentum.py` (Growth)** — all trajectory, no level: `revenue_trend` (0-30, slope over available quarters), `ni_trajectory` (0-28, forgives improving losses), `gm_expansion` (0-20, neutral if a margin dip is explained by growing R&D intensity), `fcf_trajectory` (0-10), `rd_intensity` (0-6), `rule_of_40` (0-6), `estimate_revisions` (0-8, FY EPS estimate delta over 90d normalized by *price* not by the estimate itself — meaningless near zero for growth-stage names; `None` on currency mismatch), `growth_consistency` (0-8, recent-half vs. older-half revenue slope — catches deceleration inside an overall uptrend; needs ≥4 quarters with `revenue` populated — yfinance/the DB rarely retain more than ~5-7 quarters, so don't gate any of this on 8).

**`value_quality.py` (Quality)** — all level/durability, no price or sentiment: `profitability` (0-35, ROE/ROA/net_margin tiers; net_margin is discounted to the breakeven tier if it wildly outpaces a negative `operating_margin` — gap >20pp reads as a one-off gain masking real losses, real case: NBIS net_margin 93% vs. operating_margin -32%), `cash_runway` (0-15, branches on `ttm_fcf < 0`: burning → survival runway in quarters; not burning → cash/ttm_revenue cushion ratio — same key answers "will it survive" for distressed names and "how thick is the buffer" for healthy ones, so it's never blank just because a company is profitable), `execution_track` (0-10, % of last 4 quarters beating EPS estimate), `margin_durability` (0-12, trend + residual-noise decomposition of annual `gross_margin` — rising/flat-tight margins score well regardless of magnitude of change, only real erosion or a genuine historical dip costs points even if since recovered; falls back to a derived net_margin trend when `gross_margin` isn't reported at all, i.e. banks/fintechs), `earnings_quality` (0-10, TTM `operating_cash_flow`/`net_income` — `None` unless net income is positive), `balance_sheet` (0-25, current_ratio/D2E skipped for Financial Services, interest coverage applies to all), `capital_discipline` (0-8, `dilution_rate` tiers), `buyback_bonus` (0-2) + `insider_ownership_bonus` (0-3, additive only).

**`price_long.py` (Sentiment)** — all valuation/sentiment, no business quality: `fcf_yield` (0-45, ttm FCF / market cap; for foreign filers the local-currency FCF is converted to the price currency via `snapshot["fx_rate"]` rather than dropped), `analyst_upside` (0-30, coverage-weighted price-target upside), `valuation` (0-20, fwd/trailing PE ratio, PEG, growth-adjusted P/S), `analyst_conviction` (0-8, bull/bear recommendation distribution). (`price_discount` and `short_squeeze_bonus` were removed in the "Sentiment" rework — this axis no longer carries a price-level or short-interest signal.)

### Insider conviction score (`core/insider_score.py`)

- Scale: **0–100** (50 = neutral, >50 net buying, <50 net selling)
- Time decay: half-life 90 days
- Role weights: CEO=1.0, CFO=0.9, COO/CTO=0.85, SVP=0.7, DIR=0.5, VP=0.4, 10%=0.15
- Filters: min trade value by market cap ($5K–$50K), excludes S+OE with ΔOwn ≥ −10%, excludes routine sellers (CV < 0.30 and mean interval 5–35d → 80% discount)
- 10% beneficial owners get additional 50% bear discount
- Cluster bonus: 3+ insiders buying within 30d → +12 pts; 5+ → +25 pts
- Returns `50.0` (neutral) at this raw layer when `valid_buys + valid_sells == 0` after filtering — but the composite wrapper (`composite.py::_insider`) overrides that to `None` (excluded from the weighted composite, not a permanent neutral 50), and also returns `None` when the ticker has no `insider_transactions` at all

## Color system — 5-level score scale

**Do not use hardcoded hex colors for scores. Use CSS variables and `scoreColor()`/`scoreColorVar()` exclusively.**

| Level | Range | CSS class | CSS var | Color |
|-------|-------|-----------|---------|-------|
| 1 — Very bad | 0–19 | `ic-l1` | `var(--s1)` | `#ff4444` |
| 2 — Bad | 20–39 | `ic-l2` | `var(--s2)` | `#ff8c00` |
| 3 — Neutral | 40–59 | `ic-l3` | `var(--s3)` | `#fdd835` |
| 4 — Good | 60–79 | `ic-l4` | `var(--s4)` | `#adde63` |
| 5 — Very good | 80–100 | `ic-l5` | `var(--s5)` | `#00c853` |

JS helpers (defined in `static/js/colors.js`):
- `scoreColor(s)` → CSS class for 0–100 score (`ic-l1`…`ic-l5` or `s-null`)
- `scoreColorVar(s)` → CSS variable string for inline `style=` usage
- `pctScoreColor(val, scale)` → CSS class for signed % values; maps ±scale to 0–100 then applies scoreColor
- `actionLabel(a)` → display label (replaces hyphen with space: "STRONG-BUY" → "STRONG BUY")

**Do not use `s-green` / `s-red` / `s-yellow` for any score or percentage.** Those are reserved for semantic binary indicators (buy/sell direction arrows, boolean flags).

## Action labels (based on `composite_long` score)

| Score | Action key | Display |
|-------|-----------|---------|
| ≥ 80 | `STRONG-BUY` | Strong Buy |
| ≥ 60 | `BUY` | Buy |
| ≥ 40 | `HOLD` | Hold |
| ≥ 20 | `SELL` | Sell |
| < 20 | `STRONG-SELL` | Strong Sell |

CSS classes: `.action-STRONG-BUY`, `.action-BUY`, `.action-HOLD`, `.action-SELL`, `.action-STRONG-SELL`, `.action-NA`.

## `buy_target` — buy-now vs wait-for-a-dip signal (`composite.py::_buy_target`)

Two anchors, one shared volatility discount. NOT return-validated (analyst targets aren't in the price-only `entry_lab.py`/`bt_lab.py`) — the percentile/tier knobs are behavior-tuned.

**Anchor.** With ≥ `_BT_MIN_ANALYSTS` (10) covering it, the ~10th percentile of the analyst price-target distribution, interpolated between the analyst LOW (min, p0) and MEDIAN (p50): `anchor = low + (_BT_PERCENTILE/0.5)·(median − low)` (≈ 80% low / 20% median; `target_median` falls back to `target_mean`). A conservative, outlier-robust level grounded in forward fundamentals — not a single 52-week-high print, which a momentum name's bubble peak makes meaningless (real case: SNDK ran 40→2354 in a year, so 80% of its high = $1888 was a nonsense "buy" above the current price). Below 10 analysts the distribution is too thin to shape a percentile, so it **falls back** to the −30%-off-52w-high drawdown zone (`week52_high · (1 + _BUY_TARGET_DEEP_DD)`), an out-of-sample-validated mean-reversion entry (`entry_lab.py`: the deeper the trigger the stronger the rebound — −30% off the high gave ~+19pp/6m vs ~+10pp for −20%, at 30% vs 43% coverage; a "buy the pullback in an uptrend" regime was tried and **dropped** as dilutive).

**Volatility discount.** Either anchor is discounted by a margin of safety keyed to `realized_vol` — the annualized daily-return stdev over 1m/6m/12m windows, **averaged** (`yahoo.py::_compute_realized_vol`; replaced `typical_pullback_pct` and the yfinance `beta` field, which is null for exactly the movers that matter, e.g. recent spinoffs like SNDK). Three discrete tiers (`_vol_tier`): **low** (< `_BT_VOL_MID` 40%) → 0%, **mid** (40–75%) → 12%, **high** (≥ `_BT_VOL_HIGH` 75%) → 25%, as `target = anchor · (1 − mos)`. A calm name (AAPL ~25%) buys at the raw anchor; a wild one (SNDK ~110%) needs a 25%-deeper entry. Unmeasurable vol (< ~1 month of history, `_VOL_MIN_OBS`) is **`n/a`**, NOT low — treated conservatively at the high discount so a freshly-listed name isn't mistaken for calm (real case: SKHY, 12 days of history). An analyst-count weighting and a momentum widener were both tried and dropped (the percentile encodes conservatism directly; momentum double-counts with vol on bubble names — `bt_lab.py`).

Returns `{price, pct_from_current, signal, …breakdown}` where `signal` is `"buy"` (price ≤ target) or `"wait"`; the breakdown (`method` p10|drawdown, `low`/`p50`/`anchor` or `week52_high`, `vol`/`vol_windows`/`vol_level`/`mos`, `vol_mid`/`vol_high`) feeds the hover tooltip (`buildBuyTargetTooltip`). Frontend (`fmtBuyTargetHtml`): **BUY** (green) / **NEAR −X%** (amber, dip ≤4%) / **WAIT −X%** (red), always with the `≤ $threshold`.

## Tags reference (badges rendered next to the verdict)

**Risk flags** (`compute_all`'s `flags`, rendered by `riskFlags()`):
| Tag | Meaning |
|-----|---------|
| `REV↓` | Revenue shrinking YoY — composite capped below STRONG-BUY |
| `CYCLICAL` | Big revenue surge off a prior down-year — likely a cycle peak (Growth inflated), not durable growth |
| `$$$` | Valuation in the expensive tier |
| `E-Nd` | Earnings in ~N days — event risk |
| `PRICE?` | Quote deviates >50% from prior close (`price_suspect`) — data may be wrong |

**Fetch-status symbol** (one per row): `✓` ok · `⟳` in progress · `✕` a fetch failed · `·` pending/partial.

**Portfolio only**: `⚠` next to Diff = holding is in profit but the verdict decayed to HOLD/SELL (thesis rotted).

## DB tables
- `market_snapshot` — one row per ticker, `data_json` holds price + fundamentals + insider transactions + scores
- `watchlist` — tickers with `list_type` (watchlist | portfolio)
- `fundamentals_history` — quarterly fundamentals per ticker
- `portfolio_holdings` — avg_cost + shares per ticker
- `portfolio_prices` — cached price data for P&L
- `fetch_timestamps` — per-ticker, per-data-type last fetch time

## API conventions
- All routes under `/api/`
- Scores are computed on every `market_snapshot` read via `compute_all()`, not pre-stored
- Refresh is async; frontend polls or triggers manually via POST /api/refresh

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
| `GET` | `/api/market` | Market-context cards data: VIX / S&P 500 / Nasdaq 100 / 10Y yield (value + day change + 52w range), cached 60s |

Interactive docs at http://localhost:8503/docs.

## Environment
- `.env` at repo root (optional): `POSTGRES_PASSWORD` (defaults to `stocki`), `YAHOO_COOKIE_T`/`YAHOO_COOKIE_Y` (Yahoo Finance auth cookies, required when `fc.yahoo.com` is blocked — see `.env.example` for how to extract them from a browser session).
