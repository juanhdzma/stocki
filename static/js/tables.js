import { state } from "./state.js";
import { fmtRaw, timeAgo, escapeHtml } from "./format.js";
import { scoreColor, pctScoreColor, actionBadge, actionLabel, fmtBuyTargetHtml, fmt52wRangeHtml } from "./colors.js";

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
  { key: "price_long",  label: "Sentiment" },
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

export function renderTickerTable(tickers, sc, sd, sortFnName, actionCell, pfCols = false) {
  const sorted = [...tickers].sort((a, b) => {
    if (sc === "ticker") return a.localeCompare(b) * sd;
    const va = getScore(state.watchlistData[a], sc);
    const vb = getScore(state.watchlistData[b], sc);
    if (va === null && vb === null) return 0;
    if (va === null) return 1;
    if (vb === null) return -1;
    return (va - vb) * sd;
  });

  const thCell = c => {
    const active = c.key === sc;
    const arrow  = active ? (sd > 0 ? " ↑" : " ↓") : "";
    return `<th class="sortable-th${active ? " sort-active" : ""}" onclick="${sortFnName}('${c.key}')">${c.label}${arrow}</th>`;
  };

  const sepTh = (c, extra = "") =>
    `<th class="col-sep ${extra} sortable-th${c.key === sc ? " sort-active" : ""}" onclick="${sortFnName}('${c.key}')">${c.label}${c.key === sc ? (sd > 0 ? " ↑" : " ↓") : ""}</th>`;

  const sortTh = (key, label, extraClass = "") => {
    const active = key === sc;
    const arrow  = active ? (sd > 0 ? " ↑" : " ↓") : "";
    return `<th class="${extraClass} sortable-th${active ? " sort-active" : ""}" onclick="${sortFnName}('${key}')">${label}${arrow}</th>`;
  };

  const pfHeaders = pfCols ? `
    <th class="col-sep pf-col" style="text-align:right">Avg Cost</th>
    <th class="pf-col" style="text-align:right">Shares</th>
    <th class="pf-col" style="text-align:right">Total</th>
    <th class="pf-col" style="text-align:right">Diff</th>` : "";

  const head = `<thead><tr>
    ${sortTh("ticker", "Ticker", "col-ticker")}
    <th style="text-align:left">Sector</th>
    ${sortTh("price",       "Price",  "col-sep")}
    ${sortTh("day_change",  "Day %")}
    ${sortTh("week_change", "1W %")}
    ${sortTh("month_change", "1M %")}
    ${sortTh("buy_target",  "Buy Target")}
    ${pfHeaders}
    ${SCORE_COLS_INTERMEDIATE.map((c, i) => i === 0 ? sepTh(c) : thCell(c)).join("")}
    ${SCORE_COLS_FINAL.map((c, i) => i === 0 ? sepTh(c, "col-final") : `<th class="col-final sortable-th${c.key === sc ? " sort-active" : ""}" onclick="${sortFnName}('${c.key}')">${c.label}${c.key === sc ? (sd > 0 ? " ↑" : " ↓") : ""}</th>`).join("")}
    ${sortTh("score_delta", "Δ7d", "col-sep")}
    <th class="col-sep">Updated</th>
    <th title="Data status" style="text-align:center;cursor:default">·</th>
    <th></th>
  </tr></thead>`;

  const rows = sorted.map(ticker => {
    const d      = state.watchlistData[ticker];
    const snap   = d?.snapshot || {};
    const name   = snap?.name   || null;
    const sector = snap?.sector || "—";

    const tickerCell = `<td class="td-ticker">
      <div>
        <span class="ticker-link" onclick="navigate('#ticker/${ticker}')">${ticker}</span>
        ${d ? `<span style="margin-left:6px">${d.data_ready ? actionBadge(d.scores) : `<span class="action-badge action-NA">?</span>`}</span>` : ""}
      </div>
      ${name ? `<div class="ticker-company">${escapeHtml(name)}</div>` : ""}
    </td>`;

    if (!d) {
      return `<tr>
        ${tickerCell}
        <td class="td-sector">—</td>
        <td colspan="${PRICE_COLS.length}" class="col-sep subtext" style="font-size:11px">No data</td>
        ${pfCols ? `<td colspan="4" class="col-sep pf-col subtext">—</td>` : ""}
        <td colspan="${SCORE_COLS_INTERMEDIATE.length}" class="col-sep subtext">—</td>
        <td colspan="${SCORE_COLS_FINAL.length}" class="col-sep subtext">—</td>
        <td class="col-sep subtext">—</td>
        <td class="col-sep subtext">—</td>
        <td style="text-align:center">${renderStatusSymbol(state.tickerStatus[ticker])}</td>
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

    let pfCells = "";
    if (pfCols) {
      const holding  = state.portfolioHoldings[ticker] || {};
      const avgCost  = holding.avg_cost;
      const shares   = holding.shares;
      const price    = snap.price;
      const total    = (shares != null && price != null) ? shares * price : null;
      const diffAbs  = (avgCost != null && shares != null && price != null) ? (price - avgCost) * shares : null;
      const diffPct  = (avgCost != null && price != null && avgCost > 0) ? (price - avgCost) / avgCost : null;
      const isEditing = state.editingTicker === ticker;

      const fmtAvgCost = v => v != null ? `$${Number(v).toFixed(2)}` : "—";
      const fmtShares  = v => v != null ? Number(v).toLocaleString(undefined, {maximumFractionDigits: 4}) : "—";
      const fmtTotal   = v => v != null ? `$${fmtRaw(v, "large")}` : "—";
      const fmtDiff    = (pct, abs) => {
        if (pct == null) return "—";
        const cls  = pct > 0.001 ? "s-green" : pct < -0.001 ? "s-red" : "s-yellow";
        const sign = pct >= 0 ? "+" : "";
        const absFmt = abs != null ? ` <span class="subtext" style="font-size:10px">(${abs >= 0 ? "+" : ""}$${Math.abs(abs).toFixed(0)})</span>` : "";
        return `<span class="${cls}">${sign}${(pct * 100).toFixed(1)}%</span>${absFmt}`;
      };

      const avgCostCell = isEditing
        ? `<input class="pf-input" id="pf-avgcost-${ticker}" type="number" step="0.01" min="0" placeholder="Avg cost" value="${avgCost ?? ""}" onkeydown="if(event.key==='Enter') saveHolding('${ticker}')">`
        : fmtAvgCost(avgCost);
      const sharesCell = isEditing
        ? `<input class="pf-input" id="pf-shares-${ticker}" type="number" step="1" min="0" placeholder="Shares" value="${shares ?? ""}" onkeydown="if(event.key==='Enter') saveHolding('${ticker}')">`
        : fmtShares(shares);

      pfCells = `
        <td class="col-sep pf-col">${avgCostCell}</td>
        <td class="pf-col">${sharesCell}</td>
        <td class="pf-col">${fmtTotal(total)}</td>
        <td class="pf-col">${fmtDiff(diffPct, diffAbs)}</td>`;
    }

    return `<tr>
      ${tickerCell}
      <td class="td-sector">${escapeHtml(sector)}</td>
      ${priceCells}
      ${pfCells}
      ${intermediateCells}
      ${finalCells}
      ${deltaCell}
      ${ready
        ? `<td class="col-sep subtext">${refreshed}</td>`
        : `<td class="col-sep s-null" style="font-size:10px">loading…</td>`}
      <td style="text-align:center">${renderStatusSymbol(state.tickerStatus[ticker])}</td>
      <td style="text-align:right;white-space:nowrap">${actionCell(ticker)}</td>
    </tr>`;
  }).join("");

  return `<table class="watchlist-table">${head}<tbody>${rows}</tbody></table>`;
}

export function getPfPrice(ticker, col) {
  const d  = state.portfolioData[ticker];
  const wd = state.watchlistData[ticker];
  const price     = d?.price          ?? wd?.snapshot?.price;
  const holding   = state.portfolioHoldings[ticker] || {};
  const avgCost   = holding.avg_cost  ?? null;
  const shares    = holding.shares    ?? null;
  const total     = (shares != null && price != null) ? shares * price : null;
  // avg_cost is a per-share cost, so P&L is priced per share, not against the whole position value.
  const diffPct   = (avgCost != null && price != null && avgCost > 0) ? (price - avgCost) / avgCost : null;
  switch (col) {
    case "ticker":      return null;
    case "price":       return price ?? null;
    case "day_change":  return (d?.day_change_pct  ?? wd?.snapshot?.day_change_pct) ?? null;
    case "week_change": return (d?.return_1w        ?? wd?.returns?.ticker_return_1w) ?? null;
    case "month_change": return (d?.return_1m       ?? wd?.returns?.ticker_return_1m) ?? null;
    case "pct_52w":    return wd?.snapshot?.pct_from_52w_high ?? null;
    case "cost_basis":  return avgCost;
    case "shares":      return shares;
    case "total":       return total;
    case "diff_pct":    return diffPct;
    default: return null;
  }
}

export function renderPortfolioTable(tickers) {
  const sc = state.pfSortCol, sd = state.pfSortDir;

  const sorted = [...tickers].sort((a, b) => {
    if (sc === "ticker") return a.localeCompare(b) * sd;
    const va = getPfPrice(a, sc);
    const vb = getPfPrice(b, sc);
    if (va === null && vb === null) return 0;
    if (va === null) return 1;
    if (vb === null) return -1;
    return (va - vb) * sd;
  });

  const sortTh = (key, label, extraClass = "", style = "") => {
    const active = key === sc;
    const arrow  = active ? (sd > 0 ? " ↑" : " ↓") : "";
    const styleAttr = style ? ` style="${style}"` : "";
    return `<th class="${extraClass} sortable-th${active ? " sort-active" : ""}"${styleAttr} onclick="setPfSort('${key}')">${label}${arrow}</th>`;
  };

  const head = `<thead><tr>
    ${sortTh("ticker",     "Ticker",     "col-ticker")}
    ${sortTh("price",      "Price",      "col-sep")}
    ${sortTh("day_change", "Day %")}
    ${sortTh("week_change","1W %")}
    ${sortTh("month_change","1M %")}
    ${sortTh("pct_52w",   "vs 52W")}
    <th class="col-sep" style="text-align:center">Score</th>
    <th style="text-align:left">Buy Target</th>
    ${sortTh("cost_basis", "Avg Cost", "col-sep pf-col", "text-align:right")}
    ${sortTh("shares",     "Shares",     "pf-col",          "text-align:right")}
    ${sortTh("total",      "Total",      "pf-col",          "text-align:right")}
    ${sortTh("diff_pct",   "Diff",       "pf-col",          "text-align:right")}
    <th class="col-sep" style="text-align:right">Updated</th>
    <th></th>
  </tr></thead>`;

  const fmtPct = (v, scale = 0.15) => {
    if (v == null) return "—";
    return `<span class="${pctScoreColor(v, scale)}">${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%</span>`;
  };
  const fmtDay   = v => fmtPct(v, 0.03);

  const rows = sorted.map(ticker => {
    const pd      = state.portfolioData[ticker];
    const wd      = state.watchlistData[ticker];
    const holding = state.portfolioHoldings[ticker] || {};

    const name      = wd?.snapshot?.name || pd?.name || null;
    const isEditing = state.editingTicker === ticker;

    const tickerCell = `<td class="td-ticker">
      <div>
        <span class="ticker-link" onclick="navigate('#ticker/${ticker}')">${ticker}</span>
        <span style="margin-left:6px">${actionBadge(wd?.scores)}</span>
      </div>
      ${name ? `<div class="ticker-company">${escapeHtml(name)}</div>` : ""}
    </td>`;

    const price      = pd?.price           ?? wd?.snapshot?.price;
    const dayChg     = pd?.day_change_pct  ?? wd?.snapshot?.day_change_pct;
    const ret1w      = pd?.return_1w       ?? wd?.returns?.ticker_return_1w;
    const ret1m      = pd?.return_1m       ?? wd?.returns?.ticker_return_1m;
    const ath        = wd?.snapshot?.week52_high ?? pd?.ath;
    const pct52w     = wd?.snapshot?.pct_from_52w_high ?? null;
    const refreshed  = pd ? timeAgo(pd.refreshed_at) : (wd?.refreshed_at ? timeAgo(wd.refreshed_at) : "—");

    const priceCells = `
      <td class="col-sep">${fmt52wRangeHtml(price, wd?.snapshot?.week52_low, ath)}</td>
      <td style="font-variant-numeric:tabular-nums">${fmtDay(dayChg != null ? dayChg / 100 : null)}</td>
      <td style="font-variant-numeric:tabular-nums">${fmtPct(ret1w)}</td>
      <td style="font-variant-numeric:tabular-nums">${fmtPct(ret1m, 0.25)}</td>
      <td style="font-variant-numeric:tabular-nums">${fmtPct(pct52w, 0.30)}</td>`;

    const avgCost   = holding.avg_cost;
    const shares    = holding.shares;
    const total     = (shares != null && price != null) ? shares * price : null;
    // avg_cost is per-share: P&L = (price - avg_cost) * shares, priced per share — not
    // the whole position value minus a per-share number.
    const diffAbs   = (avgCost != null && shares != null && price != null) ? (price - avgCost) * shares : null;
    const diffPct   = (avgCost != null && price != null && avgCost > 0) ? (price - avgCost) / avgCost : null;

    const fmtAvgCost = v => v != null ? `$${Number(v).toFixed(2)}` : "—";
    const fmtShares  = v => v != null ? parseFloat(v).toString() : "—";
    const fmtTotal   = v => v != null ? `$${Number(v).toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2})}` : "—";
    const fmtDiff    = (pct, abs) => {
      if (pct == null) return "—";
      const sign = pct >= 0 ? "+" : "";
      const absFmt = abs != null ? ` <span class="subtext" style="font-size:10px">(${abs >= 0 ? "+" : ""}$${Math.abs(abs).toFixed(0)})</span>` : "";
      return `<span class="${pctScoreColor(pct, 0.30)}">${sign}${(pct * 100).toFixed(1)}%</span>${absFmt}`;
    };

    const costBasisCell = isEditing
      ? `<input class="pf-input" id="pf-avgcost-${ticker}" type="number" step="0.01" min="0" placeholder="Avg cost" value="${avgCost ?? ""}" onkeydown="if(event.key==='Enter') saveHolding('${ticker}')">`
      : fmtAvgCost(avgCost);
    const sharesCell = isEditing
      ? `<input class="pf-input" id="pf-shares-${ticker}" type="number" step="1" min="0" placeholder="Shares" value="${shares ?? ""}" onkeydown="if(event.key==='Enter') saveHolding('${ticker}')">`
      : fmtShares(shares);

    // Thesis-aware: a held name that's in profit but whose verdict decayed to HOLD/SELL is
    // the "up 40% and it just turned SELL" case — flag it so the P&L doesn't hide the rot.
    const action    = wd?.scores?.composite_long?.action;
    const longScore = wd?.scores?.composite_long?.score;
    const decayed   = ["HOLD", "SELL", "STRONG-SELL"].includes(action);
    const thesisWarn = (diffPct != null && diffPct > 0.05 && decayed)
      ? ` <span class="risk-flag risk-rev" title="In profit but the verdict is now ${actionLabel(action)} — thesis decayed">⚠</span>` : "";
    const scoreCell = `<td class="col-sep ${scoreColor(longScore)}" style="text-align:center"
        onmouseenter="${wd ? `showScoreTooltip(event,'${ticker}','composite_long')` : ''}"
        onmouseleave="hideTooltip()">${longScore != null ? longScore.toFixed(1) : "—"}</td>`;
    const btCell = `<td style="font-variant-numeric:tabular-nums"
        onmouseenter="showBuyTargetTooltip(event,'${ticker}')" onmouseleave="hideTooltip()">${fmtBuyTargetHtml(wd?.scores?.buy_target)}</td>`;

    const holdingCells = `
      <td class="col-sep pf-col">${costBasisCell}</td>
      <td class="pf-col">${sharesCell}</td>
      <td class="pf-col">${fmtTotal(total)}</td>
      <td class="pf-col">${fmtDiff(diffPct, diffAbs)}${thesisWarn}</td>`;

    const actionCell = isEditing
      ? `<button class="btn-save" onclick="saveHolding('${ticker}')">✓ Save</button>
         <button class="btn-remove" onclick="cancelEdit()">✕</button>`
      : `<button class="btn-edit" onclick="editHolding('${ticker}')">Edit</button>
         <button class="btn-move" title="Remove from portfolio" onclick="moveToWatchlist('${ticker}')">↓ WL</button>
         <button class="btn-remove" onclick="removeTicker('${ticker}')">✕</button>`;

    return `<tr>
      ${tickerCell}
      ${priceCells}
      ${scoreCell}
      ${btCell}
      ${holdingCells}
      <td class="col-sep subtext">${refreshed}</td>
      <td style="text-align:right;white-space:nowrap">${actionCell}</td>
    </tr>`;
  }).join("");

  return `<table class="watchlist-table">${head}<tbody>${rows}</tbody></table>`;
}
