import { scoreColor, scoreColorVar, pctScoreColor, actionBadge } from "./colors.js";
import { escapeHtml } from "./format.js";

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
      title = "Sentiment";
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
        <span class="tt-sub-lbl">Sentiment <span class="subtext">boost</span></span>
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
  price_long:           "Sentiment",
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

export function buildBuyTargetTooltip(ticker, d) {
  const bt = d?.scores?.buy_target;
  const price = d?.snapshot?.price;
  if (!bt || bt.price == null) {
    return `<div class="tt-head"><span class="tt-ticker">${ticker}</span><span class="subtext" style="margin-left:8px">No buy target</span></div>`;
  }

  const $ = v => (v != null ? `$${v.toFixed(2)}` : "—");
  const row = (lbl, val, extra = "") =>
    `<div class="tt-sub-row"><span class="tt-sub-lbl">${lbl}</span><span class="tt-sub-val" style="margin-left:auto">${val}</span>${extra}</div>`;

  const isBuy = bt.signal === "buy";
  const sigCls = isBuy ? "s-green" : "s-red";
  const sigTxt = isBuy ? "BUY" : "WAIT";

  const volPct = bt.vol != null ? ` avg ${(bt.vol * 100).toFixed(0)}%` : "";
  const mosPct = (bt.mos * 100).toFixed(0);
  const volCls = { high: "s-red", mid: "s-yellow", low: "s-green", "n/a": "s-red" }[bt.vol_level] || "";
  const volRow = `<div class="tt-sub-row"><span class="tt-sub-lbl">Volatility <span class="${volCls}">${bt.vol_level || "—"}</span>${volPct}</span><span class="tt-sub-val" style="margin-left:auto">${bt.mos > 0 ? `−${mosPct}%` : "no discount"}</span></div>`;

  const vw = bt.vol_windows || {};
  const wins = ["1m", "6m", "12m"].filter(k => vw[k] != null);
  const winRow = wins.length
    ? `<div class="subtext" style="font-size:10px;margin-top:2px">${wins.map(k => `${k} ${(vw[k] * 100).toFixed(0)}%`).join(" · ")} → avg ${(bt.vol * 100).toFixed(0)}%</div>`
    : (bt.vol == null ? `<div class="subtext" style="font-size:10px;margin-top:2px">history &lt; 1 month → unmeasured, conservative margin</div>` : "");

  const vm = (bt.vol_mid * 100).toFixed(0), vh = (bt.vol_high * 100).toFixed(0);
  const bands = [["low", `<${vm}%`, "0%"], ["mid", `${vm}–${vh}%`, "−12%"], ["high", `≥${vh}%`, "−25%"]];
  const legend = `<div class="subtext" style="font-size:10px;display:flex;gap:8px;margin-top:3px">${
    bands.map(([lvl, rng, m]) => `<span${lvl === bt.vol_level ? ` class="${volCls}" style="font-weight:600"` : ""}>${lvl} ${rng} ${m}</span>`).join("")
  }</div>`;

  let head;
  if (bt.method === "p10") {
    head = `
      <div class="subtext" style="font-size:11px;margin-bottom:4px">10th percentile of ${bt.analysts} analysts</div>
      ${row("Low ×0.8", $(bt.low))}
      ${row("Median ×0.2", $(bt.p50))}
      ${row("= p10 anchor", `<b>${$(bt.anchor)}</b>`)}`;
  } else {
    head = `
      <div class="subtext" style="font-size:11px;margin-bottom:4px">Few analysts (${bt.analysts} &lt; 10) → 52-week-high rule</div>
      ${row("52-week high", $(bt.week52_high))}
      ${row("−20% = anchor", `<b>${$(bt.anchor)}</b>`)}`;
  }
  const body = `${head}${volRow}${winRow}${legend}${row("= Target", `<b>${$(bt.price)}</b>`)}`;

  const cmp = price != null
    ? `Price today ${$(price)} ${price <= bt.price ? "≤" : ">"} ${$(bt.price)}`
    : "";

  return `
<div class="tt-head">
  <span class="tt-ticker">${ticker}</span>
  <span class="subtext" style="margin-left:4px;font-size:11px">Buy Target</span>
  <span class="${sigCls}" style="margin-left:auto;font-weight:700">${sigTxt} ${$(bt.price)}</span>
</div>
<div class="tt-subs">
  ${body}
  <div style="border-top:1px solid var(--border);padding-top:5px;margin-top:5px;font-size:11px" class="${sigCls}">${cmp} → ${sigTxt}</div>
</div>`;
}

export function buildDeltaTooltip(ticker, d) {
  const sc = d?.score_change;
  if (!sc) return `<div class="tt-head"><span class="tt-ticker">${ticker}</span><span class="subtext" style="margin-left:8px">No 7d history</span></div>`;

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
