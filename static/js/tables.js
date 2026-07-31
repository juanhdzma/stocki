import { state } from "./state.js";
import { timeAgo, escapeHtml } from "./format.js";
import { scoreColor, pctScoreColor, actionBadge, fmtBuyTargetHtml, fmt52wRangeHtml } from "./colors.js";

export function getScore(d, col) {
  if (!d) return null;
  const snap = d.snapshot || {};
  const ret  = d.returns  || {};
  const s    = d.scores   || {};
  switch (col) {
    case "ticker":           return null;
    case "price":            return snap.price            ?? null;
    case "day_change":       return snap.day_change_pct   ?? null;
    case "week_change":      return ret.ticker_return_1w  ?? null;
    case "month_change":     return ret.ticker_return_1m  ?? null;
    case "buy_target":       return s.buy_target?.pct_from_current ?? null;
    case "growth":           return s.fundamental_momentum?.score ?? null;
    case "quality":          return s.value_quality?.score        ?? null;
    case "insiders":         return s.insider_conviction?.score   ?? null;
    case "price_long":       return s.price_long?.score           ?? null;
    case "composite_long":   return s.composite_long?.score       ?? null;
    case "score_delta":      return d.score_change?.composite?.delta ?? null;
    default: return null;
  }
}

export function _toggleSort(currentCol, currentDir, col) {
  return currentCol === col ? [currentCol, currentDir * -1] : [col, -1];
}

export const PRICE_COLS = [
  { key: "price",         label: "Price"  },
  { key: "day_change",    label: "Day %"  },
  { key: "week_change",   label: "1W %"   },
  { key: "month_change",  label: "1M %"   },
  { key: "buy_target",    label: "Buy Target" },
];

export const SCORE_COLS_INTERMEDIATE = [
  { key: "growth",      label: "Growth"    },
  { key: "quality",     label: "Quality"   },
  { key: "insiders",    label: "Insiders"  },
  { key: "price_long",  label: "Valuation" },
];

export const SCORE_COLS_FINAL = [
  { key: "composite_long",  label: "Score" },
];

export const SCORE_COLS = [...SCORE_COLS_INTERMEDIATE, ...SCORE_COLS_FINAL];

// One compact symbol per row: fetch in progress / all good / something failed.
export function renderStatusSymbol(status) {
  if (!status) return `<span class="subtext" title="Pending">·</span>`;
  const states = ["snap", "fund", "qtrs", "ins", "score"].map(k => status[k]);
  if (states.includes("yellow")) return `<span class="s-yellow" title="In progress">⟳</span>`;
  if (states.includes("red"))    return `<span class="s-red" title="Fetch failed">✕</span>`;
  if (status.score === "green")  return `<span class="s-green" title="OK">✓</span>`;
  return `<span class="subtext" title="Partial data">·</span>`;
}

export function renderTickerTable(tickers, sc, sd, sortFnName, actionCell) {
  const sorted = [...tickers].sort((a, b) => {
    if (sc === "ticker") return a.localeCompare(b) * sd;
    const va = getScore(state.watchlistData[a], sc);
    const vb = getScore(state.watchlistData[b], sc);
    if (va === null && vb === null) return 0;
    if (va === null) return 1;
    if (vb === null) return -1;
    return (va - vb) * sd;
  });

  // Keyboard + screen-reader support for the sort headers (they're <th>, not buttons):
  // focusable, Enter/Space triggers the sort, and aria-sort announces the active direction.
  const sortAttrs = key =>
    `tabindex="0" aria-sort="${key === sc ? (sd > 0 ? "ascending" : "descending") : "none"}" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();this.click()}"`;

  const thCell = c => {
    const active = c.key === sc;
    const arrow  = active ? (sd > 0 ? " ↑" : " ↓") : "";
    return `<th class="sortable-th${active ? " sort-active" : ""}" ${sortAttrs(c.key)} onclick="${sortFnName}('${c.key}')">${c.label}${arrow}</th>`;
  };

  const sepTh = (c, extra = "") =>
    `<th class="col-sep ${extra} sortable-th${c.key === sc ? " sort-active" : ""}" ${sortAttrs(c.key)} onclick="${sortFnName}('${c.key}')">${c.label}${c.key === sc ? (sd > 0 ? " ↑" : " ↓") : ""}</th>`;

  const sortTh = (key, label, extraClass = "") => {
    const active = key === sc;
    const arrow  = active ? (sd > 0 ? " ↑" : " ↓") : "";
    return `<th class="${extraClass} sortable-th${active ? " sort-active" : ""}" ${sortAttrs(key)} onclick="${sortFnName}('${key}')">${label}${arrow}</th>`;
  };

  const head = `<thead><tr>
    ${sortTh("ticker", "Ticker", "col-ticker")}
    <th style="text-align:left">Sector</th>
    ${sortTh("price",       "Price",  "col-sep")}
    ${sortTh("day_change",  "Day %")}
    ${sortTh("week_change", "1W %")}
    ${sortTh("month_change", "1M %")}
    ${sortTh("buy_target",  "Buy Target")}
    ${SCORE_COLS_INTERMEDIATE.map((c, i) => i === 0 ? sepTh(c) : thCell(c)).join("")}
    ${SCORE_COLS_FINAL.map((c, i) => i === 0 ? sepTh(c, "col-final") : `<th class="col-final sortable-th${c.key === sc ? " sort-active" : ""}" ${sortAttrs(c.key)} onclick="${sortFnName}('${c.key}')">${c.label}${c.key === sc ? (sd > 0 ? " ↑" : " ↓") : ""}</th>`).join("")}
    ${sortTh("score_delta", "Δ7d", "col-sep")}
    <th class="col-sep">Updated</th>
    <th title="Data status" style="text-align:center;cursor:default">·</th>
    <th></th>
  </tr></thead>`;

  const rows = sorted.map(ticker => renderRow(ticker, actionCell)).join("");

  return `<div class="table-scroll"><table class="watchlist-table">${head}<tbody>${rows}</tbody></table></div>`;
}

// One table row. Extracted so the refresh poller can swap a single ticker's row
// (`#row-<t>`) or just its status cell (`#stat-<t>`) in place instead of re-rendering
// the whole table each 2s. The two ids are the only addition vs. the inline version.
export function renderRow(ticker, actionCell) {
  const d      = state.watchlistData[ticker];
  const snap   = d?.snapshot || {};
  const name   = snap?.name   || null;
  const sector = snap?.sector || "—";

  const tickerCell = `<td class="td-ticker">
    <div>
      <a class="ticker-link" href="#ticker/${ticker}">${ticker}</a>
      ${d ? `<span style="margin-left:6px">${d.data_ready ? actionBadge(d.scores) : `<span class="action-badge action-NA">?</span>`}</span>` : ""}
    </div>
    ${name ? `<div class="ticker-company">${escapeHtml(name)}</div>` : ""}
  </td>`;

  if (!d) {
    return `<tr id="row-${ticker}">
      ${tickerCell}
      <td class="td-sector">—</td>
      <td colspan="${PRICE_COLS.length}" class="col-sep subtext" style="font-size:11px">No data</td>
      <td colspan="${SCORE_COLS_INTERMEDIATE.length}" class="col-sep subtext">—</td>
      <td colspan="${SCORE_COLS_FINAL.length}" class="col-sep subtext">—</td>
      <td class="col-sep subtext">—</td>
      <td class="col-sep subtext">—</td>
      <td id="stat-${ticker}" style="text-align:center">${renderStatusSymbol(state.tickerStatus[ticker])}</td>
      <td>${actionCell(ticker)}</td>
    </tr>`;
  }

  const ready = d.data_ready;
  const ret   = d?.returns  || {};

  const fmtPct = (v, scale = 0.15) => {
    if (v == null) return "—";
    return `<span class="${pctScoreColor(v, scale)}">${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%</span>`;
  };
  const fmtDay = v => fmtPct(v, 0.03);

  const buyTarget = d.scores?.buy_target;

  const priceCells = `
    <td class="col-sep">${fmt52wRangeHtml(snap.price, snap.week52_low, snap.week52_high)}</td>
    <td style="font-variant-numeric:tabular-nums">${fmtDay(snap.day_change_pct != null ? snap.day_change_pct / 100 : null)}</td>
    <td style="font-variant-numeric:tabular-nums">${fmtPct(ret.ticker_return_1w)}</td>
    <td style="font-variant-numeric:tabular-nums">${fmtPct(ret.ticker_return_1m, 0.25)}</td>
    <td style="font-variant-numeric:tabular-nums"
      onmouseenter="showBuyTargetTooltip(event,'${ticker}')" onmouseleave="hideTooltip()">${fmtBuyTargetHtml(buyTarget)}</td>
  `;

  const makeScoreCell = (c, extraClass = "") => {
    if (!ready) return `<td class="s-null ${extraClass}"
      onmouseenter="showScoreTooltip(event,'${ticker}','${c.key}')"
      onmouseleave="hideTooltip()">?</td>`;
    const s = getScore(d, c.key);
    return `<td class="${scoreColor(s)} ${extraClass}"
      onmouseenter="showScoreTooltip(event,'${ticker}','${c.key}')"
      onmouseleave="hideTooltip()">${s != null ? s.toFixed(1) : "—"}</td>`;
  };

  const deltaCell = (() => {
    const delta = d.score_change?.composite?.delta;
    if (!ready || delta == null) return `<td class="s-null col-sep"
      onmouseenter="showDeltaTooltip(event,'${ticker}')"
      onmouseleave="hideTooltip()">—</td>`;
    const cls  = delta > 0.05 ? "s-green" : delta < -0.05 ? "s-red" : "s-yellow";
    const sign = delta > 0 ? "+" : "";
    return `<td class="${cls} col-sep"
      onmouseenter="showDeltaTooltip(event,'${ticker}')"
      onmouseleave="hideTooltip()">${sign}${delta.toFixed(1)}</td>`;
  })();

  const intermediateCells = SCORE_COLS_INTERMEDIATE.map((c, i) => makeScoreCell(c, i === 0 ? "col-sep" : "")).join("");
  const finalCells        = SCORE_COLS_FINAL.map((c, i) => makeScoreCell(c, i === 0 ? "col-sep col-final" : "col-final")).join("");

  const refreshed = timeAgo(d.refreshed_at);

  return `<tr id="row-${ticker}">
    ${tickerCell}
    <td class="td-sector">${escapeHtml(sector)}</td>
    ${priceCells}
    ${intermediateCells}
    ${finalCells}
    ${deltaCell}
    ${ready
      ? `<td class="col-sep subtext">${refreshed}</td>`
      : `<td class="col-sep s-null" style="font-size:10px">loading…</td>`}
    <td id="stat-${ticker}" style="text-align:center">${renderStatusSymbol(state.tickerStatus[ticker])}</td>
    <td style="text-align:right;white-space:nowrap">${actionCell(ticker)}</td>
  </tr>`;
}
