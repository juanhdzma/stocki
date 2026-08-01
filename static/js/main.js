import { state } from "./state.js";
import { timeAgo, escapeHtml } from "./format.js";
import { _toggleSort, renderTickerTable, renderRow, renderStatusSymbol } from "./tables.js";
import { render, loadPriceTrend } from "./cards.js";
import { buildScoreTooltip, buildDeltaTooltip, buildBuyTargetTooltip } from "./tooltips.js";
import { showOverlay, hideTooltip } from "./overlay.js";
import { renderMarketBar } from "./market.js";
import { renderTodayYesterday } from "./events.js";
import { priceChartHover, chartHoverEnd } from "./charts.js";

async function loadLists() {
  const res = await fetch("/api/lists");
  if (!res.ok) throw new Error("lists " + res.status);
  const data = await res.json();
  state.watchlist = data.watchlist;
  state.favorites = data.favorites || [];
}

function setWlSort(col) {
  [state.wlSortCol, state.wlSortDir] = _toggleSort(state.wlSortCol, state.wlSortDir, col);
  sessionStorage.setItem("wlSortCol", state.wlSortCol);
  sessionStorage.setItem("wlSortDir", state.wlSortDir);
  renderTables();
}

function filteredWatchlist() {
  const f = state.wlFilters;
  const q = (f.search || "").trim().toLowerCase();
  return state.watchlist.filter(t => {
    const d = state.watchlistData[t];
    if (f.action && d?.scores?.composite_long?.action !== f.action) return false;
    if (f.signal && d?.scores?.buy_target?.signal !== f.signal) return false;
    if (f.sector && (d?.snapshot?.sector || "") !== f.sector) return false;
    if (f.flag && !(d?.scores?.flags || []).some(fl => fl.key === f.flag)) return false;
    if (q && !t.toLowerCase().includes(q) && !(d?.snapshot?.name || "").toLowerCase().includes(q)) return false;
    return true;
  });
}

function setWlFilter(dim, value) {
  state.wlFilters[dim] = value;
  sessionStorage.setItem("wlFilters", JSON.stringify(state.wlFilters));
  renderWlSection();  // filters only touch the watchlist table
  if (dim === "search") {  // re-render recreates the input — restore focus + caret
    const el = document.getElementById("wl-search");
    if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
  }
}

function clearWlFilters() {
  state.wlFilters = { action: "", signal: "", sector: "", flag: "", search: "" };
  sessionStorage.setItem("wlFilters", JSON.stringify(state.wlFilters));
  renderWlSection();
}

function renderWlFilterBar() {
  const f = state.wlFilters;
  const opt = (v, label, cur) => `<option value="${escapeHtml(v)}"${v === cur ? " selected" : ""}>${escapeHtml(label)}</option>`;
  const sectors = [...new Set(state.watchlist.map(t => state.watchlistData[t]?.snapshot?.sector).filter(Boolean))].sort();
  const actions = [["STRONG", "Strong"], ["SOLID", "Solid"], ["FAIR", "Fair"], ["WEAK", "Weak"], ["AVOID", "Avoid"]];
  const flagLabels = { new: "NEW", rev: "REV↓", cyclical: "CYCLICAL", expensive: "$$$", earnings: "Earnings soon", price: "PRICE?" };
  const flags = [...new Set(state.watchlist.flatMap(t => (state.watchlistData[t]?.scores?.flags || []).map(fl => fl.key)))].sort();
  const active = f.action || f.signal || f.sector || f.flag || f.search;
  return `<div class="wl-filters">
    <input id="wl-search" class="wl-filter wl-search${f.search ? " wl-filter-on" : ""}" type="text"
      placeholder="Search ticker…" aria-label="Search ticker" autocomplete="off" spellcheck="false" value="${(f.search || "").replace(/"/g, "&quot;")}"
      oninput="setWlFilter('search', this.value)">
    <select class="wl-filter${f.action ? " wl-filter-on" : ""}" aria-label="Filter by rating" onchange="setWlFilter('action', this.value)">
      <option value="">Rating: all</option>${actions.map(([v, l]) => opt(v, l, f.action)).join("")}
    </select>
    <select class="wl-filter${f.signal ? " wl-filter-on" : ""}" aria-label="Filter by signal" onchange="setWlFilter('signal', this.value)">
      <option value="">Signal: all</option>${opt("buy", "Buy", f.signal)}${opt("wait", "Wait", f.signal)}
    </select>
    <select class="wl-filter${f.sector ? " wl-filter-on" : ""}" aria-label="Filter by sector" onchange="setWlFilter('sector', this.value)">
      <option value="">Sector: all</option>${sectors.map(s => opt(s, s, f.sector)).join("")}
    </select>
    ${flags.length ? `<select class="wl-filter${f.flag ? " wl-filter-on" : ""}" aria-label="Filter by flag" onchange="setWlFilter('flag', this.value)">
      <option value="">Flag: all</option>${flags.map(k => opt(k, flagLabels[k] || k, f.flag)).join("")}
    </select>` : ""}
    ${active ? `<button class="wl-filter-clear" onclick="clearWlFilters()">✕ clear</button>` : ""}
  </div>`;
}

function rowActions(t) {
  const fav = state.favorites.includes(t);
  const favLabel = fav ? `Remove ${t} from favorites` : `Add ${t} to favorites`;
  return `<button class="btn-star${fav ? " starred" : ""}" title="${favLabel}" aria-label="${favLabel}" onclick="toggleFavorite('${t}')">${fav ? "★" : "☆"}</button>
    <button class="btn-remove" aria-label="Remove ${t}" onclick="removeTicker('${t}')">✕</button>`;
}

// The home is split into independent mounts so a sort/filter/star only re-renders the
// affected table, not the market bar + Today/Yesterday + both tables on every interaction.
function renderHomeSections() {
  const dash = document.getElementById("dashboard");

  if (!state.favorites.length && !state.watchlist.length) {
    dash.innerHTML = `<p class="subtext center" style="margin-top:60px">Add a ticker above to start.</p>`;
    return;
  }

  dash.innerHTML = `<div id="market-mount"></div><div id="events-mount"></div><div id="fav-mount"></div><div id="wl-mount"></div>`;
  renderMarketSection();
  renderEventsSection();
  renderFavSection();
  renderWlSection();
}

function renderMarketSection() {
  const el = document.getElementById("market-mount");
  if (el) el.innerHTML = renderMarketBar(state.market, state.watchlistData, state.homeLoadedAt);
}

function renderEventsSection() {
  const el = document.getElementById("events-mount");
  if (el) el.innerHTML = renderTodayYesterday(state.watchlistData);
}

function renderFavSection() {
  const el = document.getElementById("fav-mount");
  if (!el) return;
  el.innerHTML = state.favorites.length
    ? `<section class="cat-section watchlist-section">
        <h2>★ Favorites <span class="subtext" style="font-size:13px;font-weight:400">${state.favorites.length}</span></h2>
        ${renderTickerTable(state.favorites, state.wlSortCol, state.wlSortDir, "setWlSort", rowActions)}
      </section>`
    : "";
}

function renderWlSection() {
  const el = document.getElementById("wl-mount");
  if (!el) return;
  if (!state.watchlist.length) { el.innerHTML = ""; return; }
  const wlTickers = filteredWatchlist();
  el.innerHTML = `<section class="cat-section watchlist-section">
      <h2>Watchlist <span class="subtext" style="font-size:13px;font-weight:400">${wlTickers.length}/${state.watchlist.length}</span></h2>
      ${renderWlFilterBar()}
      ${wlTickers.length
        ? renderTickerTable(wlTickers, state.wlSortCol, state.wlSortDir, "setWlSort", rowActions)
        : `<p class="subtext center" style="margin:24px 0">No results for this filter.</p>`}
    </section>`;
}

// Both tables share one sort/membership, so sort + star re-render the pair (but nothing else).
function renderTables() { renderFavSection(); renderWlSection(); }

async function loadStatus(tickers) {
  if (!tickers.length) return;
  try {
    const res = await fetch("/api/status?tickers=" + tickers.join(","));
    state.tickerStatus = await res.json();
  } catch (e) {
    console.error("Status load failed:", e);
  }
}

async function showHome() {
  renderHeader("home");
  const dash = document.getElementById("dashboard");
  dash.innerHTML = `<p class="subtext center">Loading…</p>`;

  let listsFailed = false;
  try { await loadLists(); } catch (e) { console.error("Failed to load lists:", e); listsFailed = true; }

  const allTickers = [...new Set([...state.favorites, ...state.watchlist])];
  if (!allTickers.length) {
    // A failed load leaves the lists empty too — don't tell a user with an existing watchlist to
    // "add a ticker", which reads as data loss. Distinguish the two states.
    dash.innerHTML = listsFailed
      ? `<p class="subtext center" style="margin-top:60px">Couldn't load your list. <button class="btn" onclick="location.reload()">Retry</button></p>`
      : `<p class="subtext center" style="margin-top:60px">Add a ticker above to start.</p>`;
    return;
  }

  try {
    const [wlRes, stRes, mkRes] = await Promise.all([
      fetch("/api/watchlist?tickers=" + allTickers.join(",")),
      fetch("/api/status?tickers="   + allTickers.join(",")),
      fetch("/api/market").catch(() => null),
    ]);
    state.watchlistData = await wlRes.json();
    state.tickerStatus  = await stRes.json();
    if (mkRes && mkRes.ok) state.market = await mkRes.json();
    state.homeLoadedAt = new Date().toISOString();
  } catch (e) {
    console.error("Home load failed:", e);
  }

  renderHomeSections();
}

function flashInvalid(input) {
  input.classList.add("input-invalid");
  setTimeout(() => input.classList.remove("input-invalid"), 1200);
}

async function handleAddTicker() {
  const input = document.getElementById("add-input");
  if (!input) return;
  const ticker = input.value.trim().toUpperCase();
  if (!ticker || !/^[A-Z0-9.\-]{1,12}$/.test(ticker)) { flashInvalid(input); return; }
  if (state.favorites.includes(ticker) || state.watchlist.includes(ticker)) { flashInvalid(input); input.value = ""; return; }

  const res = await fetch(`/api/lists/${ticker}`, {method: "POST"}).catch(() => null);
  if (!res || !res.ok) { flashInvalid(input); return; }  // keep the text so the user can retry
  input.value = "";
  state.watchlist.push(ticker);
  state.watchlistData[ticker] = null;
  renderHomeSections();

  try {
    await fetch("/api/lookup/" + ticker);
    const allTickers = [...new Set([...state.favorites, ...state.watchlist])];
    const r = await fetch("/api/watchlist?tickers=" + allTickers.join(","));
    Object.assign(state.watchlistData, await r.json());
  } catch (e) {
    console.error("Fetch failed for", ticker, e);
  }

  renderHomeSections();
}

// Mutations are pessimistic: hit the server first, mutate local state only on success, so a
// failed request can't leave the client diverged from the DB until reload.
async function removeTicker(ticker) {
  const res = await fetch(`/api/lists/${ticker}`, {method: "DELETE"}).catch(() => null);
  if (!res || !res.ok) { alert("Failed to remove " + ticker); return; }
  state.favorites = state.favorites.filter(t => t !== ticker);
  state.watchlist = state.watchlist.filter(t => t !== ticker);
  delete state.watchlistData[ticker];
  renderHomeSections();
}

async function toggleFavorite(ticker) {
  const makeFav = !state.favorites.includes(ticker);
  const targetList = makeFav ? "favorite" : "watchlist";
  const res = await fetch(`/api/lists/${ticker}?list_type=${targetList}`, {method: "PATCH"}).catch(() => null);
  if (!res || !res.ok) { alert("Failed to update " + ticker); return; }
  if (makeFav) {
    state.watchlist = state.watchlist.filter(t => t !== ticker);
    if (!state.favorites.includes(ticker)) state.favorites.push(ticker);
  } else {
    state.favorites = state.favorites.filter(t => t !== ticker);
    if (!state.watchlist.includes(ticker)) state.watchlist.push(ticker);
  }
  renderTables();  // membership change only — market bar / events unaffected
}

// ── Detail view ───────────────────────────────────────────────────────────────
async function _fetchAndRenderDetail(ticker) {
  const res = await fetch("/api/watchlist?tickers=" + ticker + "&full=1");  // detail needs annuals/quarterlies
  if (!res.ok) return;
  const raw = await res.json();
  const payload = raw[ticker];
  if (!payload) return;
  state.lastDetail = { ticker, raw };
  renderHeader("detail", ticker, payload.refreshed_at);
  render([ticker], raw);
  loadPriceTrend(ticker);
}

async function showDetail(ticker) {
  renderHeader("detail", ticker);
  const dash = document.getElementById("dashboard");
  dash.innerHTML = `<p class="subtext center">Loading ${ticker}…</p>`;

  try {
    await _fetchAndRenderDetail(ticker);
  } catch (e) {
    dash.innerHTML = `<p class="subtext center">Failed to load ${ticker}.</p>`;
    console.error(e);
  }
}

// ── Header ────────────────────────────────────────────────────────────────────
function _isInFlight(status, ticker) {
  const s = status[ticker];
  return !!s && Object.values(s).includes("yellow");
}

async function handleRefreshAll() {
  const allTickers = [...new Set([...state.favorites, ...state.watchlist])];
  if (!allTickers.length) return;
  const btn = document.getElementById("refresh-all-btn");
  if (btn) { btn.textContent = "↻ …"; btn.disabled = true; btn.classList.add("loading"); }

  await fetch("/api/refresh", { method: "POST" }).catch(() => {});

  // Full /api/watchlist recomputes scores for every tracked ticker — too heavy to
  // re-poll wholesale every 2s. Instead poll the cheap /api/status, and only re-fetch
  // watchlist data for tickers whose refresh just finished (in_flight -> not in_flight).
  let prevStatus = { ...state.tickerStatus };

  let pollErrors = 0;
  while (true) {
    await new Promise(r => setTimeout(r, 2000));
    let justDone = [];
    try {
      const stRes = await fetch("/api/status?tickers=" + allTickers.join(","));
      const newStatus = await stRes.json();

      justDone = allTickers.filter(
        t => _isInFlight(prevStatus, t) && !_isInFlight(newStatus, t)
      );

      state.tickerStatus = newStatus;
      prevStatus   = newStatus;
      pollErrors = 0;

      if (justDone.length) {
        const wlRes = await fetch("/api/watchlist?tickers=" + justDone.join(","));
        Object.assign(state.watchlistData, await wlRes.json());
      }
    } catch (e) {
      console.error("Poll failed:", e);
      // Sustained network failure would otherwise spin forever (status never updates, so
      // `_running` stays stale-truthy). Bail after a few consecutive errors.
      if (++pollErrors >= 5) break;
    }
    // Incremental paint: refresh every status symbol, and swap the full row only for
    // tickers that just finished. No table/market/events rebuild, no re-sort jump each tick.
    for (const t of allTickers) {
      const cell = document.getElementById("stat-" + t);
      if (cell) cell.innerHTML = renderStatusSymbol(state.tickerStatus[t]);
    }
    for (const t of justDone) {
      const rowEl = document.getElementById("row-" + t);
      if (rowEl) rowEl.outerHTML = renderRow(t, rowActions);
    }
    if (!state.tickerStatus._running) break;
  }

  // Safety net: guarantee everything is current once the refresh is done, in case any
  // ticker's in_flight window was missed. Merge (don't replace) so tickers added mid-refresh
  // survive, and skip the home repaint if the user has navigated into a detail view.
  try {
    const wlRes = await fetch("/api/watchlist?tickers=" + allTickers.join(","));
    Object.assign(state.watchlistData, await wlRes.json());
    const hash = window.location.hash;
    if (hash === "" || hash === "#home") renderHomeSections();
  } catch (e) {
    console.error("Final refresh failed:", e);
  }

  if (btn) { btn.textContent = "↻ Refresh"; btn.disabled = false; btn.classList.remove("loading"); }
}

async function loadVersionBadge() {
  try {
    const res = await fetch("/api/system/info");
    const d   = await res.json();
    const el  = document.getElementById("yf-badge");
    if (!el) return;
    const installed = d.yfinance_installed || "?";
    const latest    = d.yfinance_latest    || "?";
    const ok        = d.up_to_date;
    el.textContent  = `yf ${installed} / ${latest}`;
    el.className    = "yf-badge " + (ok ? "yf-ok" : "yf-outdated");
    el.title        = ok ? "yfinance is up to date" : `Update available: ${latest}`;
  } catch { /* silently ignore */ }
}

function renderHeader(mode, ticker, refreshedAt) {
  const header = document.getElementById("app-header");
  if (mode === "home") {
    header.innerHTML = `
<div class="header-left">
  <h1>Stocki</h1>
  <span id="yf-badge" class="yf-badge">yf …</span>
</div>
<div class="header-right">
  <div class="search-wrap">
    <input id="add-input" class="search-input" type="text"
           placeholder="Add ticker…" autocomplete="off" spellcheck="false"
           onkeydown="if(event.key==='Enter') handleAddTicker()">
    <button class="btn" onclick="handleAddTicker()">+</button>
  </div>
  <button id="refresh-all-btn" class="btn" onclick="handleRefreshAll()">↻ Refresh</button>
  <button class="btn btn-secondary" onclick="triggerImport()" title="Replace all tickers with a Yahoo Finance portfolio/watchlist CSV export (Yahoo Finance → Portfolio → Export)">↑ Import</button>
  <input id="import-file-input" type="file" accept=".csv" style="display:none" onchange="handleImportFile(event)">
</div>`;
    loadVersionBadge();
  } else {
    const timeStr = refreshedAt
      ? `<span class="subtext" style="font-size:10px;margin-left:8px">Updated ${timeAgo(refreshedAt)}</span>`
      : "";
    header.innerHTML = `
<div class="header-left">
  <button class="btn" onclick="navigate('#home')" style="font-size:12px;padding:4px 10px">← Back</button>
  <h1 style="font-size:14px;letter-spacing:0.06em">${ticker || ""}</h1>
  ${timeStr}
</div>
<div class="header-right"></div>`;
  }
}

// ── Router ────────────────────────────────────────────────────────────────────
function navigate(hash) {
  window.location.hash = hash;
}

function onRoute() {
  hideTooltip();
  state.chartRegistry = {};  // previous view's chart hover-data — its SVGs are gone from the DOM
  const hash = window.location.hash;
  if (hash.startsWith("#ticker/")) {
    const t = hash.slice(8).toUpperCase().replace(/[^A-Z0-9.\-]/g, "");
    if (t) { showDetail(t); return; }
  }
  showHome();
}

window.addEventListener("hashchange", onRoute);
window.addEventListener("DOMContentLoaded", onRoute);

// ── Import tickers from file ──────────────────────────────────────────────────
function triggerImport() {
  const input = document.getElementById("import-file-input");
  if (input) input.click();
}

// Parses a Yahoo Finance portfolio/watchlist CSV export (Yahoo Finance → Portfolio →
// Export). Expected header includes a "Symbol" column, e.g.:
//   Symbol,Current Price,Date,Time,Change,Open,High,Low,Volume,Trade Date,...
//   AAPL,213.4,2026/07/20,16:00 EDT,1.2,...
// Only that column is used — the rest (price, volume, trade history) is ignored.
function parseYahooCsv(text) {
  const lines = text.split(/\r?\n/).map(l => l.trim()).filter(l => l.length > 0);
  if (!lines.length) return { tickers: [], error: "Empty file." };

  const header = lines[0].split(",").map(h => h.trim().toLowerCase());
  const symbolIdx = header.indexOf("symbol");
  if (symbolIdx === -1) {
    return { tickers: [], error: "This doesn't look like a Yahoo Finance export — expected a header row with a \"Symbol\" column. In Yahoo Finance: Portfolio → Export." };
  }

  const tickers = [...new Set(
    lines.slice(1)
      .map(line => (line.split(",")[symbolIdx] || "").trim().toUpperCase())
      // Same charset the server's _TICKER_RE enforces — a CSV Symbol cell flows unescaped into
      // inline onclick handlers, so reject anything that isn't a plain ticker (^RUT indices too).
      .filter(t => /^[A-Z0-9.\-]{1,12}$/.test(t) && !t.startsWith("^"))
  )];
  return { tickers, error: null };
}

async function handleImportFile(event) {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;

  const text = await file.text();
  const { tickers, error } = parseYahooCsv(text);

  if (error) {
    alert(error);
    return;
  }
  if (!tickers.length) {
    alert("No valid tickers found in the Symbol column.");
    return;
  }

  const confirmed = confirm(
    `Warning: this will replace ALL current stocks with ${tickers.length} ticker(s) from the Yahoo Finance export.\n\n` +
    `Tickers: ${tickers.slice(0, 20).join(", ")}${tickers.length > 20 ? ` … (+${tickers.length - 20} more)` : ""}\n\n` +
    `Continue?`
  );
  if (!confirmed) return;

  const res = await fetch("/api/lists/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(tickers),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert("Import failed: " + (err.detail || res.status));
    return;
  }

  const { imported } = await res.json();
  window.location.reload();
}

// ── Tooltip show wrappers ─────────────────────────────────────────────────────
function showScoreTooltip(event, ticker, col){ showOverlay(event, buildScoreTooltip(ticker, col, state.watchlistData[ticker])); }
function showDeltaTooltip(event, ticker){ showOverlay(event, buildDeltaTooltip(ticker, state.watchlistData[ticker])); }
function showBuyTargetTooltip(event, ticker){ showOverlay(event, buildBuyTargetTooltip(ticker, state.watchlistData[ticker])); }

Object.assign(window, {
  navigate, handleAddTicker, handleRefreshAll, removeTicker,
  toggleFavorite, setWlSort, setWlFilter, clearWlFilters, triggerImport,
  handleImportFile, showScoreTooltip, showDeltaTooltip, showBuyTargetTooltip, hideTooltip,
  priceChartHover, chartHoverEnd,
});
