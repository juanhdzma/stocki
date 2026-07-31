# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is
Personal stock watchlist tracker (with a starred "favorites" subset). Fetches fundamentals, market data, and insider transactions; computes composite scores; displays everything in a single-page table with tooltips.

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
    watchlist.py           # GET /api/watchlist, /api/lists (watchlist+favorites), PATCH/POST/DELETE
    refresh.py             # POST /api/refresh
    lookup.py              # ticker search
    status.py, system.py
    _payload.py            # build_payload() — shared snapshot+fundamentals+scores response shape used by watchlist/lookup
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
  worker.py                # refresh orchestration: refresh_one()/refresh_all() + spawn_background(). NOT a running scheduler — see note below
static/
  js/                      # frontend as native ES modules (loaded via <script type="module" src="js/main.js">)
    state.js               # shared mutable `state` object (module imports are read-only, so cross-module state is routed through it)
    format.js colors.js    # pure formatters / score-color + badge helpers
    overlay.js charts.js   # tooltip positioning / all SVG charts
    events.js              # "Today & Yesterday" section (insider trades + earnings in the last 2 ET days)
    tooltips.js cards.js    # hover+score tooltips / detail-view render pipeline
    tables.js api.js        # watchlist+favorites tables / fetch wrappers
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
| `price_long` | Valuation | Cheapness of the multiples (primary) + analyst target upside (key is still `price_long`; user-facing label is "Valuation") |
| `composite_long` | Long | Weighted composite — the only investment horizon this app scores (no Short) |
| `buy_target` | — | Buy-now vs wait-for-a-dip signal (see below), not a 0–100 score |
| `flags` | — | Risk flags surfaced next to the verdict (see Tags reference) |

Growth/Quality/Insiders/Valuation are deliberately independent axes — valuation-multiple and analyst-target signals live only in `price_long` (not `value_quality`), trajectory-only signals live only in `fundamental_momentum`, and level/durability-only signals live only in `value_quality`. Don't let a "quality" fix leak a price input back in, or vice versa.

### `composite_long` (`core/scorers/composite.py`)

Quality-ranked: `fundamental_momentum`/`value_quality`/`insider_conviction` weighted **40/45/15** (`_QUALITY_WEIGHTS_LONG`, missing components excluded and the rest renormalized) forms a `quality` figure that dominates the score. (Insiders is 15% — not the old 10% — because `insider_conviction` now returns `None` when there's no real signal instead of a permanent neutral 50, so its weight only bites when there's actual conviction data.) Price and a recent-dip bonus are small, *bounded* additive modifiers on top (`_PRICE_BOOST_MAX = 6`, `_DIP_BONUS_MAX = 10`), not a ceiling-setter. A cheap price (via `price_long`, itself leaning on analyst targets the code's own comment flags as bullish-skewed) or a beta-adjusted recent selloff (`_dip_bonus` — day return ×2.2 vs. week return, whichever is larger, divided by beta) can tip a good-not-great business into STRONG, but neither can outrank a materially better business or rescue a bad one — quality gaps ≥ 7 points are mathematically un-invertible by price alone (boost max 6 < 7).

**Guardrail**: if revenue is genuinely *trending* down (`_revenue_shrinking`), the final score is capped at 79.9 (just under STRONG) regardless of how high trailing profitability/balance-sheet quality scores — a business with genuinely shrinking revenue shouldn't hit the top tier on trailing quality alone. The trend gate (slope over the last ~4 quarters < `_REV_SHRINK_SLOPE` -0.10, the same "shrinking" reference `revenue_trend` uses; <4 quarters of history → never flags, since the trend can't be measured) deliberately does **not** cap on the single-quarter `revenue_growth` YoY, which reads deeply negative for a flat business whose year-ago base quarter had a one-off spike (real case: QBTS at -81% YoY was a one-off 15M system-sale quarter a year prior against flat ~3M quarters — not shrinking; QCOM at -3.5% YoY is likewise a flat name, not a decliner, and now clears the cap). Thin-history names (fresh IPOs/spinoffs, lumpy quantum/biotech contract revenue) are left unflagged rather than warned off that same noisy YoY.

### Scorer implementation pattern (`core/scorers/*.py` + `base.py`)

Each scorer builds a `sub` dict of raw sub-score values and a matching `max_pts` dict of ceilings, then calls `finalize_score(sub, max_pts)`, which sums the available (non-`None`) sub-scores, divides by the sum of *their* `max_pts`, and scales to 0–100.

**Gotcha**: `max_pts[key]` must equal the actual achievable ceiling of that sub-score's own formula — not just an intended weight written down separately. If a formula's internal clamp/scale caps below (or above) its declared `max_pts`, the category score is silently capped below 100 (or that component gets over-weighted) even with ideal input data, and it's easy to miss because nothing errors. Found this in `value_quality.py`: `profitability` and `balance_sheet` were declared at 35/25 but their formulas hardcoded a `*20` scale — `value_quality` topped out around 81/100 no matter how good the inputs were.

**Coverage convention inside a multi-metric sub-score**: `profitability`, `balance_sheet` (`value_quality.py`) each blend several metrics (e.g. ROE/ROA/net_margin) that may be individually absent. They normalize by the sum of the *present* metrics' max points (an `avail` accumulator), not a fixed all-metrics denominator — the same available-coverage convention `finalize_score` uses across sub-scores. Normalizing by the fixed max would cap a partial-coverage company below the axis ceiling even with perfect data. (`price_long.py`'s valuation multiples used to blend the same way into one `valuation` sub-score; they're now three separate weighted sub-scores — `fwd_pe`/`peg`/`growth_adj_ps` — so `finalize_score`'s own available-coverage handling does the normalization and each multiple renders as its own bar. `price_long` passes `min_coverage=0.2` so a name with a single present multiple, e.g. `growth_adj_ps` alone at 6/26=0.23, still scores instead of the 0.30 default excluding it.)

**Convention — `None` vs `0.0`**: a sub-score is `None` when the metric doesn't *apply* to this company right now (e.g. `cash_runway`'s survival-runway branch when the company isn't burning cash; `earnings_quality` when net income is negative; `margin_durability` with under 3–4 years of history) — it's excluded from the weighted average, never dragging the category down. A sub-score is a real `0.0` when the metric *does* apply and the company scores at the bottom of it (e.g. a company genuinely burning cash with no runway left). Getting this backwards either hides a real risk signal as "N/A" or unfairly zeroes out a company the metric doesn't apply to.

`finalize_score()` also accepts an optional `bonus` param — added *after* normalization and clamped so the total never exceeds 100. Use this for signals that should only ever help, never hurt, a score: `buyback_bonus`/`insider_ownership_bonus` in `value_quality.py`, `short_squeeze_bonus` in `price_long.py`. A company with no buybacks/low insider ownership/low short interest scores the same as before; one with the favorable trait gets added points. Multiple bonuses on one scorer just sum before the final clamp (see `value_quality.py`'s `total_bonus`). The bonus sub-score is still returned in `sub_scores` (outside the weighted `max_pts` sum) so the frontend can render it distinctly — see `bonusRow()` in `static/js/tooltips.js`, styled apart from the normal `subScoreBar()` rows.

### Sub-score reference

**`fundamental_momentum.py` (Growth)** — all trajectory, no level: `revenue_trend` (0-30, slope over available quarters), `ni_trajectory` (0-28, forgives improving losses), `gm_expansion` (0-20, neutral if a margin dip is explained by growing R&D intensity), `fcf_trajectory` (0-10), `rd_intensity` (0-6), `rule_of_40` (0-6), `estimate_revisions` (0-8, FY EPS estimate delta over 90d normalized by *price* not by the estimate itself — meaningless near zero for growth-stage names; `None` on currency mismatch), `growth_consistency` (0-8, recent-half vs. older-half revenue slope — catches deceleration inside an overall uptrend; needs ≥4 quarters with `revenue` populated — yfinance/the DB rarely retain more than ~5-7 quarters, so don't gate any of this on 8).

**`value_quality.py` (Quality)** — all level/durability, no price or sentiment: `profitability` (0-35, ROE/ROA/net_margin tiers; net_margin is discounted to the breakeven tier if it wildly outpaces a negative `operating_margin` — gap >20pp reads as a one-off gain masking real losses, real case: NBIS net_margin 93% vs. operating_margin -32%), `cash_runway` (0-15, branches on `ttm_fcf < 0`: burning → survival runway in quarters; not burning → cash/ttm_revenue cushion ratio — same key answers "will it survive" for distressed names and "how thick is the buffer" for healthy ones, so it's never blank just because a company is profitable), `execution_track` (0-10, % of last 4 quarters beating EPS estimate), `margin_durability` (0-12, trend + residual-noise decomposition of annual `gross_margin` — rising/flat-tight margins score well regardless of magnitude of change, only real erosion or a genuine historical dip costs points even if since recovered; falls back to a derived net_margin trend when `gross_margin` isn't reported at all, i.e. banks/fintechs), `earnings_quality` (0-10, TTM `operating_cash_flow`/`net_income` — `None` unless net income is positive), `balance_sheet` (0-25, current_ratio/D2E skipped for Financial Services, interest coverage applies to all), `capital_discipline` (0-8, `dilution_rate` tiers), `buyback_bonus` (0-2) + `insider_ownership_bonus` (0-3, additive only).

**`price_long.py` (Valuation)** — how cheaply the stock trades, no business-quality or hard-cash signal. Five weighted sub-scores, one per multiple, each scoring the cheapness of its LEVEL: `fwd_pe` (0-12, absolute forward P/E tier), `ev_ebitda` (0-10, EV/EBITDA — robust to depressed/negative *net* earnings and capital structure; `None` on negative EBITDA), `peg` (0-8), `growth_adj_ps` (0-6, P/S divided by 1+revenue_growth), `ev_sales` (0-6, EV/revenue growth-adjusted the same way). The two sales multiples (`growth_adj_ps`, `ev_sales`) are the only ones that apply to **pre-profit** names — they have no earnings, EBITDA, or PEG — so they give the speculative tail a real valuation instead of a null axis (adding `ev_sales` cut names-with-only-one-multiple from 19 to 1). EV-based multiples are skipped on currency mismatch (EV in price ccy vs local revenue/EBITDA). Deliberately not the fwd-vs-trailing P/E *ratio*, which rewards earnings growth-momentum, not cheapness, and leaks a trajectory signal into the valuation axis (growth lives only in `fundamental_momentum`) — that old term scored a cheap-but-decelerating name (NVO ~15x) at 0. They're separate sub-scores (not one blended `valuation` bar) so the axis breaks out like every other one in the tooltip. **Tier calibration is to the actual universe, not textbook** — this watchlist is growth/tech-heavy (median EV/EBITDA ~27), so `ev_ebitda` tiers place that median near neutral; textbook ~12-fair tiers dumped ~60% of names at 0, a non-discriminating near-constant that just deflated everything (the same failure that killed `analyst_conviction`). `analyst_upside` (0-8) is an **additive-only bonus** (`_UPSIDE_BONUS_MAX`, injected into `sub_scores`/`max_pts` after `finalize_score`, rendered via `bonusRow()`), never a weighted sub-score: coverage-weighted price-target upside can only LIFT a measured valuation, never define it. This matters two ways — a name with **no usable multiple** (pre-*revenue*: no positive fwd P/E, no PEG, no P/S, no EV/Sales) has no weighted sub-score at all, so the axis returns `None` (excluded) instead of scoring a perfect 100 off analyst optimism alone (real bug: OKLO, negative fwd P/E, was hitting 100); and a **wildly overvalued** name (every multiple in the bottom tier ~0, e.g. RKLB ~1200x) can't be floored high by it — it lands in single digits, not a propped-up ~30. `min_coverage=0.1` so even a single present multiple still scores (for a valuation axis one real multiple is signal). Two sub-scores that measured near-constants across the real watchlist were dropped entirely: `analyst_conviction` (bull/bear ratings were a herdish ~9 for ~90% of names — no discrimination) and, earlier, `fcf_yield` (hard cash, not valuation; double-counted cheapness here and cash in `value_quality`'s `cash_runway`). The axis was relabeled "Sentiment" → "Valuation" when this shook out: the only signal that actually discriminated was cheapness, and "cheap" is the opposite of bullish sentiment (a low multiple is the market being skeptical), so the honest label is Valuation. (`price_discount` and `short_squeeze_bonus` were removed in an earlier rework — this axis carries no price-level, short-interest, cash-generation, or sentiment signal, only how cheap the multiples are.)

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
- `actionLabel(a)` → display label (returns the tier key as-is; the badge CSS uppercases it)

**Do not use `s-green` / `s-red` / `s-yellow` for any score or percentage.** Those are reserved for semantic binary indicators (buy/sell direction arrows, boolean flags).

## Rating labels (based on `composite_long` score)

A **company-quality tier**, deliberately NOT transactional vocabulary — the composite rates the *business*, not the entry. Only `buy_target` speaks BUY/WAIT (the entry-price signal); the two axes are kept in separate vocabularies on purpose so a "STRONG" business at a bad price still reads as "STRONG" + "WAIT ≤ $X".

| Score | Tier key | Meaning |
|-------|-----------|---------|
| ≥ 80 | `STRONG` | Top-tier business |
| ≥ 60 | `SOLID` | Good |
| ≥ 40 | `FAIR` | Neutral |
| ≥ 20 | `WEAK` | Poor |
| < 20 | `AVOID` | Bottom-tier |

CSS classes: `.action-STRONG`, `.action-SOLID`, `.action-FAIR`, `.action-WEAK`, `.action-AVOID`, `.action-NA`. (Class prefix stays `.action-` and the score key stays `action` — only the tier *values* changed.)

## `buy_target` — buy-now vs wait-for-a-dip signal (`composite.py::_buy_target`)

Two anchors, one shared volatility discount. NOT return-validated (analyst targets aren't in the price-only `entry_lab.py`/`bt_lab.py`) — the percentile/tier knobs are behavior-tuned.

**Anchor.** With ≥ `_BT_MIN_ANALYSTS` (10) covering it, the ~17.5th percentile of the analyst price-target distribution, interpolated between the analyst LOW (min, p0) and MEDIAN (p50): `anchor = low + (_BT_PERCENTILE/0.5)·(median − low)` (≈ 65% low / 35% median; `target_median` falls back to `target_mean`). A conservative, outlier-robust level grounded in forward fundamentals — not a single 52-week-high print, which a momentum name's bubble peak makes meaningless (real case: SNDK ran 40→2354 in a year, so 80% of its high = $1888 was a nonsense "buy" above the current price). Below 10 analysts the distribution is too thin to shape a percentile, so it **falls back** to a technical anchor: the **lower** (more conservative) of the −30%-off-52w-high drawdown zone (`week52_high · (1 + _BUY_TARGET_DEEP_DD)`, an out-of-sample-validated mean-reversion entry — `entry_lab.py`: the deeper the trigger the stronger the rebound, −30% off the high gave ~+19pp/6m vs ~+10pp for −20%) and the **200-day SMA** (`moving_averages["200"]` from `yahoo.py::_compute_moving_averages` off the same bulk `hist`), a real trend-support level rather than an arbitrary %. It falls back to whichever of the two is measurable (SMA200 needs ~a full year of closes). The SMA is used as an anchor **level**, deliberately not the binary above/below-MA200 **gate** — `bt_lab.py` found that gate doesn't separate winners from losers (beaten-down names rebound hardest), so MA200 only informs *where* to buy, never *whether*. `method` is `ma200` when the SMA is the binding (lower) anchor, else `drawdown`.

**Margin of safety — two stacked discounts.** The anchor is discounted by `target = anchor · (1 − mos)` where `mos = vol_mos + disp_mos` — two independent risk signals summed (no cap: vol max 0.20 + dispersion max 0.12 tops out at 0.32, low enough to just sum):
- **Volatility** (`_vol_tier`, both branches): `realized_vol`, the annualized daily-return stdev over 1m/6m/12m windows **averaged** (`yahoo.py::_compute_realized_vol`; replaced `typical_pullback_pct` and the yfinance `beta` field, which is null for exactly the movers that matter, e.g. recent spinoffs like SNDK). Tiers: **low** (< `_BT_VOL_MID` 40%) → 0%, **mid** (40–75%) → 10%, **high** (≥ `_BT_VOL_HIGH` 75%) → 20%. A calm name (AAPL ~25%) buys at the raw anchor; a wild one (SNDK ~110%) needs 20% deeper. Unmeasurable vol (< ~1 month of history, `_VOL_MIN_OBS`) is **`n/a`**, NOT low — treated conservatively at the high discount so a freshly-listed name isn't mistaken for calm (real case: SKHY, 12 days).
- **Analyst dispersion** (`_disp_tier`, analyst branch only): the low→high spread over the median, `disp = (target_high − target_low) / p50`. Tiers: **low** (< `_BT_DISP_MID` 0.40) → 0%, **mid** (0.40–0.80) → 6%, **high** (≥ `_BT_DISP_HIGH` 0.80) → 12%. Encodes the paper's core finding (Palley/Steffen/Zhang, Mgmt Science 2025): a wide range doesn't make the consensus merely noisier — its correlation with forward return flips **negative** (stale, un-revised targets inflate it after bad news), so a wide range is a warning demanding a deeper entry, not an opportunity. Unmeasurable spread (no `target_high`) is **`n/a`** → **0%** discount, NOT punished — unlike unmeasurable vol, absent dispersion is just absence of a warning, not a risk signal.

An analyst-count weighting and a momentum widener were both tried and dropped (the percentile encodes conservatism directly; momentum double-counts with vol on bubble names — `bt_lab.py`).

Returns `{price, pct_from_current, signal, …breakdown}` where `signal` is `"buy"` (price ≤ target) or `"wait"`; the breakdown (`method` analyst|drawdown|ma200, `low`/`p50`/`high`/`disp`/`disp_level`/`anchor` or `week52_high`/`sma200`, `vol`/`vol_windows`/`vol_level`/`vol_mos`/`disp_mos`/`mos`, `vol_mid`/`vol_high`/`disp_mid`/`disp_high`) feeds the hover tooltip (`buildBuyTargetTooltip`). Frontend (`fmtBuyTargetHtml`): **BUY** (green) / **NEAR −X%** (amber, dip ≤4%) / **WAIT −X%** (red), always with the `≤ $threshold`.

## Tags reference (badges rendered next to the verdict)

**Risk flags** (`compute_all`'s `flags`, rendered by `riskFlags()`):
| Tag | Meaning |
|-----|---------|
| `REV↓` | Revenue *trending* down (`_revenue_shrinking`: slope over the last ~4 quarters, not the single-quarter YoY — so a flat business isn't flagged just because its year-ago base quarter had a one-off spike; <4 quarters of history never flags) — composite capped below STRONG |
| `CYCLICAL` | Revenue surge off a prior down-year — cyclical growth (a cycle peak or a low-base trough bounce), not durable (Growth inflated). Cycle depth spans revenue AND earnings: a margin-cyclical whose revenue dip is shallow but whose ebit fell ≥1.5× harder (operating leverage) still flags. Gated by op-margin > -25% (excludes pre-revenue noise) and a surge that scales with trough depth. |
| `$$$` | Rich valuation (`_is_expensive`) — confirmed on two independent bases so single-metric artifacts don't misfire: profitable names must be rich on **both** forward P/E (>30) **and** growth-adjusted P/S (>8); pre-profit names (no positive P/E) flag on a high **raw** P/S (>20). Deliberately not derived from `price_long`'s `valuation` sub-score, which mixes in earnings-trend momentum (flagged cheap-but-decelerating names, missed expensive-but-growing ones). |
| `E-Nd` | Earnings in ~N days — event risk |
| `PRICE?` | Quote deviates >50% from prior close (`price_suspect`) — data may be wrong |

**Fetch-status symbol** (one per row): `✓` ok · `⟳` in progress · `✕` a fetch failed · `·` pending/partial.

## DB tables
- `market_snapshot` — one row per ticker, `data_json` holds price + fundamentals + insider transactions + scores. `earnings_dates` (list[str], consumed by the `E-Nd` flag + insider post-earnings bonus) plus `earnings_events` (rich rows `{date, datetime ET, eps_estimate, reported_eps, surprise_pct}` from yfinance `get_earnings_dates` — `reported_eps` is `None` until reported; drives the "Today & Yesterday" section's upcoming-time vs EPS-beat split. yfinance exposes no revenue actual-vs-estimate, so only EPS is carried).
- `watchlist` — tickers with `list_type` (`watchlist` | `favorite`). Favorites are a starred subset surfaced in a separate top section — no holdings/P&L, just the same scored table. (Portfolio holdings/P&L were removed; `init_db` migrated any prior `portfolio_holdings` rows to `favorite` and dropped the `portfolio_holdings`/`portfolio_prices` tables.)
- `fundamentals_history` — quarterly fundamentals per ticker
- `fetch_timestamps` — per-ticker, per-data-type last fetch time

## API conventions
- All routes under `/api/`
- Scores are computed on every `market_snapshot` read via `compute_all()`, not pre-stored
- Refresh is async; frontend polls or triggers manually via POST /api/refresh

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/lists` | Tickers split into `{watchlist, favorites}` by `list_type` |
| `POST` | `/api/lists/{ticker}` | Add a ticker (`?list_type=watchlist\|favorite`) |
| `DELETE` | `/api/lists/{ticker}` | Remove a ticker |
| `PATCH` | `/api/lists/{ticker}` | Star/unstar — move between watchlist and favorite (`?list_type=...`) |
| `POST` | `/api/lists/import` | Replace all tickers (JSON array of strings) |
| `GET` | `/api/watchlist` | Scored data for a comma-separated list of tickers |
| `GET` | `/api/lookup/{ticker}` | Live fetch + cache for a single ticker |
| `POST` | `/api/refresh` | Trigger background refresh for all tickers |
| `POST` | `/api/refresh/{ticker}` | Trigger refresh for a single ticker |
| `GET` | `/api/status` | Data freshness per ticker (`?tickers=A,B,C`) |
| `GET` | `/api/system/info` | Runtime info (yfinance auth status, DB counts) |
| `GET` | `/api/market` | Market-context cards data: VIX / S&P 500 / Nasdaq 100 / 10Y yield (value + day change + 52w range), cached 60s |

Interactive docs at http://localhost:8503/docs.

## Environment
- `.env` at repo root (optional): `POSTGRES_PASSWORD` (defaults to `stocki`), `YAHOO_COOKIE_T`/`YAHOO_COOKIE_Y` (Yahoo Finance auth cookies, required when `fc.yahoo.com` is blocked — see `.env.example` for how to extract them from a browser session).
