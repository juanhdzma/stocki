import { srcLink, INSIDER_SOURCE, fmtPctSigned, fmtPctLevel, shortQLabel, escapeHtml } from "./format.js";
import { scoreColor, scoreColorVar, scoreLabel, actionBadge, pctScoreColor } from "./colors.js";
import { comboFundamentalsSvg, renderPriceOverview, renderPriceCharts, analystBar } from "./charts.js";
import { state } from "./state.js";

function statRow(label, valueText, colorPct) {
  const pct = colorPct != null ? Math.max(0, Math.min(100, colorPct)) : 0;
  const barColor = colorPct != null ? scoreColorVar(colorPct) : "var(--null)";
  return `<div class="stat-row">
    <span class="stat-lbl">${label}</span>
    <div class="stat-bar-wrap"><div class="stat-bar-fill" style="width:${pct.toFixed(0)}%;background:${barColor}"></div></div>
    <span class="stat-val ${scoreColor(colorPct)}">${valueText}</span>
  </div>`;
}

function cardBadge(label) {
  return `<span class="card-badge">${label}</span>`;
}

// colorPct: reuse the underlying 0-100 sub-score so the bar/number still
// reflects "is this good", even though the displayed text is the real-world stat.
function subPct(sub, max, key) {
  return (sub[key] != null && max?.[key]) ? (sub[key] / max[key]) * 100 : null;
}

// Fallback for sub-scores with no clean single real-world stat (e.g. trend deltas):
// show the raw points instead of fabricating a number the scorer didn't actually compute.
function pointsLabel(sub, max, key) {
  return (sub[key] != null && max?.[key] != null) ? `${sub[key].toFixed(1)}/${max[key]}` : "—";
}

function fmDetails(cat, snap, quarterlies) {
  const sub = cat?.sub_scores, max = cat?.max_pts;
  if (!sub || !snap) return "—";
  const q0 = (quarterlies || [])[0];
  const rdPct = (q0 && q0.rd_expense != null && q0.revenue) ? q0.rd_expense / q0.revenue : null;
  return [
    statRow("Revenue Growth",  fmtPctSigned(snap.revenue_growth),  subPct(sub, max, "revenue_trend")),
    statRow("Earnings Growth", fmtPctSigned(snap.earnings_growth), subPct(sub, max, "ni_trajectory")),
    statRow("Gross Margin",    fmtPctLevel(snap.gross_margin),     subPct(sub, max, "gm_expansion")),
    statRow("R&D Intensity",   rdPct != null ? fmtPctLevel(rdPct) : pointsLabel(sub, max, "rd_intensity"), subPct(sub, max, "rd_intensity")),
    statRow("FCF Trend",       pointsLabel(sub, max, "fcf_trajectory"), subPct(sub, max, "fcf_trajectory")),
    sub.rule_of_40 >= 5 ? cardBadge("Rule of 40 ✓") : "",
  ].join("") || "—";
}

function vqDetails(cat, snap) {
  const sub = cat?.sub_scores, max = cat?.max_pts;
  if (!sub || !snap) return "—";
  return [
    statRow("ROE",           fmtPctLevel(snap.roe),                                        subPct(sub, max, "profitability")),
    statRow("FCF Yield",     fmtPctLevel(snap.fcf_yield),                                  subPct(sub, max, "profitability")),
    statRow("Debt/Equity",   snap.debt_to_equity != null ? snap.debt_to_equity.toFixed(2) : "—", subPct(sub, max, "balance_sheet")),
    statRow("Dilution Rate", fmtPctSigned(snap.dilution_rate), subPct(sub, max, "capital_discipline")),
    sub.buyback_bonus >= 1 ? cardBadge("Buybacks ↑") : "",
  ].join("") || "—";
}

function icDetails(sub) {
  if (!sub) return "—";
  const b = sub.valid_buys  ?? null;
  const s = sub.valid_sells ?? null;
  if (b == null && s == null) return "—";
  return `${b ?? 0}B / ${s ?? 0}S`;
}

function plDetails(cat, snap) {
  const sub = cat?.sub_scores, max = cat?.max_pts;
  if (!sub || !snap) return "—";
  const upside = (snap.price && snap.target_mean) ? (snap.target_mean / snap.price - 1) : null;
  return [
    statRow("Analyst Upside", fmtPctSigned(upside),                 subPct(sub, max, "analyst_upside")),
    statRow("Trailing P/E",   snap.trailing_pe != null ? snap.trailing_pe.toFixed(1) : "—", subPct(sub, max, "valuation")),
  ].join("") || "—";
}

function renderScoreCards(tickers, raw) {
  const blocks = tickers.map(ticker => {
    const scores = raw[ticker]?.scores;
    if (!scores) return "";

    const snap = raw[ticker]?.snapshot || {};
    const quarterlies = raw[ticker]?.quarterlies || [];
    const fm   = scores.fundamental_momentum || {};
    const vq   = scores.value_quality        || {};
    const ic   = scores.insider_conviction   || {};
    const pl   = scores.price_long           || {};
    const comp = scores.composite_long       || {};

    const cards = [
      { title: "Growth",   score: fm.score, detail: fmDetails(fm, snap, quarterlies) },
      { title: "Quality",  score: vq.score, detail: vqDetails(vq, snap) },
      { title: "Insiders", score: ic.score, detail: icDetails(ic.sub_scores) },
      { title: "Valuation", score: pl.score, detail: plDetails(pl, snap) },
    ].map(c => `
      <div class="score-card">
        <div class="score-card-title">${c.title}</div>
        <div class="score-card-value ${scoreColor(c.score)}">${scoreLabel(c.score)}</div>
        <div class="score-card-detail">${c.detail}</div>
      </div>`).join("");

    const compVal = comp.score != null
      ? `<span class="score-composite-val">${comp.score.toFixed(1)}</span>`
      : "";

    return `
      <div class="score-ticker-block">
        <div class="score-ticker-header">
          <span class="score-ticker-name">${ticker}</span>
          ${actionBadge(scores)}
          ${compVal}
        </div>
        <div class="score-cards">${cards}</div>
      </div>`;
  }).join("");

  return `
    <section class="cat-section">
      <h2>Signal Overview</h2>
      ${blocks}
    </section>`;
}

async function loadPriceTrend(ticker) {
  const el = document.getElementById(`price-trend-${ticker}`);
  if (!el) return;

  if (state.priceHistoryCache[ticker]) {
    el.innerHTML = renderPriceCharts(state.priceHistoryCache[ticker], ticker);
    return;
  }

  try {
    const res = await fetch(`/api/price-history/${encodeURIComponent(ticker)}?period=1y`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const points = data.points || [];
    if (points.length < 2) {
      el.innerHTML = `<div class="trend-chart"><div class="subtext" style="font-size:11px">No price history</div></div>`;
      return;
    }
    state.priceHistoryCache[ticker] = points;
    el.innerHTML = renderPriceCharts(points, ticker);
  } catch (e) {
    el.innerHTML = `<div class="trend-chart"><div class="subtext" style="font-size:11px">Failed to load price history</div></div>`;
    console.error(e);
  }
}

function renderTrajectorySection(tickers, raw) {
  const blocks = tickers.map(ticker => {
    const d = raw[ticker];
    if (!d) return "";

    const annuals     = [...(d.annuals || [])].reverse().map(a => ({ ...a, label: a.period }));
    const quarterlies = [...(d.quarterlies || [])].reverse().map(a => ({ ...a, label: shortQLabel(a.period) }));

    const annualChart    = comboFundamentalsSvg(annuals, `${ticker}-fundAnnual`);
    const quarterlyChart = comboFundamentalsSvg(quarterlies, `${ticker}-fundQuarterly`);

    return `
      <div class="score-ticker-block">
        ${renderPriceOverview(d.snapshot, d.returns)}
        <div class="trend-grid" id="price-trend-${ticker}">
          <div class="trend-chart"><div class="trend-chart-title">Price — 1 Year</div><div class="subtext" style="font-size:11px">Loading…</div></div>
          <div class="trend-chart"><div class="trend-chart-title">Price — 1 Month</div><div class="subtext" style="font-size:11px">Loading…</div></div>
        </div>
        <div class="trend-subhead">Fundamentals <span class="mini-legend">
          <span class="mini-legend-item"><span class="mini-legend-dot" style="background:var(--blue)"></span>Revenue</span>
          <span class="mini-legend-item"><span class="mini-legend-dot" style="background:var(--green)"></span>Net Income</span>
          <span class="mini-legend-item"><span class="mini-legend-line"></span>Gross Margin</span>
        </span></div>
        <div class="trend-grid">
          <div class="trend-chart"><div class="trend-chart-title">Annual</div>${annualChart}</div>
          <div class="trend-chart"><div class="trend-chart-title">Quarterly</div>${quarterlyChart}</div>
        </div>
      </div>`;
  }).join("");

  if (!blocks) return "";

  return `
    <section class="cat-section">
      <h2>Trajectory</h2>
      ${blocks}
    </section>`;
}

function renderAnalystSummary(tickers, raw) {
  const t0   = tickers[0];
  const snap = raw[t0]?.snapshot;
  if (!snap) return "";

  const price  = snap.price;
  const target = snap.target_mean;
  const upside = (price && target) ? (target / price - 1) : null;

  const hasAnalyst = snap.analyst_count != null || upside != null;
  const hasShort   = snap.short_ratio != null || snap.short_percent_of_float != null;
  if (!hasAnalyst && !hasShort) return "";

  const bar = analystBar(snap.rec_strong_buy, snap.rec_buy, snap.rec_hold, snap.rec_sell, snap.rec_strong_sell, 320);

  return `
    <section class="cat-section">
      <h2>Analyst &amp; Short Interest</h2>
      <div class="insider-summary">
        <div class="insider-stat"><span class="insider-stat-label">Analyst Upside</span><span class="insider-stat-val ${upside != null ? pctScoreColor(upside, 0.30) : "s-null"}">${fmtPctSigned(upside)}</span></div>
        <div class="insider-stat"><span class="insider-stat-label">Target Mean</span><span class="insider-stat-val">${target != null ? "$" + target.toFixed(2) : "—"}</span></div>
        <div class="insider-stat"><span class="insider-stat-label">Short % Float</span><span class="insider-stat-val">${fmtPctLevel(snap.short_percent_of_float)}</span></div>
        <div class="insider-stat"><span class="insider-stat-label">Days to Cover</span><span class="insider-stat-val">${snap.short_ratio != null ? snap.short_ratio.toFixed(1) : "—"}</span></div>
      </div>
      ${bar ? `<div style="margin-top:12px">${bar}</div>` : ""}
    </section>`;
}

function renderInsiderSummary(tickers, raw) {
  const t0   = tickers[0];
  const txs  = (raw[t0]?.insider_transactions || [])
    .slice()
    .sort((a, b) => (b.trade_date || "").localeCompare(a.trade_date || ""));
  if (!txs.length) return "";

  const today = new Date();
  const ago90 = new Date(today); ago90.setDate(today.getDate() - 90);

  const recent = txs.filter(tx => tx.trade_date && new Date(tx.trade_date) >= ago90);
  const buys   = recent.filter(tx => (tx.trade_type || "").startsWith("P")).length;
  const sells  = recent.filter(tx => (tx.trade_type || "").startsWith("S")).length;

  const ic    = raw[t0]?.scores?.insider_conviction || {};
  const icSc  = ic.score;
  const scoreHtml = icSc != null
    ? `<span class="${scoreColor(icSc)}">${icSc.toFixed(0)}</span>`
    : "—";

  const rows = txs.slice(0, 8).map(tx => {
    const type    = (tx.trade_type || "").replace(" - ", " ");
    const typeCls = type.startsWith("P") ? "s-green" : "s-red";
    const td      = tx.trade_date ? new Date(tx.trade_date) : null;
    const in3m    = td && td >= ago90;
    return `<tr>
      <td>${tx.trade_date || "—"}</td>
      <td>${escapeHtml(tx.insider_name || "—")}</td>
      <td class="subtext">${escapeHtml(tx.title || "—")}</td>
      <td class="${typeCls}">${type}</td>
      <td>${tx.Value || "—"}</td>
      <td>${tx["ΔOwn"] || "—"}</td>
      <td>${in3m ? "<span class=\"badge badge-green\">3M</span>" : ""}</td>
    </tr>`;
  }).join("");

  return `
    <section class="cat-section">
      <h2>Insider Activity${srcLink(INSIDER_SOURCE(t0))}</h2>
      <div class="insider-summary">
        <div class="insider-stat"><span class="insider-stat-label">Score 3M</span><span class="insider-stat-val">${scoreHtml}</span></div>
        <div class="insider-stat"><span class="insider-stat-label">Buys 3M</span><span class="insider-stat-val s-green">${buys}</span></div>
        <div class="insider-stat"><span class="insider-stat-label">Sells 3M</span><span class="insider-stat-val ${sells > 0 ? "s-red" : "s-null"}">${sells}</span></div>
        <div class="insider-stat"><span class="insider-stat-label">Total 1Y</span><span class="insider-stat-val">${txs.length}</span></div>
      </div>
      <table>
        <thead><tr>
          <th style="text-align:left">Date</th>
          <th style="text-align:left">Insider</th>
          <th style="text-align:left">Title</th>
          <th style="text-align:left">Type</th>
          <th>Value</th>
          <th>ΔOwn</th>
          <th>Window</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </section>`;
}

function render(tickers, raw) {
  const dashboard = document.getElementById("dashboard");
  dashboard.innerHTML = [
    renderScoreCards(tickers, raw),
    renderTrajectorySection(tickers, raw),
    renderAnalystSummary(tickers, raw),
    renderInsiderSummary(tickers, raw),
  ].join("");
}

export {
  statRow, cardBadge, subPct, pointsLabel,
  fmDetails, vqDetails, icDetails, plDetails,
  renderScoreCards, renderTrajectorySection, renderAnalystSummary, renderInsiderSummary,
  render, loadPriceTrend,
};
