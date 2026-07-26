import { scoreColor, scoreColorVar, pctScoreColor, actionBadge } from "./colors.js";
import { miniGroupedChart, priceTargetBar, analystBar } from "./charts.js";
import { escapeHtml } from "./format.js";

// ── Hover Tooltip ─────────────────────────────────────────────────────────────
export function buildTooltip(ticker, d) {
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

// ── Score detail tooltip ──────────────────────────────────────────────────────
export function subScoreBar(label, val, max) {
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

export function bonusRow(label, val, max) {
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

export function buildScoreTooltip(ticker, col, d) {
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
              <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(name)}</span>
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
      const bar = s => s != null ? `<div class="tt-sub-bar" style="width:${Math.min(100, s).toFixed(0)}%;background:${scoreColorVar(s)}"></div>` : "";
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

// ── Score delta tooltip ─────────────────────────────────────────────────────
export const DELTA_CATEGORY_LABELS = {
  fundamental_momentum: "Growth",
  value_quality:        "Quality",
  insider_conviction:   "Insiders",
  price_long:           "Sentimiento",
};

export function deltaBar(label, val, max) {
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

export function buildDeltaTooltip(ticker, d) {
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
