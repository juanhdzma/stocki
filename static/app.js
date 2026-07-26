"use strict";

// ── State ─────────────────────────────────────────────────────────────────────
let watchlist = [];
let watchlistData = {};
let tickerStatus = {};

// ── Source URLs ───────────────────────────────────────────────────────────────
const INSIDER_SOURCE = t => `https://openinsider.com/screener?s=${t}`;

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
  const pct52hCls = pct52h != null ? pctScoreColor(pct52h, 0.30) : "";

  const comp = scores.composite_long || {};

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
  const icScore = scores.insider_conviction?.score ?? null;

  const p   = v => v != null ? `$${Number(v).toFixed(2)}` : "—";
  const pct = v => v != null ? `${(Number(v) * 100).toFixed(1)}%` : "—";
  const dec = v => v != null ? Number(v).toFixed(1) : "—";

  return `
<div class="tt-head">
  <span class="tt-ticker">${ticker}</span>
  <span class="tt-price">${price ? p(price) : "—"}</span>
  ${pct52hStr ? `<span class="tt-52h ${pct52hCls}">${pct52hStr}</span>` : ""}
  <span style="margin-left:auto;display:flex;align-items:center;gap:6px">
    ${actionBadge(scores)}
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
  <div class="tt-metric"><span class="tt-ml">vs 1W Hi</span><span class="tt-mv ${snap.pct_from_1w_high != null ? pctScoreColor(snap.pct_from_1w_high, 0.10) : ""}">${pct(snap.pct_from_1w_high)}</span></div>
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
  if (val === null || val === undefined) {
    return `<div class="tt-sub-row">
      <span class="tt-sub-lbl">${label}</span>
      <div class="tt-sub-bar-wrap"></div>
      <span class="tt-sub-val s-null">—<span class="subtext">/${max}</span></span>
    </div>`;
  }
  const pct = Math.min(100, (val / max) * 100);
  const barColor = scoreColorVar(pct);
  const numCls   = scoreColor(pct);
  return `<div class="tt-sub-row">
    <span class="tt-sub-lbl">${label}</span>
    <div class="tt-sub-bar-wrap"><div class="tt-sub-bar" style="width:${pct.toFixed(0)}%;background:${barColor}"></div></div>
    <span class="tt-sub-val ${numCls}">${val.toFixed(1)}<span class="subtext">/${max}</span></span>
  </div>`;
}

function bonusRow(label, val, max) {
  if (val === null || val === undefined) {
    return `<div class="tt-sub-row tt-bonus-row">
      <span class="tt-sub-lbl">${label}</span>
      <div class="tt-sub-bar-wrap"></div>
      <span class="tt-sub-val s-null">—</span>
    </div>`;
  }
  const pct = max ? Math.min(100, (val / max) * 100) : 0;
  return `<div class="tt-sub-row tt-bonus-row">
    <span class="tt-sub-lbl">${label}</span>
    <div class="tt-sub-bar-wrap"><div class="tt-sub-bar" style="width:${pct.toFixed(0)}%;background:var(--green)"></div></div>
    <span class="tt-bonus-badge">+${val.toFixed(1)}</span>
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
  const barColor = scoreColorVar(Math.max(0, Math.min(100, (val / max) * 50 + 50)));
  const numCls   = pctScoreColor(val, max);
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
      const max = category.max_pts || {};
      rows = [
        subScoreBar("Revenue Trend",  sub.revenue_trend,  max.revenue_trend),
        subScoreBar("NI Trajectory",  sub.ni_trajectory,  max.ni_trajectory),
        subScoreBar("GM Expansion",   sub.gm_expansion,   max.gm_expansion),
        subScoreBar("FCF Trajectory", sub.fcf_trajectory, max.fcf_trajectory),
        subScoreBar("R&D Intensity",  sub.rd_intensity,   max.rd_intensity),
        subScoreBar("Rule of 40",     sub.rule_of_40,     max.rule_of_40),
        subScoreBar("Est. Revisions", sub.estimate_revisions, max.estimate_revisions),
        subScoreBar("Growth Consistency", sub.growth_consistency, max.growth_consistency),
      ].join("");
      break;
    }
    case "quality": {
      category = scores.value_quality || {};
      title = "Quality";
      const sub = category.sub_scores || {};
      const max = category.max_pts || {};
      rows = [
        subScoreBar("Profitability",      sub.profitability,      max.profitability),
        subScoreBar("Cash Position",      sub.cash_runway,        max.cash_runway),
        subScoreBar("Execution Track",    sub.execution_track,    max.execution_track),
        subScoreBar("Margin Durability",  sub.margin_durability,  max.margin_durability),
        subScoreBar("Balance Sheet",      sub.balance_sheet,      max.balance_sheet),
        subScoreBar("Capital Discipline", sub.capital_discipline, max.capital_discipline),
        subScoreBar("Earnings Quality",   sub.earnings_quality,   max.earnings_quality),
        bonusRow("Buyback bonus",         sub.buyback_bonus,      max.buyback_bonus),
        bonusRow("Insider Ownership",     sub.insider_ownership_bonus, max.insider_ownership_bonus),
      ].join("");
      break;
    }
    case "insiders": {
      category = scores.insider_conviction || {};
      title = "Insiders";
      const sub = category.sub_scores || {};
      const txsRaw = d.insider_transactions || [];

      const yr365ms = 365 * 86400 * 1000;
      const nowMs   = Date.now();

      const roleShort = t => {
        const u = (t || "").toUpperCase();
        if (u.includes("CEO") || u.includes("PRESIDENT") || u.includes("CHAIRMAN")) return "CEO";
        if (u.includes("CFO") || u.includes("CHIEF FIN"))  return "CFO";
        if (u.includes("COO") || u.includes("CTO"))         return "COO";
        if (u.includes("SVP") || u.includes("EVP") || u.includes("CHIEF")) return "SVP";
        if (u.includes("10%") || u.includes("BENEFICIAL"))  return "10%";
        if (u.includes("DIRECTOR") || / DIR[,\s]/.test(" " + u)) return "Dir";
        if (u.includes("VP") || u.includes("VICE"))         return "VP";
        return "—";
      };
      const fmtVal = v => {
        if (v >= 1e9) return `$${(v/1e9).toFixed(1)}B`;
        if (v >= 1e6) return `$${(v/1e6).toFixed(1)}M`;
        if (v >= 1e3) return `$${(v/1e3).toFixed(0)}K`;
        return `$${v.toFixed(0)}`;
      };
      const fmtDate = dt => {
        const mo = String(dt.getMonth()+1).padStart(2,"0");
        const dy = String(dt.getDate()).padStart(2,"0");
        return `${mo}/${dy}`;
      };

      const mc = (d.snapshot || {}).market_cap || 0;

      const parseDeltaOwn = v => {
        const s = String(v || "").replace("%","").replace("+","").trim();
        if (!s || s.includes(">") || s.includes("<")) return null;
        const f = parseFloat(s);
        return isNaN(f) ? null : f / 100;
      };

      const parsed = txsRaw.map(tx => {
        const dt     = tx.trade_date ? new Date(tx.trade_date) : null;
        const rawVal = String(tx.Value || tx.value_usd || "0").replace(/[^0-9.-]/g, "");
        const val    = Math.abs(parseFloat(rawVal) || 0);
        const isBuy  = (tx.trade_type || "").startsWith("P");
        const role   = roleShort(tx.title);
        const dOwn   = parseDeltaOwn(tx["ΔOwn"] ?? tx.delta_own);

        // Mirror Python filter logic to label excluded transactions
        let excluded = null;
        if (!isBuy) {
          const isSaleOE = (tx.trade_type || "").includes("+OE") || (tx.trade_type || "").includes("OE");
          if (role === "10%") {
            excluded = "institutional";
          } else if (isSaleOE && (dOwn === null || dOwn >= -0.10)) {
            const pctStr = dOwn !== null ? ` (${(dOwn*100).toFixed(0)}%)` : "";
            excluded = `S+OE${pctStr}`;
          } else if (dOwn !== null) {
            const thr = mc > 500e9 ? -0.10 : mc > 10e9 ? -0.05 : -0.03;
            if (dOwn > thr) excluded = `Δ${(dOwn*100).toFixed(0)}%`;
          }
        }

        return { dt, val, isBuy, name: tx.insider_name || "—", title: tx.title || "", role, excluded };
      }).filter(tx => tx.dt && (nowMs - tx.dt.getTime()) <= yr365ms);

      // Detect scheduled sellers: 3+ sells, weekly/monthly cadence, low variance
      const sellDates = {};
      parsed.filter(tx => !tx.isBuy).forEach(tx => {
        (sellDates[tx.name] = sellDates[tx.name] || []).push(tx.dt.getTime());
      });
      const scheduled = new Set();
      for (const [name, dts] of Object.entries(sellDates)) {
        if (dts.length < 3) continue;
        const sorted = [...dts].sort((a,b) => a-b);
        const ivs = sorted.slice(1).map((d,i) => (d - sorted[i]) / 86400000);
        const m = ivs.reduce((a,b) => a+b, 0) / ivs.length;
        const s = Math.sqrt(ivs.reduce((a,b) => a + (b-m)**2, 0) / ivs.length);
        if (m >= 5 && m <= 35 && s/m < 0.30) scheduled.add(name);
      }

      // Scored first, then excluded; within each group sort by value desc
      const scored   = parsed.filter(tx => tx.isBuy || !tx.excluded);
      const excluded = parsed.filter(tx => !tx.isBuy && tx.excluded);
      const top = [
        ...scored.sort((a,b) => b.val - a.val).slice(0, 5),
        ...excluded.sort((a,b) => b.val - a.val).slice(0, 3),
      ];

      const validBuys  = sub.valid_buys  ?? "—";
      const validSells = sub.valid_sells ?? "—";

      const statsRow = `<div class="tt-sub-row" style="margin-bottom:6px">
        <span class="tt-sub-lbl">Scored activity (1Y)</span>
        <span class="tt-sub-val" style="margin-left:auto">
          <span class="s-green">${validBuys}B</span>
          <span class="subtext"> / </span>
          <span class="${(validSells||0) > 0 ? "s-red" : "s-null"}">${validSells}S</span>
        </span>
      </div>`;

      const txRows = top.length === 0
        ? `<div style="color:var(--subtext);font-size:11px;padding:4px 0">No significant activity in past year</div>`
        : top.map(tx => {
            const isExcluded = !tx.isBuy && !!tx.excluded;
            const isScheduled = !tx.isBuy && scheduled.has(tx.name);
            const opacity = isExcluded ? "opacity:0.4;" : "";
            const cls  = tx.isBuy ? "s-green" : (isExcluded ? "s-null" : "s-red");
            const dir  = tx.isBuy ? "B" : "S";
            const name = tx.name.length > 18 ? tx.name.slice(0, 17) + "…" : tx.name;
            const tag  = isExcluded
              ? `<span class="subtext" style="font-size:9px"> ${tx.excluded}</span>`
              : isScheduled
              ? `<span class="subtext" style="font-size:9px"> auto</span>`
              : "";
            return `<div class="tt-sub-row" style="font-size:11px;gap:4px;align-items:center;${opacity}">
              <span class="subtext" style="min-width:32px">${fmtDate(tx.dt)}</span>
              <span class="${cls}" style="min-width:18px;font-weight:700">${dir}</span>
              <span class="subtext" style="min-width:28px">${tx.role}</span>
              <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${name}</span>
              <span style="min-width:48px;text-align:right;font-weight:500">${fmtVal(tx.val)}${tag}</span>
            </div>`;
          }).join("");

      rows = statsRow + `<div style="border-top:1px solid var(--border);padding-top:5px;margin-top:2px">${txRows}</div>`;
      break;
    }
    case "price_long": {
      category = scores.price_long || {};
      title = "Sentimiento";
      const sub = category.sub_scores || {};
      const max = category.max_pts || {};
      rows = [
        subScoreBar("FCF Yield",          sub.fcf_yield,          max.fcf_yield),
        subScoreBar("Analyst Upside",     sub.analyst_upside,     max.analyst_upside),
        subScoreBar("Valuation",          sub.valuation,          max.valuation),
        subScoreBar("Analyst Conviction", sub.analyst_conviction, max.analyst_conviction),
      ].join("");
      break;
    }
    case "composite_long": {
      category = scores.composite_long || {};
      title = "Score Long";
      const weights = category.weights || {};
      const cats = [
        { key: "fundamental_momentum", label: "Growth"    },
        { key: "value_quality",        label: "Quality"   },
        { key: "insider_conviction",   label: "Insiders"  },
      ];
      const bar = s => s != null ? `<div class="tt-sub-bar" style="width:${Math.min(100, s).toFixed(0)}%;background:${s >= 70 ? "var(--green)" : s >= 50 ? "var(--yellow)" : "var(--red)"}"></div>` : "";
      rows = cats.map(c => {
        const s  = scores[c.key]?.score;
        const wt = weights[c.key] ?? 0;
        return `<div class="tt-sub-row">
          <span class="tt-sub-lbl">${c.label} <span class="subtext">${wt}%</span></span>
          <div class="tt-sub-bar-wrap">${bar(s)}</div>
          <span class="tt-sub-val ${scoreColor(s)}">${s != null ? s.toFixed(1) : "—"}</span>
        </div>`;
      }).join("");
      const pl = scores.price_long?.score ?? null;
      rows += `<div class="tt-sub-row" title="Attractive price can lift a good business into STRONG BUY — a rich price never drags it down">
        <span class="tt-sub-lbl">Sentimiento <span class="subtext">boost</span></span>
        <div class="tt-sub-bar-wrap">${bar(pl)}</div>
        <span class="tt-sub-val ${scoreColor(pl)}">${pl != null ? pl.toFixed(1) : "—"}</span>
      </div>`;
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

// ── Score delta tooltip ─────────────────────────────────────────────────────
const DELTA_CATEGORY_LABELS = {
  fundamental_momentum: "Growth",
  value_quality:        "Quality",
  insider_conviction:   "Insiders",
  price_long:           "Sentimiento",
};

function deltaBar(label, val, max) {
  const pct      = Math.min(100, (Math.abs(val) / max) * 100);
  const barColor = scoreColorVar(Math.max(0, Math.min(100, (val / max) * 50 + 50)));
  const numCls   = pctScoreColor(val, max);
  const rounded  = val.toFixed(1) === "-0.0" ? "0.0" : val.toFixed(1);
  const sign     = val > 0 ? "+" : "";
  return `<div class="tt-sub-row">
    <span class="tt-sub-lbl">${label}</span>
    <div class="tt-sub-bar-wrap"><div class="tt-sub-bar" style="width:${pct.toFixed(0)}%;background:${barColor}"></div></div>
    <span class="tt-sub-val ${numCls}">${sign}${rounded}</span>
  </div>`;
}

function buildDeltaTooltip(ticker) {
  const d  = watchlistData[ticker];
  const sc = d?.score_change;
  if (!sc) return `<div class="tt-head"><span class="tt-ticker">${ticker}</span><span class="subtext" style="margin-left:8px">Sin historial de hace 7d</span></div>`;

  const comp = sc.composite || {};
  const catRows = Object.entries(sc.categories || {})
    .map(([key, c]) => deltaBar(DELTA_CATEGORY_LABELS[key] || key, c.delta, 8))
    .join("");

  const moverRows = (sc.movers || []).map(m => `
    <div class="tt-sub-row" style="font-size:11px">
      <span class="tt-sub-lbl" style="opacity:.7">${m.category} · ${m.key.replace(/_/g, " ")}</span>
      <span class="tt-sub-val ${m.delta > 0 ? "s-green" : "s-red"}" style="margin-left:auto">${m.delta > 0 ? "+" : ""}${m.delta.toFixed(1)}</span>
    </div>`).join("");

  const deltaCls = comp.delta > 0 ? "s-green" : comp.delta < 0 ? "s-red" : "s-yellow";
  return `
<div class="tt-head">
  <span class="tt-ticker">${ticker}</span>
  <span class="subtext" style="margin-left:4px;font-size:11px">Score 7d ${comp.old?.toFixed(1)} → ${comp.new?.toFixed(1)}</span>
  <span class="tt-comp-score ${deltaCls}" style="margin-left:auto;font-size:13px;font-weight:700">${comp.delta > 0 ? "+" : ""}${comp.delta?.toFixed(1)}</span>
</div>
<div class="tt-subs">
  ${catRows}
  ${moverRows ? `<div style="border-top:1px solid var(--border);padding-top:5px;margin-top:5px">${moverRows}</div>` : ""}
</div>`;
}

function showDeltaTooltip(event, ticker) {
  const el = document.getElementById("tooltip");
  el.style.width = "";
  el.innerHTML = buildDeltaTooltip(ticker);
  el.style.display = "block";
  positionTooltip(event, el);
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
  if (s >= 80) return "ic-l5";
  if (s >= 60) return "ic-l4";
  if (s >= 40) return "ic-l3";
  if (s >= 20) return "ic-l2";
  return "ic-l1";
}

function scoreColorVar(s) {
  if (s === null || s === undefined) return "var(--null)";
  if (s >= 80) return "var(--s5)";
  if (s >= 60) return "var(--s4)";
  if (s >= 40) return "var(--s3)";
  if (s >= 20) return "var(--s2)";
  return "var(--s1)";
}

function pctScoreColor(val, scale) {
  if (val === null || val === undefined) return "s-null";
  return scoreColor(Math.max(0, Math.min(100, (val / scale) * 50 + 50)));
}

function actionLabel(a) {
  return (a || "NA").replace("-", " ");
}

function actionBadge(scores) {
  const a = scores?.composite_long?.action || "NA";
  return `<span class="action-badge action-${a}">${actionLabel(a)}</span>`;
}



function scoreLabel(s) {
  return (s === null || s === undefined) ? "—" : s.toFixed(1);
}

function fmtPctSigned(v) { return v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`; }
function fmtPctLevel(v)  { return v == null ? "—" : `${(v * 100).toFixed(1)}%`; }

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
    statRow("FCF Yield",      fmtPctLevel(snap.fcf_yield),          subPct(sub, max, "fcf_yield")),
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
      { title: "Sentimiento", score: pl.score, detail: plDetails(pl, snap) },
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

// ── Trajectory charts (detail view) ────────────────────────────────────────────
function fmtCompact(n) {
  if (n == null) return "—";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(0)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(0)}K`;
  return `${sign}${abs.toFixed(0)}`;
}

let chartRegistry = {};

function svgUserX(event, svgEl, viewBoxW) {
  const rect = svgEl.getBoundingClientRect();
  const relX = event.clientX - rect.left;
  return Math.max(0, Math.min(viewBoxW, relX * (viewBoxW / rect.width)));
}

function chartTooltipShow(event, html) {
  const el = document.getElementById("tooltip");
  el.style.width = "";
  el.innerHTML = html;
  el.style.display = "block";
  positionTooltip(event, el);
}

function chartHoverEnd(id) {
  const cross = document.getElementById(`${id}-cross`);
  const dot   = document.getElementById(`${id}-dot`);
  if (cross) cross.style.display = "none";
  if (dot)   dot.style.display = "none";
  hideTooltip();
}

function priceChartHover(event, id) {
  const reg = chartRegistry[id];
  if (!reg) return;
  const ux = svgUserX(event, document.getElementById(id), reg.W);
  let idx = Math.round((ux - reg.padX) / reg.gap);
  idx = Math.max(0, Math.min(reg.points.length - 1, idx));
  const p = reg.points[idx];
  const x = reg.padX + reg.gap * idx;
  const y = reg.plotTop + reg.plotH - ((p.close - reg.min) / reg.range) * reg.plotH;

  const cross = document.getElementById(`${id}-cross`);
  const dot   = document.getElementById(`${id}-dot`);
  if (cross) { cross.setAttribute("x1", x.toFixed(1)); cross.setAttribute("x2", x.toFixed(1)); cross.style.display = ""; }
  if (dot)   { dot.setAttribute("cx", x.toFixed(1)); dot.setAttribute("cy", y.toFixed(1)); dot.style.display = ""; }

  chartTooltipShow(event, `<div class="tt-head"><span class="tt-ticker">${p.date}</span></div><div style="padding:4px 2px;font-size:13px;font-weight:600">$${p.close.toFixed(2)}</div>`);
}

function calendarTicks(points, mode) {
  const raw = [0];
  for (let i = 1; i < points.length; i++) {
    const d = new Date(points[i].date + "T00:00:00");
    if (mode === "week") {
      if (d.getDay() === 1) raw.push(i);
    } else {
      const prev = new Date(points[i - 1].date + "T00:00:00");
      if (d.getMonth() !== prev.getMonth()) raw.push(i);
    }
  }
  const minGap = Math.max(1, Math.floor(points.length / 9));
  const ticks = [raw[0]];
  for (let i = 1; i < raw.length; i++) {
    if (raw[i] - ticks[ticks.length - 1] >= minGap) ticks.push(raw[i]);
  }
  return ticks;
}

function fmtTickDate(dateStr, mode) {
  const d = new Date(dateStr + "T00:00:00");
  if (mode === "month") return d.toLocaleDateString("en-US", { month: "short" });
  const [, m, day] = dateStr.split("-");
  return `${m}/${day}`;
}

function comboFundamentalsSvg(periods, id) {
  const hasRevNi = periods.filter(p => p.revenue != null || p.net_income != null).length >= 2;
  const marginCoordsRaw = periods.filter(p => p.gross_margin != null);
  if (!hasRevNi && marginCoordsRaw.length < 2) {
    return `<div class="subtext" style="font-size:11px">Not enough data</div>`;
  }

  const W = 720, H = 300;
  const padTop = 46, barsH = 150, negReserve = 32, labelY = H - 14, marginLabelY = 20;
  const baseline = padTop + barsH;
  const marginPlotTop = padTop + 14;
  const marginPlotBottom = baseline - 14;
  const marginPlotH = marginPlotBottom - marginPlotTop;

  const n = periods.length;
  const groupW = W / n;
  const barW   = groupW * 0.26;
  const gapBar = 8;

  const barsMaxAbs = Math.max(
    ...periods.map(p => Math.abs(p.revenue ?? 0)),
    ...periods.map(p => Math.abs(p.net_income ?? 0)),
    1e-9
  );

  const bar = (val, x, color, label) => {
    if (val == null) return "";
    const neg = val < 0;
    const h = (Math.abs(val) / barsMaxAbs) * (neg ? negReserve : barsH);
    const y = neg ? baseline : baseline - h;
    const ly = neg ? y + h + 16 : y - 8;
    return `
      <rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(h, 1).toFixed(1)}" rx="3" fill="${color}"><title>${label}: ${fmtCompact(val)}</title></rect>
      <text x="${(x + barW / 2).toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="middle" class="trend-bar-label">${fmtCompact(val)}</text>`;
  };

  const barsSvg = periods.map((p, i) => {
    const cx = groupW * i + groupW / 2;
    const rx = cx - barW - gapBar / 2;
    const nx = cx + gapBar / 2;
    return `
      ${bar(p.revenue,    rx, "var(--blue)", p.label)}
      ${bar(p.net_income, nx, p.net_income >= 0 ? "var(--green)" : "var(--red)", p.label)}
      <text x="${cx.toFixed(1)}" y="${labelY}" text-anchor="middle" class="trend-axis-label">${p.label}</text>`;
  }).join("");

  const baselineLine = `<line x1="0" y1="${baseline}" x2="${W}" y2="${baseline}" stroke="var(--border)" stroke-width="1"></line>`;

  let marginSvg = "";
  if (marginCoordsRaw.length >= 2) {
    const marginCoords = periods.map((p, i) => p.gross_margin == null ? null : {
      x: groupW * i + groupW / 2,
      v: p.gross_margin,
    }).filter(Boolean);
    const vals = marginCoords.map(c => c.v);
    const min = Math.min(...vals), max = Math.max(...vals);
    const range = (max - min) || 1;
    const coords = marginCoords.map(c => ({ x: c.x, v: c.v, y: marginPlotBottom - ((c.v - min) / range) * marginPlotH }));
    const pathD = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");
    const dots  = coords.map(c => `<circle cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(1)}" r="3" fill="var(--text)" stroke="var(--bg)" stroke-width="1.5"></circle>`).join("");
    const labels = coords.map(c => `<text x="${c.x.toFixed(1)}" y="${marginLabelY}" text-anchor="middle" class="trend-margin-label">${(c.v * 100).toFixed(0)}%</text>`).join("");
    marginSvg = `<path d="${pathD}" fill="none" stroke="var(--text)" stroke-width="1.5" stroke-dasharray="5 3" stroke-linecap="round" stroke-linejoin="round"></path>${dots}${labels}`;
  }

  return `<svg id="${id}" class="trend-svg" viewBox="0 0 ${W} ${H}">${baselineLine}${barsSvg}${marginSvg}</svg>`;
}

function priceLineSvg(points, id, mode) {
  if (points.length < 2) return `<div class="subtext" style="font-size:11px">Not enough data</div>`;
  const W = 720, H = 300;
  const padTop = 44, padBottom = 46, padXL = 54, padXR = 16;
  const plotTop = padTop, plotBottom = H - padBottom;
  const plotH = plotBottom - plotTop;
  const plotW = W - padXL - padXR;
  const closes = points.map(p => p.close);
  const min = Math.min(...closes), max = Math.max(...closes);
  const range = (max - min) || 1;
  const gap = plotW / (points.length - 1);

  chartRegistry[id] = { points, padX: padXL, gap, plotTop, plotH, min, range, W, kind: "price" };

  const coords = points.map((p, i) => ({
    x: padXL + gap * i,
    y: plotTop + plotH - ((p.close - min) / range) * plotH,
  }));

  const first = closes[0], last = closes[closes.length - 1];
  const color = last >= first ? "var(--green)" : "var(--red)";
  const pathD = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");
  const areaD = `${pathD} L${coords[coords.length - 1].x.toFixed(1)},${plotBottom} L${coords[0].x.toFixed(1)},${plotBottom} Z`;

  const mid = (max + min) / 2;
  const yGrid = [max, mid, min].map(v => {
    const y = plotTop + plotH - ((v - min) / range) * plotH;
    return `
      <line x1="${padXL}" y1="${y.toFixed(1)}" x2="${W - padXR}" y2="${y.toFixed(1)}" class="chart-gridline"></line>
      <text x="${(padXL - 8).toFixed(1)}" y="${(y + 3).toFixed(1)}" text-anchor="end" class="trend-axis-label">$${v.toFixed(0)}</text>`;
  }).join("");

  const ticks = calendarTicks(points, mode);
  const xGrid = ticks.map(i => {
    const x = padXL + gap * i;
    return `
      <line x1="${x.toFixed(1)}" y1="${plotTop}" x2="${x.toFixed(1)}" y2="${plotBottom}" class="chart-gridline"></line>
      <text x="${x.toFixed(1)}" y="${(plotBottom + 16).toFixed(1)}" text-anchor="middle" class="trend-axis-label">${fmtTickDate(points[i].date, mode)}</text>`;
  }).join("");

  const pctChange = ((last - first) / first) * 100;
  const changeLabel = `${pctChange >= 0 ? "+" : ""}${pctChange.toFixed(1)}%`;
  const last0 = coords[coords.length - 1];

  return `<svg id="${id}" class="trend-svg" viewBox="0 0 ${W} ${H}" onmousemove="priceChartHover(event,'${id}')" onmouseleave="chartHoverEnd('${id}')">
    ${yGrid}
    ${xGrid}
    <path d="${areaD}" fill="${color}" fill-opacity="0.12" stroke="none"></path>
    <path d="${pathD}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path>
    <circle cx="${last0.x.toFixed(1)}" cy="${last0.y.toFixed(1)}" r="3" fill="${color}"></circle>
    <line id="${id}-cross" class="chart-crosshair" x1="0" y1="${plotTop}" x2="0" y2="${plotBottom}" style="display:none"></line>
    <circle id="${id}-dot" class="chart-hover-dot" r="4" fill="var(--text)" stroke="${color}" stroke-width="2" style="display:none"></circle>
    <text x="${padXL}" y="20" text-anchor="start" class="trend-point-label" style="fill:${color}">${changeLabel}</text>
  </svg>`;
}

function rangeBar(lo, hi, markers, loLabel, hiLabel) {
  if (lo == null || hi == null || hi <= lo) return "";
  const dots = markers
    .filter(m => m.value != null)
    .map(m => {
      const rawPct = ((m.value - lo) / (hi - lo)) * 100;
      const outOfRange = rawPct < 0 || rawPct > 100;
      const clamped = Math.max(0, Math.min(100, rawPct));
      const cls = outOfRange ? "range-marker-out" : m.cls;
      const title = outOfRange ? `${m.title} (out of range)` : m.title;
      const edgeCls = outOfRange ? (rawPct < 0 ? " range-marker-label-left" : " range-marker-label-right") : "";
      const label = m.label ? `<span class="range-marker-label${edgeCls}">${m.label}</span>` : "";
      return `<div class="range-marker ${cls}" style="left:${clamped.toFixed(1)}%" title="${title}">${label}</div>`;
    })
    .join("");
  return `
    <div class="range-bar-row">
      <span class="range-edge-label">${loLabel}</span>
      <div class="range-track">${dots}</div>
      <span class="range-edge-label">${hiLabel}</span>
    </div>`;
}

function statColumn(label, valueHtml, extraClass = "") {
  return `<div class="stat-col ${extraClass}">
    ${valueHtml}
    <div class="range-title">${label}</div>
  </div>`;
}

function changeVal(v) {
  const cls = v == null ? "s-null" : v >= 0 ? "s-green" : "s-red";
  return `<span class="poc-val ${cls}">${fmtPctSigned(v)}</span>`;
}

function renderPriceOverview(snap, returns) {
  if (!snap || snap.price == null) return "";
  const price = snap.price;
  const fmt$ = v => v != null ? `$${v.toFixed(v >= 100 ? 0 : 2)}` : "—";

  const dayPct  = snap.day_change_pct != null ? snap.day_change_pct / 100 : null;
  const weekPct = returns?.ticker_return_1w ?? null;
  const athPct  = (snap.ath && price) ? (price - snap.ath) / snap.ath : null;

  const currentCol = statColumn("Current", `<div class="price-overview-price">${fmt$(price)}</div>`);
  const dayCol     = statColumn("Day",     changeVal(dayPct));
  const weekCol    = statColumn("Week",    changeVal(weekPct));
  const athCol     = statColumn("ATH",     changeVal(athPct));

  const w52Bar = rangeBar(
    snap.week52_low, snap.week52_high,
    [{ value: price, cls: "range-marker-current", title: `Current ${fmt$(price)}`, label: fmt$(price) }],
    fmt$(snap.week52_low), fmt$(snap.week52_high)
  );

  const hasTargets = snap.target_low != null && snap.target_high != null;
  const analystBarHtml = hasTargets ? rangeBar(
    snap.target_low, snap.target_high,
    [
      { value: snap.target_mean, cls: "range-marker-target",  title: `Analyst Target Mean ${fmt$(snap.target_mean)}`, label: fmt$(snap.target_mean) },
      { value: price,            cls: "range-marker-current", title: `Current ${fmt$(price)}`, label: fmt$(price) },
    ],
    fmt$(snap.target_low), fmt$(snap.target_high)
  ) : "";

  if (!w52Bar && !analystBarHtml) return "";

  return `
    <div class="price-overview">
      ${currentCol}
      ${dayCol}
      ${weekCol}
      ${athCol}
      <div class="range-group">
        ${w52Bar || `<div class="subtext" style="font-size:11px">No data</div>`}
        <div class="range-title">52W Range</div>
      </div>
      <div class="range-group">
        ${analystBarHtml || `<div class="subtext" style="font-size:11px">No analyst data</div>`}
        <div class="range-title">Analyst Target</div>
      </div>
    </div>`;
}

function renderPriceCharts(points, ticker) {
  const monthPoints = points.slice(-22);
  return `
    <div class="trend-chart">
      <div class="trend-chart-title">Price — 1 Year</div>
      ${priceLineSvg(points, `${ticker}-price1y`, "month")}
    </div>
    <div class="trend-chart">
      <div class="trend-chart-title">Price — 1 Month</div>
      ${priceLineSvg(monthPoints, `${ticker}-price1m`, "week")}
    </div>`;
}

async function loadPriceTrend(ticker) {
  const el = document.getElementById(`price-trend-${ticker}`);
  if (!el) return;

  if (priceHistoryCache[ticker]) {
    el.innerHTML = renderPriceCharts(priceHistoryCache[ticker], ticker);
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
    priceHistoryCache[ticker] = points;
    el.innerHTML = renderPriceCharts(points, ticker);
  } catch (e) {
    el.innerHTML = `<div class="trend-chart"><div class="subtext" style="font-size:11px">Failed to load price history</div></div>`;
    console.error(e);
  }
}

function shortQLabel(period) {
  const m = /^(\d{4})-Q(\d)$/.exec(period);
  return m ? `Q${m[2]} '${m[1].slice(2)}` : period;
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
    renderTrajectorySection(tickers, raw),
    renderAnalystSummary(tickers, raw),
    renderInsiderSummary(tickers, raw),
  ].join("");
}

// ── Home view ─────────────────────────────────────────────────────────────────
let portfolio = [];
let portfolioHoldings = {};
let portfolioData = {};
let editingTicker = null;
let pfSortCol = sessionStorage.getItem("pfSortCol") ?? "total";
let pfSortDir = Number(sessionStorage.getItem("pfSortDir") ?? -1);
let wlSortCol = sessionStorage.getItem("wlSortCol") ?? "ticker";
let wlSortDir = Number(sessionStorage.getItem("wlSortDir") ?? 1);
let lastDetail = null;
let priceHistoryCache = {};

async function loadLists() {
  const res = await fetch("/api/lists");
  const data = await res.json();
  watchlist = data.watchlist;
  portfolio = data.portfolio;
  portfolioHoldings = data.portfolio_holdings || {};
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
    case "ath":              return snap.week52_high       ?? null;
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

function _toggleSort(currentCol, currentDir, col) {
  return currentCol === col ? [currentCol, currentDir * -1] : [col, -1];
}

function setPfSort(col) {
  [pfSortCol, pfSortDir] = _toggleSort(pfSortCol, pfSortDir, col);
  sessionStorage.setItem("pfSortCol", pfSortCol);
  sessionStorage.setItem("pfSortDir", pfSortDir);
  renderHomeSections();
}

function setWlSort(col) {
  [wlSortCol, wlSortDir] = _toggleSort(wlSortCol, wlSortDir, col);
  sessionStorage.setItem("wlSortCol", wlSortCol);
  sessionStorage.setItem("wlSortDir", wlSortDir);
  renderHomeSections();
}

const PRICE_COLS = [
  { key: "price",         label: "Price"  },
  { key: "day_change",    label: "Day %"  },
  { key: "week_change",   label: "1W %"   },
  { key: "year_change",   label: "52W %"  },
  { key: "ath",           label: "52W Hi" },
  { key: "buy_target",    label: "Buy Target" },
];

const SCORE_COLS_INTERMEDIATE = [
  { key: "growth",      label: "Growth"    },
  { key: "quality",     label: "Quality"   },
  { key: "insiders",    label: "Insiders"  },
  { key: "price_long",  label: "Sentimiento" },
];

const SCORE_COLS_FINAL = [
  { key: "composite_long",  label: "Long"  },
];

const SCORE_COLS = [...SCORE_COLS_INTERMEDIATE, ...SCORE_COLS_FINAL];

// One compact symbol per row: fetch in progress / all good / something failed.
function renderStatusSymbol(status) {
  if (!status) return `<span class="subtext" title="Pendiente">·</span>`;
  const states = ["snap", "fund", "qtrs", "ins", "score"].map(k => status[k]);
  if (states.includes("yellow")) return `<span class="s-yellow" title="En proceso">⟳</span>`;
  if (states.includes("red"))    return `<span class="s-red" title="Falló un fetch">✕</span>`;
  if (status.score === "green")  return `<span class="s-green" title="OK">✓</span>`;
  return `<span class="subtext" title="Datos parciales">·</span>`;
}

function renderTickerTable(tickers, sc, sd, sortFnName, actionCell, pfCols = false) {
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
    ${sortTh("year_change", "52W %")}
    ${sortTh("ath",         "52W Hi")}
    ${sortTh("buy_target",  "Buy Target")}
    ${pfHeaders}
    ${SCORE_COLS_INTERMEDIATE.map((c, i) => i === 0 ? sepTh(c) : thCell(c)).join("")}
    ${SCORE_COLS_FINAL.map((c, i) => i === 0 ? sepTh(c, "col-final") : `<th class="col-final sortable-th${c.key === sc ? " sort-active" : ""}" onclick="${sortFnName}('${c.key}')">${c.label}${c.key === sc ? (sd > 0 ? " ↑" : " ↓") : ""}</th>`).join("")}
    ${sortTh("score_delta", "Δ7d", "col-sep")}
    <th class="col-sep">Updated</th>
    <th title="Estado de datos" style="text-align:center;cursor:default">·</th>
    <th></th>
  </tr></thead>`;

  const rows = sorted.map(ticker => {
    const d      = watchlistData[ticker];
    const snap   = d?.snapshot || {};
    const name   = snap?.name   || null;
    const sector = snap?.sector || "—";

    const tickerCell = `<td class="td-ticker"
        onmouseenter="showTooltip(event, '${ticker}')"
        onmouseleave="hideTooltip()">
      <div>
        <span class="ticker-link" onclick="navigate('#ticker/${ticker}')">${ticker}</span>
        ${d ? `<span style="margin-left:6px">${d.data_ready ? actionBadge(d.scores) : `<span class="action-badge action-NA">?</span>`}</span>` : ""}
      </div>
      ${name ? `<div class="ticker-company">${name}</div>` : ""}
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
        <td style="text-align:center">${renderStatusSymbol(tickerStatus[ticker])}</td>
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
    const fmtPrice = v => v != null ? `$${v.toFixed(2)}` : "—";

    const buyTarget = d.scores?.buy_target;
    const fmtBuyTarget = bt => {
      if (!bt || bt.price == null) return "—";
      const thr = `<span class="subtext" style="font-size:10px">≤ $${bt.price.toFixed(2)}</span>`;
      if (bt.signal === "buy") {
        return `<span class="s-green" style="font-weight:600">COMPRAR</span> ${thr}`;
      }
      const pct = bt.pct_from_current;
      const near = pct != null && pct >= -0.04;
      const cls = near ? "s-yellow" : "s-red";
      const label = near ? "CASI" : "ESPERAR";
      const dip = pct != null ? `${(pct * 100).toFixed(0)}%` : "";
      return `<span class="${cls}" style="font-weight:600">${label} ${dip}</span> ${thr}`;
    };

    const priceCells = `
      <td class="col-sep" style="font-variant-numeric:tabular-nums">${fmtPrice(snap.price)}</td>
      <td style="font-variant-numeric:tabular-nums">${fmtDay(snap.day_change_pct != null ? snap.day_change_pct / 100 : null)}</td>
      <td style="font-variant-numeric:tabular-nums">${fmtPct(ret.ticker_return_1w)}</td>
      <td style="font-variant-numeric:tabular-nums">${fmtPct(ret.ticker_return_12m)}</td>
      <td style="font-variant-numeric:tabular-nums">${snap.week52_high != null ? `$${snap.week52_high.toFixed(2)}` : "—"}</td>
      <td style="font-variant-numeric:tabular-nums">${fmtBuyTarget(buyTarget)}</td>
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
      const holding  = portfolioHoldings[ticker] || {};
      const avgCost  = holding.avg_cost;
      const shares   = holding.shares;
      const price    = snap.price;
      const total    = (shares != null && price != null) ? shares * price : null;
      const diffAbs  = (avgCost != null && shares != null && price != null) ? (price - avgCost) * shares : null;
      const diffPct  = (avgCost != null && price != null && avgCost > 0) ? (price - avgCost) / avgCost : null;
      const isEditing = editingTicker === ticker;

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
      <td class="td-sector">${sector}</td>
      ${priceCells}
      ${pfCells}
      ${intermediateCells}
      ${finalCells}
      ${deltaCell}
      ${ready
        ? `<td class="col-sep subtext">${refreshed}</td>`
        : `<td class="col-sep s-null" style="font-size:10px">loading…</td>`}
      <td style="text-align:center">${renderStatusSymbol(tickerStatus[ticker])}</td>
      <td style="text-align:right;white-space:nowrap">${actionCell(ticker)}</td>
    </tr>`;
  }).join("");

  return `<table class="watchlist-table">${head}<tbody>${rows}</tbody></table>`;
}

const PF_SORT_COLS = [
  { key: "price",       label: "Price"      },
  { key: "day_change",  label: "Day %"      },
  { key: "week_change", label: "1W %"       },
  { key: "year_change", label: "52W %"      },
  { key: "ath",         label: "52W Hi"      },
  { key: "pct_52w",    label: "vs 52W"      },
  { key: "cost_basis",  label: "Cost Basis" },
  { key: "shares",      label: "Shares"     },
  { key: "total",       label: "Total"      },
  { key: "diff_pct",    label: "Diff"       },
];

function getPfPrice(ticker, col) {
  const d  = portfolioData[ticker];
  const wd = watchlistData[ticker];
  const price     = d?.price          ?? wd?.snapshot?.price;
  const holding   = portfolioHoldings[ticker] || {};
  const costBasis = holding.avg_cost  ?? null;
  const shares    = holding.shares    ?? null;
  const total     = (shares != null && price != null) ? shares * price : null;
  const diffPct   = (costBasis != null && total != null && costBasis > 0) ? (total - costBasis) / costBasis : null;
  switch (col) {
    case "ticker":      return null;
    case "price":       return price ?? null;
    case "day_change":  return (d?.day_change_pct  ?? wd?.snapshot?.day_change_pct) ?? null;
    case "week_change": return (d?.return_1w        ?? wd?.returns?.ticker_return_1w) ?? null;
    case "year_change": return (d?.return_12m       ?? wd?.returns?.ticker_return_12m) ?? null;
    case "ath":         return wd?.snapshot?.week52_high ?? null;
    case "pct_52w":    return wd?.snapshot?.pct_from_52w_high ?? null;
    case "cost_basis":  return costBasis;
    case "shares":      return shares;
    case "total":       return total;
    case "diff_pct":    return diffPct;
    default: return null;
  }
}

function renderPortfolioTable(tickers) {
  const sc = pfSortCol, sd = pfSortDir;

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
    ${sortTh("year_change","52W %")}
    ${sortTh("ath",        "52W Hi")}
    ${sortTh("pct_52w",   "vs 52W")}
    ${sortTh("cost_basis", "Cost Basis", "col-sep pf-col", "text-align:right")}
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
  const fmtPrice = v => v != null ? `$${v.toFixed(2)}` : "—";

  const rows = sorted.map(ticker => {
    const pd      = portfolioData[ticker];
    const wd      = watchlistData[ticker];
    const holding = portfolioHoldings[ticker] || {};

    const name      = wd?.snapshot?.name || pd?.name || null;
    const isEditing = editingTicker === ticker;

    const tickerCell = `<td class="td-ticker"
        onmouseenter="${wd ? `showTooltip(event,'${ticker}')` : ''}"
        onmouseleave="hideTooltip()">
      <div>
        <span class="ticker-link" onclick="navigate('#ticker/${ticker}')">${ticker}</span>
        <span style="margin-left:6px">${actionBadge(wd?.scores)}</span>
      </div>
      ${name ? `<div class="ticker-company">${name}</div>` : ""}
    </td>`;

    const price      = pd?.price           ?? wd?.snapshot?.price;
    const dayChg     = pd?.day_change_pct  ?? wd?.snapshot?.day_change_pct;
    const ret1w      = pd?.return_1w       ?? wd?.returns?.ticker_return_1w;
    const ret12m     = pd?.return_12m      ?? wd?.returns?.ticker_return_12m;
    const ath        = wd?.snapshot?.week52_high ?? pd?.ath;
    const pct52w     = wd?.snapshot?.pct_from_52w_high ?? null;
    const refreshed  = pd ? timeAgo(pd.refreshed_at) : (wd?.refreshed_at ? timeAgo(wd.refreshed_at) : "—");

    const priceCells = `
      <td class="col-sep" style="font-variant-numeric:tabular-nums">${fmtPrice(price)}</td>
      <td style="font-variant-numeric:tabular-nums">${fmtDay(dayChg != null ? dayChg / 100 : null)}</td>
      <td style="font-variant-numeric:tabular-nums">${fmtPct(ret1w)}</td>
      <td style="font-variant-numeric:tabular-nums">${fmtPct(ret12m)}</td>
      <td style="font-variant-numeric:tabular-nums">${price != null && ath != null ? `$${ath.toFixed(2)}` : "—"}</td>
      <td style="font-variant-numeric:tabular-nums">${fmtPct(pct52w, 0.30)}</td>`;

    const costBasis = holding.avg_cost;
    const shares    = holding.shares;
    const total     = (shares != null && price != null) ? shares * price : null;
    const diffAbs   = (costBasis != null && total != null) ? total - costBasis : null;
    const diffPct   = (costBasis != null && total != null && costBasis > 0) ? (total - costBasis) / costBasis : null;

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
      ? `<input class="pf-input" id="pf-avgcost-${ticker}" type="number" step="0.01" min="0" placeholder="Cost basis" value="${costBasis ?? ""}" onkeydown="if(event.key==='Enter') saveHolding('${ticker}')">`
      : fmtAvgCost(costBasis);
    const sharesCell = isEditing
      ? `<input class="pf-input" id="pf-shares-${ticker}" type="number" step="1" min="0" placeholder="Shares" value="${shares ?? ""}" onkeydown="if(event.key==='Enter') saveHolding('${ticker}')">`
      : fmtShares(shares);

    const holdingCells = `
      <td class="col-sep pf-col">${costBasisCell}</td>
      <td class="pf-col">${sharesCell}</td>
      <td class="pf-col">${fmtTotal(total)}</td>
      <td class="pf-col">${fmtDiff(diffPct, diffAbs)}</td>`;

    const actionCell = isEditing
      ? `<button class="btn-save" onclick="saveHolding('${ticker}')">✓ Save</button>
         <button class="btn-remove" onclick="cancelEdit()">✕</button>`
      : `<button class="btn-edit" onclick="editHolding('${ticker}')">Edit</button>
         <button class="btn-move" title="Remove from portfolio" onclick="moveToWatchlist('${ticker}')">↓ WL</button>
         <button class="btn-remove" onclick="removeTicker('${ticker}')">✕</button>`;

    return `<tr>
      ${tickerCell}
      ${priceCells}
      ${holdingCells}
      <td class="col-sep subtext">${refreshed}</td>
      <td style="text-align:right;white-space:nowrap">${actionCell}</td>
    </tr>`;
  }).join("");

  return `<table class="watchlist-table">${head}<tbody>${rows}</tbody></table>`;
}

function editHolding(ticker) {
  editingTicker = ticker;
  renderHomeSections();
}

async function saveHolding(ticker) {
  const avgCostEl = document.getElementById(`pf-avgcost-${ticker}`);
  const sharesEl  = document.getElementById(`pf-shares-${ticker}`);
  const avg_cost  = avgCostEl?.value !== "" ? parseFloat(avgCostEl.value) : null;
  const shares    = sharesEl?.value  !== "" ? parseFloat(sharesEl.value)  : null;
  await fetch(`/api/portfolio/${ticker}/holding`, {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({avg_cost, shares}),
  });
  portfolioHoldings[ticker] = {avg_cost, shares};
  editingTicker = null;
  renderHomeSections();
}

function cancelEdit() {
  editingTicker = null;
  renderHomeSections();
}

function renderHomeSections() {
  const dash = document.getElementById("dashboard");

  if (!portfolio.length && !watchlist.length) {
    dash.innerHTML = `<p class="subtext center" style="margin-top:60px">Add a ticker above to start.</p>`;
    return;
  }

  let html = "";

  if (portfolio.length) {
    const pfTotal = portfolio.reduce((sum, t) => {
      const price  = portfolioData[t]?.price ?? watchlistData[t]?.snapshot?.price;
      const shares = portfolioHoldings[t]?.shares;
      return (price != null && shares != null) ? sum + price * shares : sum;
    }, 0);
    const pfTotalStr = pfTotal > 0
      ? `$${pfTotal.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2})}`
      : "";
    html += `<section class="cat-section watchlist-section">
      <h2>Portfolio ${pfTotalStr ? `<span class="pf-total-badge">${pfTotalStr}</span>` : ""}</h2>
      ${renderPortfolioTable(portfolio)}
    </section>`;
  }

  if (watchlist.length) {
    html += `<section class="cat-section watchlist-section">
      <h2>Watchlist</h2>
      ${renderTickerTable(watchlist, wlSortCol, wlSortDir, "setWlSort",
        t => `${!portfolio.includes(t)
          ? `<button class="btn-move" title="Add to portfolio" onclick="moveToPortfolio('${t}')">↑ PF</button>`
          : ""}
              <button class="btn-remove" onclick="removeTicker('${t}')">✕</button>`,
        false
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
    const [wlRes, pfRes, stRes] = await Promise.all([
      fetch("/api/watchlist?tickers=" + allTickers.join(",")),
      fetch("/api/portfolio/prices"),
      fetch("/api/status?tickers="   + allTickers.join(",")),
    ]);
    watchlistData = await wlRes.json();
    tickerStatus  = await stRes.json();
    const pfRaw   = await pfRes.json();
    const { _running, ...pfPrices } = pfRaw;
    portfolioData = pfPrices;
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
  delete portfolioHoldings[ticker];
  if (editingTicker === ticker) editingTicker = null;
  renderHomeSections();
}

async function _moveTicker(ticker, targetList) {
  await fetch(`/api/lists/${ticker}?list_type=${targetList}`, {method: "PATCH"});
  if (targetList === "portfolio") {
    if (!portfolio.includes(ticker)) portfolio.push(ticker);
    portfolioHoldings[ticker] = { avg_cost: null, shares: null };
  } else {
    portfolio = portfolio.filter(t => t !== ticker);
    delete portfolioHoldings[ticker];
    if (editingTicker === ticker) editingTicker = null;
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
  lastDetail = { ticker, raw };
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
  const allTickers = [...new Set([...portfolio, ...watchlist])];
  if (!allTickers.length) return;
  const btn = document.getElementById("refresh-all-btn");
  if (btn) { btn.textContent = "↻ …"; btn.disabled = true; btn.classList.add("loading"); }

  await fetch("/api/refresh", { method: "POST" }).catch(() => {});

  // Full /api/watchlist recomputes scores for every tracked ticker — too heavy to
  // re-poll wholesale every 2s. Instead poll the cheap /api/status, and only re-fetch
  // watchlist data for tickers whose refresh just finished (in_flight -> not in_flight).
  let prevStatus = { ...tickerStatus };

  while (true) {
    await new Promise(r => setTimeout(r, 2000));
    try {
      const stRes = await fetch("/api/status?tickers=" + allTickers.join(","));
      const newStatus = await stRes.json();

      const justDone = allTickers.filter(
        t => _isInFlight(prevStatus, t) && !_isInFlight(newStatus, t)
      );

      tickerStatus = newStatus;
      prevStatus   = newStatus;

      if (justDone.length) {
        const wlRes = await fetch("/api/watchlist?tickers=" + justDone.join(","));
        Object.assign(watchlistData, await wlRes.json());
      }
    } catch (e) {
      console.error("Poll failed:", e);
    }
    renderHomeSections();
    if (!tickerStatus._running) break;
  }

  // Safety net: guarantee everything is current once the refresh is done, in case
  // any ticker's in_flight window was missed between two 2s polls.
  try {
    const wlRes = await fetch("/api/watchlist?tickers=" + allTickers.join(","));
    watchlistData = await wlRes.json();
    renderHomeSections();
  } catch (e) {
    console.error("Final refresh failed:", e);
  }

  if (btn) { btn.textContent = "↻ Refresh"; btn.disabled = false; btn.classList.remove("loading"); }
}

async function handleRescore() {
  const allTickers = [...new Set([...portfolio, ...watchlist])];
  if (!allTickers.length) return;
  const btn = document.getElementById("rescore-btn");
  if (btn) { btn.textContent = "⟲ …"; btn.disabled = true; btn.classList.add("loading"); }

  try {
    const wlRes = await fetch("/api/watchlist?tickers=" + allTickers.join(","));
    watchlistData = await wlRes.json();
    renderHomeSections();
  } catch (e) {
    console.error("Rescore failed:", e);
  }

  if (btn) { btn.textContent = "⟲ Rescore"; btn.disabled = false; btn.classList.remove("loading"); }
}

async function handleRefreshPortfolio() {
  if (!portfolio.length) return;
  const btn = document.getElementById("refresh-pf-btn");
  if (btn) { btn.textContent = "↻ …"; btn.disabled = true; btn.classList.add("loading"); }

  await fetch("/api/portfolio/refresh", { method: "POST" }).catch(() => {});

  while (true) {
    await new Promise(r => setTimeout(r, 1500));
    try {
      const res = await fetch("/api/portfolio/prices");
      const raw = await res.json();
      const { _running, ...pfPrices } = raw;
      portfolioData = pfPrices;
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

window.navigate         = navigate;
window.handleAddTicker  = handleAddTicker;
window.handleRefreshAll = handleRefreshAll;
window.handleRescore = handleRescore;
window.removeTicker     = removeTicker;
window.moveToPortfolio  = moveToPortfolio;
window.moveToWatchlist  = moveToWatchlist;
window.setPfSort        = setPfSort;
window.setWlSort        = setWlSort;
window.triggerImport    = triggerImport;
window.handleImportFile = handleImportFile;
window.showTooltip      = showTooltip;
window.showScoreTooltip = showScoreTooltip;
window.showDeltaTooltip = showDeltaTooltip;
window.hideTooltip      = hideTooltip;
window.editHolding           = editHolding;
window.saveHolding           = saveHolding;
window.cancelEdit            = cancelEdit;
window.handleRefreshPortfolio = handleRefreshPortfolio;
