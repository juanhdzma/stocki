"use strict";

// ── State ─────────────────────────────────────────────────────────────────────
let watchlist = [];
let watchlistData = {};
let sortCol = "composite";
let sortDir = -1;

// ── Source URLs ───────────────────────────────────────────────────────────────
const YF = t => `https://finance.yahoo.com/quote/${t}`;
const SNAPSHOT_SOURCE   = t => YF(t) + "/key-statistics/";
const RETURNS_SOURCE    = t => YF(t) + "/performance/";
const FINANCIALS_SOURCE = t => YF(t) + "/financials/";
const CASHFLOW_SOURCE   = t => YF(t) + "/cash-flow/";
const BALANCE_SOURCE    = t => YF(t) + "/balance-sheet/";
const ANALYSIS_SOURCE   = t => YF(t) + "/analysis/";
const OPTIONS_SOURCE    = t => YF(t) + "/options/";
const INSIDER_SOURCE    = t => `https://openinsider.com/screener?s=${t}`;

// ── Format helpers ────────────────────────────────────────────────────────────
function fmtRaw(v, type) {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  if (isNaN(n)) return String(v);
  switch (type) {
    case "pct": return (n * 100).toFixed(1) + "%";
    case "large": {
      const abs = Math.abs(n), sign = n < 0 ? "-" : "";
      if (abs >= 1e9) return sign + (abs / 1e9).toFixed(2) + "B";
      if (abs >= 1e6) return sign + (abs / 1e6).toFixed(1) + "M";
      if (abs >= 1e3) return sign + (abs / 1e3).toFixed(0) + "K";
      return n.toFixed(0);
    }
    case "price":   return "$" + n.toFixed(2);
    case "decimal": return n.toFixed(2);
    case "text":    return isNaN(n) ? String(v).replace(/_/g, " ") : n.toFixed(2);
    default:        return n.toFixed(2);
  }
}

function srcLink(url) {
  if (!url) return "";
  return ` <a href="${url}" target="_blank" rel="noopener" class="src-link">↗</a>`;
}

function fmtTimestamp(iso) {
  if (!iso) return "—";
  const d = new Date(iso.replace(" ", "T") + "Z");
  return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

function timeAgo(isoStr) {
  if (!isoStr) return "—";
  const normalized = isoStr.replace(" ", "T");
  const withZ = /[Zz+]/.test(normalized) ? normalized : normalized + "Z";
  const d = new Date(withZ);
  if (isNaN(d.getTime())) return "—";
  const sec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return "now";
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

function shortPeriod(p) {
  if (!p) return "";
  const qm = p.match(/Q\d/);
  if (qm) return qm[0];
  return String(p).slice(-4);
}

// ── SVG mini charts ───────────────────────────────────────────────────────────
function fmtShort(v) {
  if (v === null || v === undefined) return "";
  const n = Number(v), abs = Math.abs(n), sign = n < 0 ? "-" : "";
  if (abs >= 1e9) return sign + (abs / 1e9).toFixed(1) + "B";
  if (abs >= 1e6) return sign + (abs / 1e6).toFixed(0) + "M";
  if (abs >= 1e3) return sign + (abs / 1e3).toFixed(0) + "K";
  return n.toFixed(0);
}

function miniGroupedChart(revVals, niVals, labels, width, height) {
  const n = labels.length;
  if (!n) return "";
  const allVals = [...revVals, ...niVals].map(v => (v === null || v === undefined) ? 0 : Number(v));
  const maxAbs  = Math.max(...allVals.map(v => Math.abs(v)), 1);

  const padH = 2, padTop = 14, padBot = 14;
  const innerH  = height - padTop - padBot;
  const baseline = padTop + innerH;
  const groupGap = 4, barGap = 1;
  const groupW   = Math.max((width - 2 * padH - groupGap * (n - 1)) / n, 4);
  const bw       = Math.max((groupW - barGap) / 2, 1);

  const elements = labels.map((lbl, i) => {
    const rv   = revVals[i] != null ? Number(revVals[i]) : null;
    const niv  = niVals[i]  != null ? Number(niVals[i])  : null;
    const gx   = padH + i * (groupW + groupGap);
    const lblX = (gx + groupW / 2).toFixed(1);

    const barSvg = (val, xOff, color) => {
      if (val === null) return "";
      const bh = Math.max((Math.abs(val) / maxAbs) * innerH, 1);
      const x  = gx + xOff;
      const y  = val >= 0 ? baseline - bh : baseline;
      const c  = val >= 0 ? color : "#f85149";
      const valY = val >= 0 ? (y - 2).toFixed(1) : (y + bh + 8).toFixed(1);
      return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" fill="${c}" rx="1"/>
<text x="${(x + bw / 2).toFixed(1)}" y="${valY}" text-anchor="middle" fill="${c}" font-size="6" font-family="monospace">${fmtShort(val)}</text>`;
    };

    return `${barSvg(rv,  0,        "#58a6ff")}
${barSvg(niv, bw + barGap, "#3fb950")}
<text x="${lblX}" y="${height - 1}" text-anchor="middle" fill="#8b949e" font-size="7" font-family="monospace">${shortPeriod(lbl)}</text>`;
  }).join("\n");

  return `<svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">
<line x1="${padH}" y1="${baseline}" x2="${width - padH}" y2="${baseline}" stroke="#30363d" stroke-width="0.5"/>
${elements}</svg>`;
}

function priceTargetBar(price, low, mean, high, width, height) {
  if (!price || !low || !high) return "";
  const allV = [low, mean, high, price].filter(Boolean);
  const minV = Math.min(...allV) * 0.92;
  const maxV = Math.max(...allV) * 1.08;
  const range = maxV - minV;
  if (range <= 0) return "";

  const pad = 24;
  const innerW = width - 2 * pad;
  const sc = v => pad + ((v - minV) / range) * innerW;
  const midY = 18;
  const fmt = v => `$${Number(v).toFixed(0)}`;

  const lX = sc(low).toFixed(1), mX = sc(mean).toFixed(1),
        hX = sc(high).toFixed(1), pX = sc(price).toFixed(1);

  return `<svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">
<rect x="${lX}" y="${(midY - 3)}" width="${(sc(high) - sc(low)).toFixed(1)}" height="6" fill="#21262d" rx="3"/>
<line x1="${lX}" y1="${midY - 6}" x2="${lX}" y2="${midY + 6}" stroke="#484f58" stroke-width="1.5"/>
<line x1="${hX}" y1="${midY - 6}" x2="${hX}" y2="${midY + 6}" stroke="#484f58" stroke-width="1.5"/>
<line x1="${mX}" y1="${midY - 8}" x2="${mX}" y2="${midY + 8}" stroke="#d29922" stroke-width="2"/>
<circle cx="${pX}" cy="${midY}" r="5" fill="#58a6ff"/>
<text x="${pX}" y="${midY - 11}" text-anchor="middle" fill="#58a6ff" font-size="8" font-family="monospace" font-weight="600">${fmt(price)}</text>
<text x="${lX}" y="${height - 1}" text-anchor="middle" fill="#8b949e" font-size="7" font-family="monospace">${fmt(low)}</text>
<text x="${mX}" y="${height - 1}" text-anchor="middle" fill="#d29922" font-size="7" font-family="monospace">${fmt(mean)}</text>
<text x="${hX}" y="${height - 1}" text-anchor="middle" fill="#8b949e" font-size="7" font-family="monospace">${fmt(high)}</text>
</svg>`;
}

// ── Hover Tooltip ─────────────────────────────────────────────────────────────
function buildTooltip(ticker, d) {
  if (!d) return `<div class="tt-head"><span class="tt-ticker">${ticker}</span><span class="subtext" style="margin-left:8px">No data — click to load</span></div>`;

  const snap   = d.snapshot || {};
  const scores = d.scores   || {};
  const annuals  = (d.annuals    || []).slice().reverse();
  const quarters = (d.quarterlies || []).slice().reverse();
  const txs = d.insider_transactions || [];

  const price  = snap.price;
  const pct52h = snap.pct_from_52w_high;
  const pct52hStr = pct52h != null ? `${(pct52h * 100).toFixed(1)}% from 52W high` : "";
  const pct52hCls = pct52h != null
    ? (pct52h > -0.05 ? "s-yellow" : pct52h > -0.2 ? "s-null" : "s-green")
    : "";

  const comp      = scores.composite || {};
  const actionStr = comp.action || "NA";
  const actionCls = "action-" + actionStr;

  const CW = 440, CH = 84;
  const annualChart  = miniGroupedChart(
    annuals.map(f => f.revenue),  annuals.map(f => f.net_income),  annuals.map(f => f.period),  CW, CH);
  const quarterChart = miniGroupedChart(
    quarters.map(f => f.revenue), quarters.map(f => f.net_income), quarters.map(f => f.period), CW, CH);

  const ptBar = priceTargetBar(price, snap.target_low, snap.target_mean, snap.target_high, 440, 52);

  const today = new Date();
  const ago90 = new Date(today); ago90.setDate(today.getDate() - 90);
  const recent  = txs.filter(tx => tx.trade_date && new Date(tx.trade_date) >= ago90);
  const buys3m  = recent.filter(tx => (tx.trade_type || "").startsWith("P")).length;
  const sells3m = recent.filter(tx => (tx.trade_type || "").startsWith("S")).length;
  const icScore = scores.insider_conviction?.sub_scores?.score_3m ?? null;

  const p   = v => v != null ? `$${Number(v).toFixed(2)}` : "—";
  const pct = v => v != null ? `${(Number(v) * 100).toFixed(1)}%` : "—";
  const dec = v => v != null ? Number(v).toFixed(1) : "—";

  return `
<div class="tt-head">
  <span class="tt-ticker">${ticker}</span>
  <span class="tt-price">${price ? p(price) : "—"}</span>
  ${pct52hStr ? `<span class="tt-52h ${pct52hCls}">${pct52hStr}</span>` : ""}
  <span style="margin-left:auto;display:flex;align-items:center;gap:6px">
    <span class="action-badge ${actionCls}">${actionStr}</span>
    ${comp.score != null ? `<span class="tt-comp-score">${comp.score.toFixed(1)}</span>` : ""}
  </span>
</div>
<div class="tt-chart-legend">
  <span class="tt-legend-rev">■ Revenue</span>
  <span class="tt-legend-ni">■ Net Income</span>
</div>
<div>
  <div class="tt-chart-lbl">Annual</div>
  <div class="tt-chart">${annualChart || "<span class='subtext'>—</span>"}</div>
</div>
<div style="margin-top:8px">
  <div class="tt-chart-lbl">Quarterly</div>
  <div class="tt-chart">${quarterChart || "<span class='subtext'>—</span>"}</div>
</div>
${ptBar ? `<div class="tt-section-lbl">Analyst Targets</div><div class="tt-chart">${ptBar}</div>` : ""}
<div class="tt-metrics">
  <div class="tt-metric"><span class="tt-ml">Fwd P/E</span><span class="tt-mv">${dec(snap.forward_pe)}</span></div>
  <div class="tt-metric"><span class="tt-ml">Gross M.</span><span class="tt-mv">${pct(snap.gross_margin)}</span></div>
  <div class="tt-metric"><span class="tt-ml">Op. M.</span><span class="tt-mv">${pct(snap.operating_margin)}</span></div>
  <div class="tt-metric"><span class="tt-ml">Insider %</span><span class="tt-mv">${pct(snap.held_pct_insiders)}</span></div>
</div>
<div class="tt-footer">
  <span class="tt-ml">Insiders 3M</span>
  <span class="s-green">${buys3m}B</span>
  <span class="subtext">/</span>
  <span class="${sells3m > 0 ? "s-red" : "s-null"}">${sells3m}S</span>
  ${icScore != null ? `<span class="tt-iscore ${icScore >= 0 ? "s-green" : "s-red"}">&nbsp;${icScore > 0 ? "+" : ""}${icScore.toFixed(0)}</span>` : ""}
  <span class="tt-ml" style="margin-left:12px">Short Float</span>
  <span>${pct(snap.short_percent_of_float)}</span>
</div>`;
}

function showTooltip(event, ticker) {
  const el = document.getElementById("tooltip");
  el.style.width = "492px";
  el.innerHTML = buildTooltip(ticker, watchlistData[ticker]);
  positionTooltip(event, el);
  el.style.display = "block";
}

function hideTooltip() {
  const el = document.getElementById("tooltip");
  if (el) el.style.display = "none";
}

function positionTooltip(event, el) {
  const TW = parseInt(el.style.width) || 492;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  let left = event.clientX + 18;
  let top  = event.clientY - 30;
  if (left + TW > vw - 8) left = event.clientX - TW - 18;
  if (top < 60) top = 60;
  if (top + 640 > vh - 8) top = Math.max(60, vh - 648);
  el.style.left = left + "px";
  el.style.top  = top + "px";
}

// ── Score detail tooltip ──────────────────────────────────────────────────────
function subScoreBar(label, val, max) {
  if (val === null || val === undefined) {
    return `<div class="tt-sub-row">
      <span class="tt-sub-lbl">${label}</span>
      <div class="tt-sub-bar-wrap"></div>
      <span class="tt-sub-val s-null">—</span>
    </div>`;
  }
  const pct = Math.min(100, (val / max) * 100);
  const barColor = pct >= 70 ? "var(--green)" : pct >= 40 ? "var(--yellow)" : "var(--red)";
  const numCls   = pct >= 70 ? "s-green"      : pct >= 40 ? "s-yellow"      : "s-red";
  return `<div class="tt-sub-row">
    <span class="tt-sub-lbl">${label}</span>
    <div class="tt-sub-bar-wrap"><div class="tt-sub-bar" style="width:${pct.toFixed(0)}%;background:${barColor}"></div></div>
    <span class="tt-sub-val ${numCls}">${val.toFixed(1)}<span class="subtext">/${max}</span></span>
  </div>`;
}

function signedBar(label, val, max) {
  if (val === null || val === undefined) {
    return `<div class="tt-sub-row">
      <span class="tt-sub-lbl">${label}</span>
      <div class="tt-sub-bar-wrap"></div>
      <span class="tt-sub-val s-null">—</span>
    </div>`;
  }
  const pct      = Math.min(100, (Math.abs(val) / max) * 100);
  const barColor = val >= 0 ? "var(--green)" : "var(--red)";
  const numCls   = val > 20 ? "s-green" : val < -20 ? "s-red" : "s-yellow";
  const sign     = val > 0 ? "+" : "";
  return `<div class="tt-sub-row">
    <span class="tt-sub-lbl">${label}</span>
    <div class="tt-sub-bar-wrap"><div class="tt-sub-bar" style="width:${pct.toFixed(0)}%;background:${barColor}"></div></div>
    <span class="tt-sub-val ${numCls}">${sign}${val.toFixed(0)}</span>
  </div>`;
}

function buildScoreTooltip(ticker, col) {
  const d = watchlistData[ticker];
  if (!d) return `<div class="tt-head"><span class="tt-ticker">${ticker}</span><span class="subtext" style="margin-left:8px">No data</span></div>`;

  const scores = d.scores || {};
  let category = {}, title = "", rows = "";

  switch (col) {
    case "growth": {
      category = scores.fundamental_momentum || {};
      title = "Growth";
      const sub = category.sub_scores || {};
      rows = [
        subScoreBar("Revenue Trend",  sub.revenue_trend,  25),
        subScoreBar("NI Trajectory",  sub.ni_trajectory,  20),
        subScoreBar("GM Expansion",   sub.gm_expansion,   15),
        subScoreBar("FCF Trajectory", sub.fcf_trajectory, 15),
        subScoreBar("R&D Intensity",  sub.rd_intensity,   10),
        subScoreBar("Buybacks",       sub.buyback_signal, 10),
        subScoreBar("Rule of 40",     sub.rule_of_40,      5),
      ].join("");
      break;
    }
    case "quality": {
      category = scores.value_quality || {};
      title = "Quality";
      const sub = category.sub_scores || {};
      rows = [
        subScoreBar("Profitability",      sub.profitability,      20),
        subScoreBar("Price Discount",     sub.price_discount,     20),
        subScoreBar("Valuation",          sub.valuation,          20),
        subScoreBar("Balance Sheet",      sub.balance_sheet,      20),
        subScoreBar("Capital Discipline", sub.capital_discipline, 10),
        subScoreBar("Analyst Conviction", sub.analyst_conviction, 10),
      ].join("");
      break;
    }
    case "insiders": {
      category = scores.insider_conviction || {};
      title = "Insiders";
      const sub = category.sub_scores || {};
      const b3m = sub.valid_buys_3m;
      const s3m = sub.valid_sells_3m;
      rows = [
        signedBar("Score 3M", sub.score_3m, 100),
        signedBar("Score 1Y", sub.score_1y, 100),
        `<div class="tt-sub-row" style="margin-top:2px">
          <span class="tt-sub-lbl">Buys / Sells 3M</span>
          <span class="tt-sub-val" style="margin-left:auto">
            <span class="s-green">${b3m ?? "—"}B</span>
            <span class="subtext"> / </span>
            <span class="${(s3m || 0) > 0 ? "s-red" : "s-null"}">${s3m ?? "—"}S</span>
          </span>
        </div>`,
      ].join("");
      break;
    }
    case "entry": {
      category = scores.price_opportunity || {};
      title = "Entry";
      const sub = category.sub_scores || {};
      rows = [
        subScoreBar("Dip Signal",       sub.dip_signal,        30),
        subScoreBar("SPY Divergence",   sub.spy_divergence,    20),
        subScoreBar("Short Setup",      sub.short_setup,       20),
        subScoreBar("Options Sentiment",sub.options_sentiment, 15),
        subScoreBar("Analyst Upside",   sub.analyst_upside,    15),
      ].join("");
      break;
    }
    case "composite": {
      category = scores.composite || {};
      title = "Score";
      const weights = scores.composite?.weights || {fundamental_momentum: 30, value_quality: 30, insider_conviction: 25, price_opportunity: 15};
      const cats = [
        { key: "fundamental_momentum", label: "Growth"   },
        { key: "value_quality",        label: "Quality"  },
        { key: "insider_conviction",   label: "Insiders" },
        { key: "price_opportunity",    label: "Entry"    },
      ];
      rows = cats.map(c => {
        const s  = scores[c.key]?.score;
        const wt = weights[c.key];
        const pct = s != null ? Math.min(100, s) : 0;
        const barColor = s != null ? (s >= 70 ? "var(--green)" : s >= 50 ? "var(--yellow)" : "var(--red)") : "";
        return `<div class="tt-sub-row">
          <span class="tt-sub-lbl">${c.label} <span class="subtext">${wt}%</span></span>
          <div class="tt-sub-bar-wrap">${s != null ? `<div class="tt-sub-bar" style="width:${pct.toFixed(0)}%;background:${barColor}"></div>` : ""}</div>
          <span class="tt-sub-val ${scoreColor(s)}">${s != null ? s.toFixed(1) : "—"}</span>
        </div>`;
      }).join("");
      break;
    }
    default:
      return "";
  }

  const score = category.score;
  return `
<div class="tt-head">
  <span class="tt-ticker">${ticker}</span>
  <span class="subtext" style="margin-left:4px;font-size:11px">${title}</span>
  ${score != null ? `<span class="tt-comp-score ${scoreColor(score)}" style="margin-left:auto;font-size:13px;font-weight:700">${score.toFixed(1)}</span>` : ""}
</div>
<div class="tt-subs">${rows}</div>`;
}

function showScoreTooltip(event, ticker, col) {
  const el = document.getElementById("tooltip");
  el.style.width = "360px";
  el.innerHTML = buildScoreTooltip(ticker, col);
  positionTooltip(event, el);
  el.style.display = "block";
}

// ── Raw data table (detail view) ──────────────────────────────────────────────
const SNAPSHOT_SECTIONS = [
  {
    label: "Price & Market",
    src: SNAPSHOT_SOURCE,
    fields: [
      { key: "price",              label: "Price",               fmt: "price"   },
      { key: "market_cap",         label: "Market Cap",          fmt: "large"   },
      { key: "enterprise_value",   label: "Enterprise Value",    fmt: "large"   },
      { key: "week52_low",         label: "52W Low",             fmt: "price"   },
      { key: "week52_high",        label: "52W High",            fmt: "price"   },
      { key: "pct_from_52w_high",  label: "% from 52W High",     fmt: "pct"     },
      { key: "pct_from_1w_high",   label: "% from 1W High",      fmt: "pct"     },
      { key: "beta",               label: "Beta",                fmt: "decimal" },
      { key: "average_volume",     label: "Avg Volume",          fmt: "large"   },
      { key: "shares_outstanding", label: "Shares Outstanding",  fmt: "large"   },
      { key: "sector",             label: "Sector",              fmt: "text"    },
      { key: "industry",           label: "Industry",            fmt: "text"    },
    ],
  },
  {
    label: "Valuation Multiples",
    src: SNAPSHOT_SOURCE,
    fields: [
      { key: "trailing_pe",    label: "Trailing P/E",   fmt: "decimal" },
      { key: "forward_pe",     label: "Forward P/E",    fmt: "decimal" },
      { key: "peg_ratio",      label: "PEG Ratio",      fmt: "decimal" },
      { key: "eps_ttm",        label: "EPS (TTM)",      fmt: "price"   },
      { key: "price_to_sales", label: "Price / Sales",  fmt: "decimal" },
      { key: "ev_to_revenue",  label: "EV / Revenue",   fmt: "decimal" },
    ],
  },
  {
    label: "Margins & Returns",
    src: FINANCIALS_SOURCE,
    fields: [
      { key: "gross_margin",     label: "Gross Margin",     fmt: "pct" },
      { key: "operating_margin", label: "Operating Margin", fmt: "pct" },
      { key: "net_margin",       label: "Net Margin",       fmt: "pct" },
      { key: "roe",              label: "ROE",              fmt: "pct" },
      { key: "roa",              label: "ROA",              fmt: "pct" },
      { key: "fcf_yield",        label: "FCF Yield",        fmt: "pct" },
    ],
  },
  {
    label: "Growth (YoY)",
    src: FINANCIALS_SOURCE,
    fields: [
      { key: "revenue_growth",  label: "Revenue Growth",  fmt: "pct" },
      { key: "earnings_growth", label: "Earnings Growth", fmt: "pct" },
      { key: "dilution_rate",   label: "Dilution Rate",   fmt: "pct" },
    ],
  },
  {
    label: "Liquidity & Leverage",
    src: BALANCE_SOURCE,
    fields: [
      { key: "current_ratio",  label: "Current Ratio", fmt: "decimal" },
      { key: "quick_ratio",    label: "Quick Ratio",   fmt: "decimal" },
      { key: "debt_to_equity", label: "Debt / Equity", fmt: "decimal" },
    ],
  },
  {
    label: "Ownership",
    src: SNAPSHOT_SOURCE,
    fields: [
      { key: "held_pct_insiders",      label: "Insider %",       fmt: "pct"     },
      { key: "held_pct_institutions",  label: "Institutional %", fmt: "pct"     },
      { key: "short_percent_of_float", label: "Short % Float",   fmt: "pct"     },
      { key: "short_ratio",            label: "Short Ratio",     fmt: "decimal" },
    ],
  },
  {
    label: "Analyst",
    src: ANALYSIS_SOURCE,
    fields: [
      { key: "target_low",          label: "Target Low",        fmt: "price"   },
      { key: "target_mean",         label: "Target Mean",       fmt: "price"   },
      { key: "target_high",         label: "Target High",       fmt: "price"   },
      { key: "analyst_count",       label: "# Analysts",        fmt: "decimal" },
      { key: "recommendation_mean", label: "Rec. Mean (1=Buy)", fmt: "decimal" },
      { key: "recommendation_key",  label: "Consensus",         fmt: "text"    },
      { key: "rec_strong_buy",      label: "Strong Buy",        fmt: "decimal" },
      { key: "rec_buy",             label: "Buy",               fmt: "decimal" },
      { key: "rec_hold",            label: "Hold",              fmt: "decimal" },
      { key: "rec_sell",            label: "Sell",              fmt: "decimal" },
      { key: "rec_strong_sell",     label: "Strong Sell",       fmt: "decimal" },
    ],
  },
];

const RETURNS_FIELDS = [
  { key: "ticker_return_1m",  label: "Return 1M",      fmt: "pct" },
  { key: "spy_return_1m",     label: "SPY Return 1M",  fmt: "pct" },
  { key: "ticker_return_3m",  label: "Return 3M",      fmt: "pct" },
  { key: "spy_return_3m",     label: "SPY Return 3M",  fmt: "pct" },
  { key: "ticker_return_6m",  label: "Return 6M",      fmt: "pct" },
  { key: "spy_return_6m",     label: "SPY Return 6M",  fmt: "pct" },
  { key: "ticker_return_12m", label: "Return 12M",     fmt: "pct" },
  { key: "spy_return_12m",    label: "SPY Return 12M", fmt: "pct" },
];

const FUND_FIELDS = [
  { key: "revenue",             label: "Revenue",          fmt: "large" },
  { key: "gross_margin",        label: "Gross Margin",     fmt: "pct"   },
  { key: "ebit",                label: "EBIT",             fmt: "large" },
  { key: "net_income",          label: "Net Income",       fmt: "large" },
  { key: "rd_expense",          label: "R&D Expense",      fmt: "large" },
  { key: "total_assets",        label: "Total Assets",     fmt: "large" },
  { key: "total_equity",        label: "Total Equity",     fmt: "large" },
  { key: "total_debt",          label: "Total Debt",       fmt: "large" },
  { key: "cash",                label: "Cash",             fmt: "large" },
  { key: "operating_cash_flow", label: "Operating CF",     fmt: "large" },
  { key: "fcf",                 label: "FCF",              fmt: "large" },
  { key: "buybacks",            label: "Buybacks",         fmt: "large" },
  { key: "interest_expense",    label: "Interest Expense", fmt: "large" },
];

function sectionRow(label, colspan, url) {
  const link = url ? srcLink(url) : "";
  return `<tr class="section-row"><td colspan="${colspan}">${label}${link}</td></tr>`;
}

function renderRawTable(tickers, raw) {
  const cols = tickers.length + 1;
  const t0   = tickers[0];
  const head = `<thead><tr><th>Field</th>${tickers.map(t => `<th>${t}</th>`).join("")}</tr></thead>`;

  const snapSections = SNAPSHOT_SECTIONS.map(sec => {
    const rows = sec.fields.map(f => {
      const cells = tickers.map(t => `<td>${fmtRaw(raw[t]?.snapshot?.[f.key], f.fmt)}</td>`).join("");
      return `<tr><td>${f.label}</td>${cells}</tr>`;
    }).join("");
    return sectionRow(sec.label, cols, sec.src(t0)) + rows;
  }).join("");

  const retRows = RETURNS_FIELDS.map(f => {
    const cells = tickers.map(t => `<td>${fmtRaw(raw[t]?.returns?.[f.key], f.fmt)}</td>`).join("");
    return `<tr><td>${f.label}</td>${cells}</tr>`;
  }).join("");

  return `
    <section class="cat-section">
      <h2>Market Data</h2>
      <table>
        ${head}
        <tbody>
          ${snapSections}
          ${sectionRow("Returns vs SPY", cols, RETURNS_SOURCE(t0))}
          ${retRows}
        </tbody>
      </table>
    </section>`;
}

function renderFundamentalsTable(tickers, raw) {
  const t0          = tickers[0];
  const annuals     = raw[t0]?.annuals    || [];
  const quarterlies = raw[t0]?.quarterlies || [];
  const periods     = [...annuals, ...quarterlies];

  if (!periods.length) return "";

  const periodCols  = periods.map(p => `<th>${p.period}</th>`).join("");
  const head        = `<thead><tr><th>Field</th>${periodCols}</tr></thead>`;
  const annualCount = annuals.length;

  const rows = FUND_FIELDS.map(f => {
    const cells = periods.map((p, i) => {
      const cls = i < annualCount ? "" : " class=\"subtext\"";
      return `<td${cls}>${fmtRaw(p[f.key], f.fmt)}</td>`;
    }).join("");
    return `<tr><td>${f.label}</td>${cells}</tr>`;
  }).join("");

  const sepCol = annualCount > 0 && quarterlies.length > 0
    ? `<col span="${annualCount}" style="border-right:2px solid var(--border)">`
    : "";

  return `
    <section class="cat-section">
      <h2>Fundamentals${srcLink(FINANCIALS_SOURCE(t0))}</h2>
      <table>
        <colgroup><col>${sepCol}</colgroup>
        ${head}
        <tbody>${rows}</tbody>
      </table>
    </section>`;
}

function renderInsiderTable(tickers, raw) {
  const t0  = tickers[0];
  const txs = (raw[t0]?.insider_transactions || [])
    .slice()
    .sort((a, b) => (b.trade_date || "").localeCompare(a.trade_date || ""));

  if (!txs.length) return "";

  const today  = new Date();
  const ago90  = new Date(today); ago90.setDate(today.getDate() - 90);
  const ago365 = new Date(today); ago365.setDate(today.getDate() - 365);

  const rows = txs.map(tx => {
    const td   = tx.trade_date ? new Date(tx.trade_date) : null;
    const in3m = td && td >= ago90;
    const in1y = td && td >= ago365;
    const tag3m = in3m ? `<span class="badge badge-green">3M</span>` : "";
    const tag1y = in1y && !in3m ? `<span class="badge badge-yellow">1Y</span>` : "";
    const type  = (tx.trade_type || "").replace(" - ", " ");
    const typeClass = type.startsWith("P") ? "s-green" : "s-red";
    return `<tr>
      <td>${tx.trade_date || "—"}</td>
      <td>${tx.insider_name || "—"}</td>
      <td class="subtext">${tx.title || "—"}</td>
      <td class="${typeClass}">${type}</td>
      <td>${tx.Qty || "—"}</td>
      <td>${tx.Price || "—"}</td>
      <td>${tx.Value || "—"}</td>
      <td>${tx["ΔOwn"] || "—"}</td>
      <td>${tag3m}${tag1y}</td>
    </tr>`;
  }).join("");

  return `
    <section class="cat-section">
      <h2>Insider Transactions${srcLink(INSIDER_SOURCE(t0))}</h2>
      <table>
        <thead>
          <tr>
            <th style="text-align:left">Date</th>
            <th style="text-align:left">Insider</th>
            <th style="text-align:left">Title</th>
            <th style="text-align:left">Type</th>
            <th>Qty</th>
            <th>Price</th>
            <th>Value</th>
            <th>ΔOwn</th>
            <th>Window</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </section>`;
}

// ── Score cards (detail view) ─────────────────────────────────────────────────
function scoreColor(s) {
  if (s === null || s === undefined) return "s-null";
  if (s >= 70) return "s-green";
  if (s >= 50) return "s-yellow";
  return "s-red";
}



function scoreLabel(s) {
  return (s === null || s === undefined) ? "—" : s.toFixed(1);
}

function fmDetails(sub) {
  if (!sub) return "—";
  const p = [];
  if (sub.revenue_trend  != null) p.push(sub.revenue_trend  >= 16 ? "Rev ↑"  : sub.revenue_trend  >= 8  ? "Rev →" : "Rev ↓");
  if (sub.ni_trajectory  != null) p.push(sub.ni_trajectory  >= 13 ? "NI ↑"   : sub.ni_trajectory  >= 8  ? "NI →"  : "NI ↓");
  if (sub.gm_expansion   != null) p.push(sub.gm_expansion   >= 9  ? "GM ↑"   : sub.gm_expansion   >= 6  ? "GM →"  : "GM ↓");
  if (sub.rule_of_40     >= 5)    p.push("R40 ✓");
  if (sub.buyback_signal >= 5)    p.push("Buybacks");
  return p.join(" · ") || "—";
}

function vqDetails(sub) {
  if (!sub) return "—";
  const p = [];
  if (sub.price_discount    != null) p.push(sub.price_discount    >= 12 ? "Discount ↑" : "Near fair");
  if (sub.balance_sheet     != null) p.push(sub.balance_sheet     >= 14 ? "Solid BS"   : sub.balance_sheet >= 8 ? "OK BS" : "Weak BS");
  if (sub.profitability     != null) p.push(sub.profitability     >= 14 ? "Profitable" : sub.profitability >= 8 ? "OK margins" : "Thin");
  if (sub.capital_discipline != null && sub.capital_discipline >= 7) p.push("Cap discipline ✓");
  return p.join(" · ") || "—";
}

function icDetails(sub) {
  if (!sub) return "—";
  const p = [];
  if (sub.score_3m    != null) p.push(`3M ${sub.score_3m >= 0 ? "+" : ""}${sub.score_3m.toFixed(0)}`);
  if (sub.valid_buys_3m != null) p.push(`${sub.valid_buys_3m}B / ${sub.valid_sells_3m || 0}S`);
  return p.join(" · ") || "—";
}

function poDetails(sub) {
  if (!sub) return "—";
  const p = [];
  if (sub.dip_signal      != null) p.push(sub.dip_signal    >= 20 ? "Dip ↑"       : sub.dip_signal    >= 10 ? "Mild dip" : "No dip");
  if (sub.short_setup     != null) p.push(sub.short_setup   >= 12 ? "Squeeze risk" : "Low short");
  if (sub.spy_divergence  != null) p.push(sub.spy_divergence >= 12 ? "SPY lag ↑"  : "");
  if (sub.options_sentiment != null && sub.options_sentiment >= 10) p.push("Fear (buy)");
  return p.filter(Boolean).join(" · ") || "—";
}

function renderScoreCards(tickers, raw) {
  const blocks = tickers.map(ticker => {
    const scores = raw[ticker]?.scores;
    if (!scores) return "";

    const fm   = scores.fundamental_momentum || {};
    const vq   = scores.value_quality        || {};
    const ic   = scores.insider_conviction   || {};
    const po   = scores.price_opportunity    || {};
    const comp = scores.composite            || {};

    const action    = comp.action || "NA";
    const actionCls = "action-" + action;

    const cards = [
      { title: "Growth",   score: fm.score, detail: fmDetails(fm.sub_scores) },
      { title: "Quality",  score: vq.score, detail: vqDetails(vq.sub_scores) },
      { title: "Insiders", score: ic.score, detail: icDetails(ic.sub_scores) },
      { title: "Entry",    score: po.score, detail: poDetails(po.sub_scores) },
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
          <span class="action-badge ${actionCls}">${action}</span>
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
  const s3m   = ic.sub_scores?.score_3m;
  const scoreHtml = s3m != null
    ? `<span class="${s3m > 20 ? "s-green" : s3m < -20 ? "s-red" : "s-yellow"}">${s3m > 0 ? "+" : ""}${s3m.toFixed(0)}</span>`
    : "—";

  const rows = txs.slice(0, 8).map(tx => {
    const type    = (tx.trade_type || "").replace(" - ", " ");
    const typeCls = type.startsWith("P") ? "s-green" : "s-red";
    const td      = tx.trade_date ? new Date(tx.trade_date) : null;
    const in3m    = td && td >= ago90;
    return `<tr>
      <td>${tx.trade_date || "—"}</td>
      <td>${tx.insider_name || "—"}</td>
      <td class="subtext">${tx.title || "—"}</td>
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
    renderInsiderSummary(tickers, raw),
    renderRawTable(tickers, raw),
    renderFundamentalsTable(tickers, raw),
  ].join("");
}

// ── Home view ─────────────────────────────────────────────────────────────────
let _homeRefreshTimer = null;
let _detailRefreshTimer = null;
let portfolio = [];
let pfSortCol = "composite", pfSortDir = -1;
let wlSortCol = "composite", wlSortDir = -1;

async function loadLists() {
  const res = await fetch("/api/lists");
  const data = await res.json();
  watchlist = data.watchlist;
  portfolio = data.portfolio;
}

function getScore(d, col) {
  if (!d?.scores) return null;
  const s = d.scores;
  switch (col) {
    case "growth":    return s.fundamental_momentum?.score ?? null;
    case "quality":   return s.value_quality?.score        ?? null;
    case "insiders":  return s.insider_conviction?.score   ?? null;
    case "entry":     return s.price_opportunity?.score    ?? null;
    case "composite": return s.composite?.score            ?? null;
    default: return null;
  }
}

function _toggleSort(currentCol, currentDir, col) {
  return currentCol === col ? [currentCol, currentDir * -1] : [col, -1];
}

function setPfSort(col) {
  [pfSortCol, pfSortDir] = _toggleSort(pfSortCol, pfSortDir, col);
  renderHomeSections();
}

function setWlSort(col) {
  [wlSortCol, wlSortDir] = _toggleSort(wlSortCol, wlSortDir, col);
  renderHomeSections();
}

const SCORE_COLS = [
  { key: "growth",    label: "Growth"   },
  { key: "quality",   label: "Quality"  },
  { key: "insiders",  label: "Insiders" },
  { key: "entry",     label: "Entry"    },
  { key: "composite", label: "Score"    },
];

function renderTickerTable(tickers, sc, sd, sortFnName, actionCell) {
  const sorted = [...tickers].sort((a, b) => {
    const va = getScore(watchlistData[a], sc);
    const vb = getScore(watchlistData[b], sc);
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

  const head = `<thead><tr>
    <th style="text-align:left">Ticker</th>
    ${SCORE_COLS.map(thCell).join("")}
    <th>Updated</th>
    <th></th>
  </tr></thead>`;

  const rows = sorted.map(ticker => {
    const d = watchlistData[ticker];
    if (!d) {
      return `<tr>
        <td class="td-ticker"><span class="ticker-link" onclick="navigate('#ticker/${ticker}')">${ticker}</span></td>
        <td colspan="5" class="subtext" style="font-size:11px">No data — click to fetch</td>
        <td class="subtext">—</td>
        <td>${actionCell(ticker)}</td>
      </tr>`;
    }

    const ready = d.data_ready;
    const scoreCells = SCORE_COLS.map(c => {
      if (!ready) return `<td class="s-null"
        onmouseenter="showScoreTooltip(event,'${ticker}','${c.key}')"
        onmouseleave="hideTooltip()">?</td>`;
      const s = getScore(d, c.key);
      return `<td class="${scoreColor(s)}"
        onmouseenter="showScoreTooltip(event,'${ticker}','${c.key}')"
        onmouseleave="hideTooltip()">${s != null ? s.toFixed(1) : "—"}</td>`;
    }).join("");

    const action    = ready ? (d.scores?.composite?.action || "NA") : "?";
    const refreshed = timeAgo(d.refreshed_at);

    return `<tr>
      <td class="td-ticker"
          onmouseenter="showTooltip(event, '${ticker}')"
          onmouseleave="hideTooltip()">
        <span class="ticker-link" onclick="navigate('#ticker/${ticker}')">${ticker}</span>
        <span class="action-badge action-${action}" style="margin-left:6px">${action}</span>
      </td>
      ${scoreCells}
      ${ready
        ? `<td class="subtext">${refreshed}</td>`
        : `<td class="s-null" style="font-size:10px">loading…</td>`}
      <td style="text-align:right;white-space:nowrap">${actionCell(ticker)}</td>
    </tr>`;
  }).join("");

  return `<table class="watchlist-table">${head}<tbody>${rows}</tbody></table>`;
}

function renderHomeSections() {
  const dash = document.getElementById("dashboard");

  if (!portfolio.length && !watchlist.length) {
    dash.innerHTML = `<p class="subtext center" style="margin-top:60px">Add a ticker above to start.</p>`;
    return;
  }

  let html = "";

  if (portfolio.length) {
    html += `<section class="cat-section watchlist-section">
      <h2>Portfolio</h2>
      ${renderTickerTable(portfolio, pfSortCol, pfSortDir, "setPfSort",
        t => `<button class="btn-move" title="Move to watchlist" onclick="moveToWatchlist('${t}')">↓ WL</button>
              <button class="btn-remove" onclick="removeTicker('${t}')">✕</button>`
      )}
    </section>`;
  }

  if (watchlist.length) {
    html += `<section class="cat-section watchlist-section">
      <h2>Watchlist</h2>
      ${renderTickerTable(watchlist, wlSortCol, wlSortDir, "setWlSort",
        t => `<button class="btn-move" title="Move to portfolio" onclick="moveToPortfolio('${t}')">↑ PF</button>
              <button class="btn-remove" onclick="removeTicker('${t}')">✕</button>`
      )}
    </section>`;
  }

  dash.innerHTML = html;
}

async function showHome() {
  renderHeader("home");
  const dash = document.getElementById("dashboard");
  dash.innerHTML = `<p class="subtext center">Loading…</p>`;

  try { await loadLists(); } catch (e) { console.error("Failed to load lists:", e); }

  const allTickers = [...new Set([...portfolio, ...watchlist])];
  if (!allTickers.length) {
    dash.innerHTML = `<p class="subtext center" style="margin-top:60px">Add a ticker above to start.</p>`;
    return;
  }

  try {
    const res = await fetch("/api/watchlist?tickers=" + allTickers.join(","));
    watchlistData = await res.json();
  } catch (e) {
    console.error("Home load failed:", e);
  }

  renderHomeSections();

  if (_homeRefreshTimer) clearInterval(_homeRefreshTimer);
  _homeRefreshTimer = setInterval(async () => {
    const tickers = [...new Set([...portfolio, ...watchlist])];
    if (!tickers.length) return;
    try {
      const res = await fetch("/api/watchlist?tickers=" + tickers.join(","));
      watchlistData = await res.json();
      renderHomeSections();
    } catch (e) { console.error("Auto-refresh failed:", e); }
  }, 5 * 60 * 1000);
}

async function handleAddTicker() {
  const input = document.getElementById("add-input");
  if (!input) return;
  const ticker = input.value.trim().toUpperCase();
  if (!ticker || !/^[A-Z.]{1,10}$/.test(ticker)) { input.value = ""; return; }
  if (portfolio.includes(ticker) || watchlist.includes(ticker)) { input.value = ""; return; }

  input.value = "";
  await fetch(`/api/lists/${ticker}`, {method: "POST"});
  watchlist.push(ticker);
  watchlistData[ticker] = null;
  renderHomeSections();

  try {
    await fetch("/api/lookup/" + ticker);
    const allTickers = [...new Set([...portfolio, ...watchlist])];
    const res = await fetch("/api/watchlist?tickers=" + allTickers.join(","));
    watchlistData = await res.json();
  } catch (e) {
    console.error("Fetch failed for", ticker, e);
  }

  renderHomeSections();
}

async function removeTicker(ticker) {
  await fetch(`/api/lists/${ticker}`, {method: "DELETE"});
  portfolio = portfolio.filter(t => t !== ticker);
  watchlist = watchlist.filter(t => t !== ticker);
  delete watchlistData[ticker];
  renderHomeSections();
}

async function _moveTicker(ticker, targetList) {
  await fetch(`/api/lists/${ticker}?list_type=${targetList}`, {method: "PATCH"});
  if (targetList === "portfolio") {
    watchlist = watchlist.filter(t => t !== ticker);
    if (!portfolio.includes(ticker)) portfolio.push(ticker);
  } else {
    portfolio = portfolio.filter(t => t !== ticker);
    if (!watchlist.includes(ticker)) watchlist.push(ticker);
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
  renderHeader("detail", ticker, payload.refreshed_at);
  render([ticker], raw);
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
    return;
  }

  if (_detailRefreshTimer) clearInterval(_detailRefreshTimer);
  _detailRefreshTimer = setInterval(async () => {
    try { await _fetchAndRenderDetail(ticker); } catch (e) { console.error("Detail auto-refresh failed:", e); }
  }, 5 * 60 * 1000);
}

// ── Header ────────────────────────────────────────────────────────────────────
async function handleRefreshAll() {
  const allTickers = [...new Set([...portfolio, ...watchlist])];
  if (!allTickers.length) return;
  const btn = document.getElementById("refresh-all-btn");
  if (btn) { btn.textContent = "↻ …"; btn.disabled = true; btn.classList.add("loading"); }

  await Promise.all(allTickers.map(t =>
    fetch(`/api/refresh/${t}`, { method: "POST" }).catch(() => {})
  ));

  try {
    const res = await fetch("/api/watchlist?tickers=" + allTickers.join(","));
    watchlistData = await res.json();
  } catch (e) {
    console.error("Reload after refresh failed:", e);
  }

  renderHomeSections();
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
  <h1>StockDesk</h1>
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
  if (_homeRefreshTimer) { clearInterval(_homeRefreshTimer); _homeRefreshTimer = null; }
  if (_detailRefreshTimer) { clearInterval(_detailRefreshTimer); _detailRefreshTimer = null; }
  const hash = window.location.hash;
  if (hash.startsWith("#ticker/")) {
    const t = hash.slice(8).toUpperCase().replace(/[^A-Z.]/g, "");
    if (t) { showDetail(t); return; }
  }
  showHome();
}

window.addEventListener("hashchange", onRoute);
window.addEventListener("DOMContentLoaded", onRoute);

window.navigate         = navigate;
window.handleAddTicker  = handleAddTicker;
window.handleRefreshAll = handleRefreshAll;
window.removeTicker     = removeTicker;
window.moveToPortfolio  = moveToPortfolio;
window.moveToWatchlist  = moveToWatchlist;
window.setPfSort        = setPfSort;
window.setWlSort        = setWlSort;
window.showTooltip      = showTooltip;
window.showScoreTooltip = showScoreTooltip;
window.hideTooltip      = hideTooltip;
