"use strict";

// ── State ─────────────────────────────────────────────────────────────────────
let watchlist = [];
let watchlistData = {};
let tickerStatus = {};
let sortCol = "composite_short";
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

function miniGroupedChart(revVals, niVals, labels, width) {
  const n = labels.length;
  if (!n) return "";
  const allVals = [...revVals, ...niVals].map(v => (v === null || v === undefined) ? 0 : Number(v));
  const maxPos  = Math.max(...allVals.filter(v => v >= 0), 0);
  const maxNeg  = Math.max(...allVals.filter(v => v < 0).map(v => Math.abs(v)), 0);
  const maxAbs  = Math.max(maxPos, maxNeg, 1);

  const padH = 2, padLabel = 12, padVal = 14;
  const barAreaPos = maxPos > 0 ? 60 : 0;
  const barAreaNeg = maxNeg > 0 ? 60 : 0;
  const baseline   = padVal + barAreaPos;
  const height     = padVal + barAreaPos + barAreaNeg + padLabel;

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
      const area = val >= 0 ? barAreaPos : barAreaNeg;
      const bh   = Math.max((Math.abs(val) / maxAbs) * area, 1);
      const x    = gx + xOff;
      const y    = val >= 0 ? baseline - bh : baseline;
      const c    = val >= 0 ? color : "#f85149";
      const valY = val >= 0 ? (y - 3).toFixed(1) : (y + bh + 10).toFixed(1);
      return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" fill="${c}" rx="1"/>
<text x="${(x + bw / 2).toFixed(1)}" y="${valY}" text-anchor="middle" fill="${c}" font-size="9" font-family="monospace">${fmtShort(val)}</text>`;
    };

    return `${barSvg(rv,  0,        "#58a6ff")}
${barSvg(niv, bw + barGap, "#3fb950")}
<text x="${lblX}" y="${height - 2}" text-anchor="middle" fill="#8b949e" font-size="9" font-family="monospace">${shortPeriod(lbl)}</text>`;
  }).join("\n");

  return `<svg width="${width}" height="${height}" style="display:block;height:${height}px;margin-bottom:16px" xmlns="http://www.w3.org/2000/svg">
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

  const pad = 44;
  const innerW = width - 2 * pad;
  const sc = v => pad + ((v - minV) / range) * innerW;
  const midY = 20;
  const fmt = v => `$${Number(v).toFixed(0)}`;

  const lX = sc(low).toFixed(1), mX = sc(mean).toFixed(1),
        hX = sc(high).toFixed(1), pX = sc(price).toFixed(1);

  return `<svg width="${width}" height="${height}" overflow="visible" style="display:block;height:${height}px;margin-bottom:12px" xmlns="http://www.w3.org/2000/svg">
<rect x="${lX}" y="${(midY - 3)}" width="${(sc(high) - sc(low)).toFixed(1)}" height="6" fill="#21262d" rx="3"/>
<line x1="${lX}" y1="${midY - 6}" x2="${lX}" y2="${midY + 6}" stroke="#484f58" stroke-width="1.5"/>
<line x1="${hX}" y1="${midY - 6}" x2="${hX}" y2="${midY + 6}" stroke="#484f58" stroke-width="1.5"/>
<line x1="${mX}" y1="${midY - 8}" x2="${mX}" y2="${midY + 8}" stroke="#d29922" stroke-width="2"/>
<circle cx="${pX}" cy="${midY}" r="5" fill="#58a6ff"/>
<text x="${pX}" y="${midY - 14}" text-anchor="middle" fill="#58a6ff" font-size="10" font-family="monospace" font-weight="600">${fmt(price)}</text>
<text x="${lX}" y="${height - 1}" text-anchor="start" fill="#8b949e" font-size="10" font-family="monospace">${fmt(low)}</text>
<text x="${mX}" y="${height - 1}" text-anchor="middle" fill="#d29922" font-size="10" font-family="monospace">${fmt(mean)}</text>
<text x="${hX}" y="${height - 1}" text-anchor="end" fill="#8b949e" font-size="10" font-family="monospace">${fmt(high)}</text>
</svg>`;
}

function analystBar(sb, b, h, s, ss, width) {
  const total = (sb||0) + (b||0) + (h||0) + (s||0) + (ss||0);
  if (total === 0) return "";
  const barH = 20, labelH = 13, height = barH + labelH + 2;
  const segments = [
    { n: sb||0, color: "#3fb950", label: "Strong Buy" },
    { n: b||0,  color: "#7ee787", label: "Buy"        },
    { n: h||0,  color: "#8b949e", label: "Hold"       },
    { n: s||0,  color: "#f0883e", label: "Sell"       },
    { n: ss||0, color: "#f85149", label: "Strong Sell"},
  ].filter(seg => seg.n > 0);
  let x = 0;
  const parts = segments.map(seg => {
    const w = (seg.n / total) * width;
    const cx = (x + w / 2).toFixed(1);
    const out = `<rect x="${x.toFixed(1)}" y="0" width="${w.toFixed(1)}" height="${barH}" fill="${seg.color}" rx="2"/>
${w >= 18 ? `<text x="${cx}" y="${barH - 6}" text-anchor="middle" fill="#0d1117" font-size="10" font-family="monospace" font-weight="700">${seg.n}</text>` : ""}
${w >= 30 ? `<text x="${cx}" y="${barH + labelH}" text-anchor="middle" fill="${seg.color}" font-size="9" font-family="monospace">${seg.label}</text>` : `<text x="${cx}" y="${barH + labelH}" text-anchor="middle" fill="${seg.color}" font-size="9" font-family="monospace">${seg.n}</text>`}`;
    x += w;
    return out;
  });
  return `<svg width="${width}" height="${height}" overflow="visible" style="display:block;height:${height}px" xmlns="http://www.w3.org/2000/svg">${parts.join("")}</svg>`;
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

  const CW = 440;
  const annualChart  = miniGroupedChart(
    annuals.map(f => f.revenue),  annuals.map(f => f.net_income),  annuals.map(f => f.period),  CW);
  const quarterChart = miniGroupedChart(
    quarters.map(f => f.revenue), quarters.map(f => f.net_income), quarters.map(f => f.period), CW);

  const ptBar = priceTargetBar(price, snap.target_low, snap.target_mean, snap.target_high, 440, 64);

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
  <div class="tt-metric"><span class="tt-ml">52W Low</span><span class="tt-mv">${p(snap.week52_low)}</span></div>
  <div class="tt-metric"><span class="tt-ml">52W High</span><span class="tt-mv">${p(snap.week52_high)}</span></div>
  <div class="tt-metric"><span class="tt-ml">vs 52W Hi</span><span class="tt-mv ${pct52hCls}">${pct(snap.pct_from_52w_high)}</span></div>
  <div class="tt-metric"><span class="tt-ml">vs 1W Hi</span><span class="tt-mv ${snap.pct_from_1w_high != null ? (snap.pct_from_1w_high > -0.02 ? "s-yellow" : snap.pct_from_1w_high > -0.05 ? "s-null" : "s-green") : ""}">${pct(snap.pct_from_1w_high)}</span></div>
</div>
<div class="tt-analyst">
  <span class="tt-ml">${snap.analyst_count != null ? snap.analyst_count + " analysts" : "—"}</span>
  <div style="margin-top:6px">${analystBar(snap.rec_strong_buy, snap.rec_buy, snap.rec_hold, snap.rec_sell, snap.rec_strong_sell, 440)}</div>
</div>`;
}

function showTooltip(event, ticker) {
  const el = document.getElementById("tooltip");
  el.style.width = "";
  el.innerHTML = buildTooltip(ticker, watchlistData[ticker]);
  el.style.display = "block";
  positionTooltip(event, el);
}

function hideTooltip() {
  const el = document.getElementById("tooltip");
  if (el) el.style.display = "none";
}

function positionTooltip(event, el) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const TW = el.offsetWidth  || 492;
  const TH = el.offsetHeight || 400;
  let left = event.clientX + 18;
  let top  = event.clientY - 30;
  if (left + TW > vw - 8) left = event.clientX - TW - 18;
  if (top < 60) top = 60;
  if (top + TH > vh - 8) top = Math.max(60, vh - TH - 8);
  el.style.left = left + "px";
  el.style.top  = top + "px";
}

// ── Score detail tooltip ──────────────────────────────────────────────────────
function subScoreBar(label, val, max) {
  const v = (val === null || val === undefined) ? 0 : val;
  const pct = Math.min(100, (v / max) * 100);
  const barColor = pct >= 70 ? "var(--green)" : pct >= 40 ? "var(--yellow)" : "var(--red)";
  const numCls   = pct >= 70 ? "s-green"      : pct >= 40 ? "s-yellow"      : "s-red";
  return `<div class="tt-sub-row">
    <span class="tt-sub-lbl">${label}</span>
    <div class="tt-sub-bar-wrap"><div class="tt-sub-bar" style="width:${pct.toFixed(0)}%;background:${barColor}"></div></div>
    <span class="tt-sub-val ${numCls}">${v.toFixed(1)}<span class="subtext">/${max}</span></span>
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
        subScoreBar("Revenue Trend",  sub.revenue_trend,  30),
        subScoreBar("NI Trajectory",  sub.ni_trajectory,  28),
        subScoreBar("GM Expansion",   sub.gm_expansion,   20),
        subScoreBar("FCF Trajectory", sub.fcf_trajectory, 10),
        subScoreBar("R&D Intensity",  sub.rd_intensity,    6),
        subScoreBar("Rule of 40",     sub.rule_of_40,      6),
      ].join("");
      break;
    }
    case "quality": {
      category = scores.value_quality || {};
      title = "Quality";
      const sub = category.sub_scores || {};
      rows = [
        subScoreBar("Profitability",      sub.profitability,      35),
        subScoreBar("Balance Sheet",      sub.balance_sheet,      25),
        subScoreBar("Valuation",          sub.valuation,          20),
        subScoreBar("Capital Discipline", sub.capital_discipline, 12),
        subScoreBar("Analyst Conviction", sub.analyst_conviction,  8),
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
    case "price_short": {
      category = scores.price_short || {};
      title = "Price Short";
      const sub = category.sub_scores || {};
      rows = [
        subScoreBar("Dip Signal",        sub.dip_signal,        50),
        subScoreBar("Options Sentiment", sub.options_sentiment, 30),
        subScoreBar("Short Setup",       sub.short_setup,       20),
      ].join("");
      break;
    }
    case "price_long": {
      category = scores.price_long || {};
      title = "Price Long";
      const sub = category.sub_scores || {};
      rows = [
        subScoreBar("Price Discount", sub.price_discount, 40),
        subScoreBar("Analyst Upside", sub.analyst_upside, 35),
        subScoreBar("Buybacks",       sub.buyback_signal, 25),
      ].join("");
      break;
    }
    case "composite_short":
    case "composite_long": {
      const isShort = col === "composite_short";
      category = scores[col] || {};
      title = isShort ? "Score Short" : "Score Long";
      const priceKey = isShort ? "price_short" : "price_long";
      const priceLabel = isShort ? "P.Short" : "P.Long";
      const weights = category.weights || {};
      const cats = [
        { key: "fundamental_momentum", label: "Growth"    },
        { key: "value_quality",        label: "Quality"   },
        { key: "insider_conviction",   label: "Insiders"  },
        { key: priceKey,               label: priceLabel  },
      ];
      rows = cats.map(c => {
        const s  = scores[c.key]?.score;
        const wt = weights[c.key] ?? weights[priceKey] ?? 25;
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
  el.style.width = "";
  el.innerHTML = buildScoreTooltip(ticker, col);
  el.style.display = "block";
  positionTooltip(event, el);
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
  return p.join(" · ") || "—";
}

function vqDetails(sub) {
  if (!sub) return "—";
  const p = [];
  if (sub.balance_sheet      != null) p.push(sub.balance_sheet     >= 14 ? "Solid BS"   : sub.balance_sheet >= 8 ? "OK BS" : "Weak BS");
  if (sub.profitability      != null) p.push(sub.profitability     >= 14 ? "Profitable" : sub.profitability >= 8 ? "OK margins" : "Thin");
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
  if (sub.dip_signal      != null) p.push(sub.dip_signal     >= 20 ? "Dip ↑"       : sub.dip_signal    >= 10 ? "Mild dip" : "No dip");
  if (sub.price_discount  != null) p.push(sub.price_discount >= 12 ? "Discount ↑"   : "Near fair");
  if (sub.buyback_signal  != null && sub.buyback_signal >= 8) p.push("Buybacks ↑");
  if (sub.short_setup     != null) p.push(sub.short_setup    >= 12 ? "Squeeze risk" : "Low short");

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
  if (!d) return null;
  const snap = d.snapshot || {};
  const ret  = d.returns  || {};
  const s    = d.scores   || {};
  switch (col) {
    case "ticker":           return null;
    case "price":            return snap.price            ?? null;
    case "day_change":       return snap.day_change_pct   ?? null;
    case "week_change":      return ret.ticker_return_1w  ?? null;
    case "year_change":      return ret.ticker_return_12m ?? null;
    case "ath":              return snap.ath              ?? null;
    case "growth":           return s.fundamental_momentum?.score ?? null;
    case "quality":          return s.value_quality?.score        ?? null;
    case "insiders":         return s.insider_conviction?.score   ?? null;
    case "price_short":      return s.price_short?.score          ?? null;
    case "price_long":       return s.price_long?.score           ?? null;
    case "composite_short":  return s.composite_short?.score      ?? null;
    case "composite_long":   return s.composite_long?.score       ?? null;
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

const PRICE_COLS = [
  { key: "price",         label: "Price"  },
  { key: "day_change",    label: "Day %"  },
  { key: "week_change",   label: "1W %"   },
  { key: "year_change",   label: "52W %"  },
  { key: "ath",           label: "ATH"    },
];

const SCORE_COLS_INTERMEDIATE = [
  { key: "growth",      label: "Growth"    },
  { key: "quality",     label: "Quality"   },
  { key: "insiders",    label: "Insiders"  },
  { key: "price_short", label: "P.Short"   },
  { key: "price_long",  label: "P.Long"    },
];

const SCORE_COLS_FINAL = [
  { key: "composite_short", label: "Short" },
  { key: "composite_long",  label: "Long"  },
];

const SCORE_COLS = [...SCORE_COLS_INTERMEDIATE, ...SCORE_COLS_FINAL];

const STATUS_LIGHTS = [
  { key: "snap",  title: "Snapshot (price & market data)" },
  { key: "fund",  title: "Fundamentals annual"            },
  { key: "qtrs",  title: "Quarterlies (≥2 quarters)"     },
  { key: "ins",   title: "Insider transactions"           },
  { key: "score", title: "Score computed"                 },
];

function renderStatusLights(status) {
  if (!status) return `<div class="status-lights">${STATUS_LIGHTS.map(() => `<span class="sl sl-gray"></span>`).join("")}</div>`;
  return `<div class="status-lights">${STATUS_LIGHTS.map(l =>
    `<span class="sl sl-${status[l.key] || "gray"}" title="${l.title}"></span>`
  ).join("")}</div>`;
}

function renderTickerTable(tickers, sc, sd, sortFnName, actionCell) {
  const sorted = [...tickers].sort((a, b) => {
    if (sc === "ticker") return a.localeCompare(b) * sd;
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

  const lightsHeader = STATUS_LIGHTS.map(l => l.key[0].toUpperCase()).join(" ");
  const sepTh = (c, extra = "") =>
    `<th class="col-sep ${extra} sortable-th${c.key === sc ? " sort-active" : ""}" onclick="${sortFnName}('${c.key}')">${c.label}${c.key === sc ? (sd > 0 ? " ↑" : " ↓") : ""}</th>`;

  const sortTh = (key, label, extraClass = "") => {
    const active = key === sc;
    const arrow  = active ? (sd > 0 ? " ↑" : " ↓") : "";
    return `<th class="${extraClass} sortable-th${active ? " sort-active" : ""}" onclick="${sortFnName}('${key}')">${label}${arrow}</th>`;
  };

  const head = `<thead><tr>
    ${sortTh("ticker", "Ticker", "col-ticker")}
    <th style="text-align:left">Sector</th>
    ${sortTh("price",       "Price",  "col-sep")}
    ${sortTh("day_change",  "Day %")}
    ${sortTh("week_change", "1W %")}
    ${sortTh("year_change", "52W %")}
    ${sortTh("ath",         "ATH")}
    ${SCORE_COLS_INTERMEDIATE.map((c, i) => i === 0 ? sepTh(c) : thCell(c)).join("")}
    ${SCORE_COLS_FINAL.map((c, i) => i === 0 ? sepTh(c, "col-final") : `<th class="col-final sortable-th${c.key === sc ? " sort-active" : ""}" onclick="${sortFnName}('${c.key}')">${c.label}${c.key === sc ? (sd > 0 ? " ↑" : " ↓") : ""}</th>`).join("")}
    <th class="col-sep">Updated</th>
    <th title="${STATUS_LIGHTS.map(l => l.key[0].toUpperCase() + "=" + l.title).join(" · ")}" style="cursor:default">${lightsHeader}</th>
    <th></th>
  </tr></thead>`;

  const rows = sorted.map(ticker => {
    const d      = watchlistData[ticker];
    const status = tickerStatus[ticker];
    const snap   = d?.snapshot || {};
    const name   = snap?.name   || null;
    const sector = snap?.sector || "—";

    const tickerCell = `<td class="td-ticker"
        onmouseenter="showTooltip(event, '${ticker}')"
        onmouseleave="hideTooltip()">
      <div>
        <span class="ticker-link" onclick="navigate('#ticker/${ticker}')">${ticker}</span>
        ${d ? `<span class="action-badge action-${d.data_ready ? (d.scores?.composite_short?.action || "NA") : "?"}" style="margin-left:6px">${d.data_ready ? (d.scores?.composite_short?.action || "NA") : "?"}</span>` : ""}
      </div>
      ${name ? `<div class="ticker-company">${name}</div>` : ""}
    </td>`;

    if (!d) {
      return `<tr>
        ${tickerCell}
        <td class="td-sector">—</td>
        <td colspan="${PRICE_COLS.length}" class="col-sep subtext" style="font-size:11px">No data</td>
        <td colspan="${SCORE_COLS_INTERMEDIATE.length}" class="col-sep subtext">—</td>
        <td colspan="${SCORE_COLS_FINAL.length}" class="col-sep subtext">—</td>
        <td class="col-sep subtext">—</td>
        <td>${renderStatusLights(status)}</td>
        <td>${actionCell(ticker)}</td>
      </tr>`;
    }

    const ready = d.data_ready;
    const ret   = d?.returns  || {};

    const fmtPct = (v, th = 0.05) => {
      if (v == null) return "—";
      const cls = v >= th ? "s-green" : v <= -th ? "s-red" : "s-yellow";
      return `<span class="${cls}">${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%</span>`;
    };
    const fmtDay = v => fmtPct(v, 0.01);
    const fmtPrice = v => v != null ? `$${v.toFixed(2)}` : "—";

    const priceCells = `
      <td class="col-sep" style="font-variant-numeric:tabular-nums">${fmtPrice(snap.price)}</td>
      <td style="font-variant-numeric:tabular-nums">${fmtDay(snap.day_change_pct != null ? snap.day_change_pct / 100 : null)}</td>
      <td style="font-variant-numeric:tabular-nums">${fmtPct(ret.ticker_return_1w)}</td>
      <td style="font-variant-numeric:tabular-nums">${fmtPct(ret.ticker_return_12m)}</td>
      <td style="font-variant-numeric:tabular-nums">${snap.ath != null ? `$${snap.ath.toFixed(2)}` : "—"}</td>
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

    const intermediateCells = SCORE_COLS_INTERMEDIATE.map((c, i) => makeScoreCell(c, i === 0 ? "col-sep" : "")).join("");
    const finalCells        = SCORE_COLS_FINAL.map((c, i) => makeScoreCell(c, i === 0 ? "col-sep col-final" : "col-final")).join("");

    const refreshed = timeAgo(d.refreshed_at);

    return `<tr>
      ${tickerCell}
      <td class="td-sector">${sector}</td>
      ${priceCells}
      ${intermediateCells}
      ${finalCells}
      ${ready
        ? `<td class="col-sep subtext">${refreshed}</td>`
        : `<td class="col-sep s-null" style="font-size:10px">loading…</td>`}
      <td>${renderStatusLights(status)}</td>
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

async function loadStatus(tickers) {
  if (!tickers.length) return;
  try {
    const res = await fetch("/api/status?tickers=" + tickers.join(","));
    tickerStatus = await res.json();
  } catch (e) {
    console.error("Status load failed:", e);
  }
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
    const [wlRes, stRes] = await Promise.all([
      fetch("/api/watchlist?tickers=" + allTickers.join(",")),
      fetch("/api/status?tickers="   + allTickers.join(",")),
    ]);
    watchlistData = await wlRes.json();
    tickerStatus  = await stRes.json();
  } catch (e) {
    console.error("Home load failed:", e);
  }

  renderHomeSections();
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
  }
}

// ── Header ────────────────────────────────────────────────────────────────────
async function handleRefreshAll() {
  const allTickers = [...new Set([...portfolio, ...watchlist])];
  if (!allTickers.length) return;
  const btn = document.getElementById("refresh-all-btn");
  if (btn) { btn.textContent = "↻ …"; btn.disabled = true; btn.classList.add("loading"); }

  await fetch("/api/refresh", { method: "POST" }).catch(() => {});

  while (true) {
    await new Promise(r => setTimeout(r, 2000));
    try {
      const [wlRes, stRes] = await Promise.all([
        fetch("/api/watchlist?tickers=" + allTickers.join(",")),
        fetch("/api/status?tickers="   + allTickers.join(",")),
      ]);
      watchlistData = await wlRes.json();
      tickerStatus  = await stRes.json();
    } catch (e) {
      console.error("Poll failed:", e);
    }
    renderHomeSections();
    if (!tickerStatus._running) break;
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
  <button class="btn btn-secondary" onclick="triggerImport()" title="Replace all tickers from a CSV file">↑ Import</button>
  <input id="import-file-input" type="file" accept=".txt,.csv" style="display:none" onchange="handleImportFile(event)">
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
    const t = hash.slice(8).toUpperCase().replace(/[^A-Z.]/g, "");
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

async function handleImportFile(event) {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;

  const text = await file.text();
  const tickers = text
    .split(/[\s,;]+/)
    .map(t => t.trim().toUpperCase())
    .filter(t => t.length > 0 && t.length <= 10);

  if (!tickers.length) {
    alert("No valid tickers found in file.");
    return;
  }

  const confirmed = confirm(
    `⚠️ Warning: this will replace ALL current stocks with ${tickers.length} ticker(s) from the file.\n\n` +
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

window.navigate         = navigate;
window.handleAddTicker  = handleAddTicker;
window.handleRefreshAll = handleRefreshAll;
window.removeTicker     = removeTicker;
window.moveToPortfolio  = moveToPortfolio;
window.moveToWatchlist  = moveToWatchlist;
window.setPfSort        = setPfSort;
window.setWlSort        = setWlSort;
window.triggerImport    = triggerImport;
window.handleImportFile = handleImportFile;
window.showTooltip      = showTooltip;
window.showScoreTooltip = showScoreTooltip;
window.hideTooltip      = hideTooltip;
