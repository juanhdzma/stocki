import { state } from "./state.js";
import { timeAgo } from "./format.js";
import { _toggleSort, renderTickerTable, renderPortfolioTable } from "./tables.js";
import { render, loadPriceTrend } from "./cards.js";
import { buildScoreTooltip, buildDeltaTooltip, buildBuyTargetTooltip } from "./tooltips.js";
import { showOverlay, hideTooltip } from "./overlay.js";
import { renderMarketBar } from "./market.js";
import { priceChartHover, chartHoverEnd } from "./charts.js";

async function loadLists() {
  const res = await fetch("/api/lists");
  const data = await res.json();
  state.watchlist = data.watchlist;
  state.portfolio = data.portfolio;
  state.portfolioHoldings = data.portfolio_holdings || {};
}

function setPfSort(col) {
  [state.pfSortCol, state.pfSortDir] = _toggleSort(state.pfSortCol, state.pfSortDir, col);
  sessionStorage.setItem("pfSortCol", state.pfSortCol);
  sessionStorage.setItem("pfSortDir", state.pfSortDir);
  renderHomeSections();
}

function setWlSort(col) {
  [state.wlSortCol, state.wlSortDir] = _toggleSort(state.wlSortCol, state.wlSortDir, col);
  sessionStorage.setItem("wlSortCol", state.wlSortCol);
  sessionStorage.setItem("wlSortDir", state.wlSortDir);
  renderHomeSections();
}

function filteredWatchlist() {
  const f = state.wlFilters;
  return state.watchlist.filter(t => {
    const d = state.watchlistData[t];
    if (f.action && d?.scores?.composite_long?.action !== f.action) return false;
    if (f.signal && d?.scores?.buy_target?.signal !== f.signal) return false;
    if (f.sector && (d?.snapshot?.sector || "") !== f.sector) return false;
    return true;
  });
}

function setWlFilter(dim, value) {
  state.wlFilters[dim] = value;
  sessionStorage.setItem("wlFilters", JSON.stringify(state.wlFilters));
  renderHomeSections();
}

function clearWlFilters() {
  state.wlFilters = { action: "", signal: "", sector: "" };
  sessionStorage.setItem("wlFilters", JSON.stringify(state.wlFilters));
  renderHomeSections();
}

function renderWlFilterBar() {
  const f = state.wlFilters;
  const opt = (v, label, cur) => `<option value="${v}"${v === cur ? " selected" : ""}>${label}</option>`;
  const sectors = [...new Set(state.watchlist.map(t => state.watchlistData[t]?.snapshot?.sector).filter(Boolean))].sort();
  const actions = [["STRONG-BUY", "Strong Buy"], ["BUY", "Buy"], ["HOLD", "Hold"], ["SELL", "Sell"], ["STRONG-SELL", "Strong Sell"]];
  const active = f.action || f.signal || f.sector;
  return `<div class="wl-filters">
    <select class="wl-filter${f.action ? " wl-filter-on" : ""}" onchange="setWlFilter('action', this.value)">
      <option value="">Action: all</option>${actions.map(([v, l]) => opt(v, l, f.action)).join("")}
    </select>
    <select class="wl-filter${f.signal ? " wl-filter-on" : ""}" onchange="setWlFilter('signal', this.value)">
      <option value="">Signal: all</option>${opt("buy", "Buy", f.signal)}${opt("wait", "Wait", f.signal)}
    </select>
    <select class="wl-filter${f.sector ? " wl-filter-on" : ""}" onchange="setWlFilter('sector', this.value)">
      <option value="">Sector: all</option>${sectors.map(s => opt(s, s, f.sector)).join("")}
    </select>
    ${active ? `<button class="wl-filter-clear" onclick="clearWlFilters()">✕ clear</button>` : ""}
  </div>`;
}

function editHolding(ticker) {
  state.editingTicker = ticker;
  renderHomeSections();
}

async function saveHolding(ticker) {
  const avgCostEl = document.getElementById(`pf-avgcost-${ticker}`);
  const sharesEl  = document.getElementById(`pf-shares-${ticker}`);
  const avg_cost  = avgCostEl && avgCostEl.value !== "" ? parseFloat(avgCostEl.value) : null;
  const shares    = sharesEl && sharesEl.value !== "" ? parseFloat(sharesEl.value) : null;
  await fetch(`/api/portfolio/${ticker}/holding`, {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({avg_cost, shares}),
  });
  state.portfolioHoldings[ticker] = {avg_cost, shares};
  state.editingTicker = null;
  renderHomeSections();
}

function cancelEdit() {
  state.editingTicker = null;
  renderHomeSections();
}

function renderHomeSections() {
  const dash = document.getElementById("dashboard");

  if (!state.portfolio.length && !state.watchlist.length) {
    dash.innerHTML = `<p class="subtext center" style="margin-top:60px">Add a ticker above to start.</p>`;
    return;
  }

  let html = renderMarketBar(state.market, state.watchlistData);

  if (state.portfolio.length) {
    const pfTotal = state.portfolio.reduce((sum, t) => {
      const price  = state.portfolioData[t]?.price ?? state.watchlistData[t]?.snapshot?.price;
      const shares = state.portfolioHoldings[t]?.shares;
      return (price != null && shares != null) ? sum + price * shares : sum;
    }, 0);
    const pfTotalStr = pfTotal > 0
      ? `$${pfTotal.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2})}`
      : "";
    html += `<section class="cat-section watchlist-section">
      <h2>Portfolio ${pfTotalStr ? `<span class="pf-total-badge">${pfTotalStr}</span>` : ""}</h2>
      ${renderPortfolioTable(state.portfolio)}
    </section>`;
  }

  if (state.watchlist.length) {
    const wlTickers = filteredWatchlist();
    html += `<section class="cat-section watchlist-section">
      <h2>Watchlist <span class="subtext" style="font-size:13px;font-weight:400">${wlTickers.length}/${state.watchlist.length}</span></h2>
      ${renderWlFilterBar()}
      ${wlTickers.length
        ? renderTickerTable(wlTickers, state.wlSortCol, state.wlSortDir, "setWlSort",
          t => `${!state.portfolio.includes(t)
            ? `<button class="btn-move" title="Add to portfolio" onclick="moveToPortfolio('${t}')">↑ PF</button>`
            : ""}
                <button class="btn-remove" onclick="removeTicker('${t}')">✕</button>`,
          false
        )
        : `<p class="subtext center" style="margin:24px 0">No results for this filter.</p>`}
    </section>`;
  }

  dash.innerHTML = html;
}

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

  try { await loadLists(); } catch (e) { console.error("Failed to load lists:", e); }

  const allTickers = [...new Set([...state.portfolio, ...state.watchlist])];
  if (!allTickers.length) {
    dash.innerHTML = `<p class="subtext center" style="margin-top:60px">Add a ticker above to start.</p>`;
    return;
  }

  try {
    const [wlRes, pfRes, stRes, mkRes] = await Promise.all([
      fetch("/api/watchlist?tickers=" + allTickers.join(",")),
      fetch("/api/portfolio/prices"),
      fetch("/api/status?tickers="   + allTickers.join(",")),
      fetch("/api/market").catch(() => null),
    ]);
    state.watchlistData = await wlRes.json();
    state.tickerStatus  = await stRes.json();
    const pfRaw   = await pfRes.json();
    const { _running, ...pfPrices } = pfRaw;
    state.portfolioData = pfPrices;
    if (mkRes && mkRes.ok) state.market = await mkRes.json();
  } catch (e) {
    console.error("Home load failed:", e);
  }

  renderHomeSections();
}

async function handleAddTicker() {
  const input = document.getElementById("add-input");
  if (!input) return;
  const ticker = input.value.trim().toUpperCase();
  if (!ticker || !/^[A-Z0-9.]{1,10}$/.test(ticker)) { input.value = ""; return; }
  if (state.portfolio.includes(ticker) || state.watchlist.includes(ticker)) { input.value = ""; return; }

  input.value = "";
  await fetch(`/api/lists/${ticker}`, {method: "POST"});
  state.watchlist.push(ticker);
  state.watchlistData[ticker] = null;
  renderHomeSections();

  try {
    await fetch("/api/lookup/" + ticker);
    const allTickers = [...new Set([...state.portfolio, ...state.watchlist])];
    const res = await fetch("/api/watchlist?tickers=" + allTickers.join(","));
    state.watchlistData = await res.json();
  } catch (e) {
    console.error("Fetch failed for", ticker, e);
  }

  renderHomeSections();
}

async function removeTicker(ticker) {
  await fetch(`/api/lists/${ticker}`, {method: "DELETE"});
  state.portfolio = state.portfolio.filter(t => t !== ticker);
  state.watchlist = state.watchlist.filter(t => t !== ticker);
  delete state.watchlistData[ticker];
  delete state.portfolioHoldings[ticker];
  if (state.editingTicker === ticker) state.editingTicker = null;
  renderHomeSections();
}

async function _moveTicker(ticker, targetList) {
  await fetch(`/api/lists/${ticker}?list_type=${targetList}`, {method: "PATCH"});
  if (targetList === "portfolio") {
    if (!state.portfolio.includes(ticker)) state.portfolio.push(ticker);
    state.portfolioHoldings[ticker] = { avg_cost: null, shares: null };
  } else {
    state.portfolio = state.portfolio.filter(t => t !== ticker);
    delete state.portfolioHoldings[ticker];
    if (state.editingTicker === ticker) state.editingTicker = null;
  }
  renderHomeSections();
}

async function moveToPortfolio(ticker) {
  await _moveTicker(ticker, "portfolio");
}

async function moveToWatchlist(ticker) {
  await _moveTicker(ticker, "watchlist");
}

// ── Detail view ───────────────────────────────────────────────────────────────
async function _fetchAndRenderDetail(ticker) {
  const res = await fetch("/api/watchlist?tickers=" + ticker);
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
  const allTickers = [...new Set([...state.portfolio, ...state.watchlist])];
  if (!allTickers.length) return;
  const btn = document.getElementById("refresh-all-btn");
  if (btn) { btn.textContent = "↻ …"; btn.disabled = true; btn.classList.add("loading"); }

  await fetch("/api/refresh", { method: "POST" }).catch(() => {});

  // Full /api/watchlist recomputes scores for every tracked ticker — too heavy to
  // re-poll wholesale every 2s. Instead poll the cheap /api/status, and only re-fetch
  // watchlist data for tickers whose refresh just finished (in_flight -> not in_flight).
  let prevStatus = { ...state.tickerStatus };

  while (true) {
    await new Promise(r => setTimeout(r, 2000));
    try {
      const stRes = await fetch("/api/status?tickers=" + allTickers.join(","));
      const newStatus = await stRes.json();

      const justDone = allTickers.filter(
        t => _isInFlight(prevStatus, t) && !_isInFlight(newStatus, t)
      );

      state.tickerStatus = newStatus;
      prevStatus   = newStatus;

      if (justDone.length) {
        const wlRes = await fetch("/api/watchlist?tickers=" + justDone.join(","));
        Object.assign(state.watchlistData, await wlRes.json());
      }
    } catch (e) {
      console.error("Poll failed:", e);
    }
    renderHomeSections();
    if (!state.tickerStatus._running) break;
  }

  // Safety net: guarantee everything is current once the refresh is done, in case
  // any ticker's in_flight window was missed between two 2s polls.
  try {
    const wlRes = await fetch("/api/watchlist?tickers=" + allTickers.join(","));
    state.watchlistData = await wlRes.json();
    renderHomeSections();
  } catch (e) {
    console.error("Final refresh failed:", e);
  }

  if (btn) { btn.textContent = "↻ Refresh"; btn.disabled = false; btn.classList.remove("loading"); }
}

async function handleRescore() {
  const allTickers = [...new Set([...state.portfolio, ...state.watchlist])];
  if (!allTickers.length) return;
  const btn = document.getElementById("rescore-btn");
  if (btn) { btn.textContent = "⟲ …"; btn.disabled = true; btn.classList.add("loading"); }

  try {
    const wlRes = await fetch("/api/watchlist?tickers=" + allTickers.join(","));
    state.watchlistData = await wlRes.json();
    renderHomeSections();
  } catch (e) {
    console.error("Rescore failed:", e);
  }

  if (btn) { btn.textContent = "⟲ Rescore"; btn.disabled = false; btn.classList.remove("loading"); }
}

async function handleRefreshPortfolio() {
  if (!state.portfolio.length) return;
  const btn = document.getElementById("refresh-pf-btn");
  if (btn) { btn.textContent = "↻ …"; btn.disabled = true; btn.classList.add("loading"); }

  await fetch("/api/portfolio/refresh", { method: "POST" }).catch(() => {});

  while (true) {
    await new Promise(r => setTimeout(r, 1500));
    try {
      const res = await fetch("/api/portfolio/prices");
      const raw = await res.json();
      const { _running, ...pfPrices } = raw;
      state.portfolioData = pfPrices;
      renderHomeSections();
      if (!_running) break;
    } catch (e) {
      console.error("Portfolio price poll failed:", e);
      break;
    }
  }

  if (btn) { btn.textContent = "↻ Portfolio"; btn.disabled = false; btn.classList.remove("loading"); }
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
  <button id="rescore-btn" class="btn btn-secondary" onclick="handleRescore()" title="Recompute scores from cached DB data — no external fetch">⟲ Rescore</button>
</div>
<div class="header-right">
  <div class="search-wrap">
    <input id="add-input" class="search-input" type="text"
           placeholder="Add ticker…" autocomplete="off" spellcheck="false"
           onkeydown="if(event.key==='Enter') handleAddTicker()">
    <button class="btn" onclick="handleAddTicker()">+</button>
  </div>
  <button id="refresh-all-btn" class="btn" onclick="handleRefreshAll()">↻ Watchlist</button>
  <button id="refresh-pf-btn" class="btn btn-secondary" onclick="handleRefreshPortfolio()">↻ Portfolio</button>
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
  const hash = window.location.hash;
  if (hash.startsWith("#ticker/")) {
    const t = hash.slice(8).toUpperCase().replace(/[^A-Z0-9.]/g, "");
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
      .filter(t => t.length > 0 && t.length <= 12 && !t.startsWith("^"))  // ^RUT etc. are indices, not tickers
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
  navigate, handleAddTicker, handleRefreshAll, handleRescore, removeTicker,
  moveToPortfolio, moveToWatchlist, setPfSort, setWlSort, setWlFilter, clearWlFilters, triggerImport,
  handleImportFile, showScoreTooltip, showDeltaTooltip, showBuyTargetTooltip, hideTooltip,
  editHolding, saveHolding, cancelEdit, handleRefreshPortfolio,
  priceChartHover, chartHoverEnd,
});
