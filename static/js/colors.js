// ── Score cards (detail view) ─────────────────────────────────────────────────
export function scoreColor(s) {
  if (s === null || s === undefined) return "s-null";
  if (s >= 80) return "ic-l5";
  if (s >= 60) return "ic-l4";
  if (s >= 40) return "ic-l3";
  if (s >= 20) return "ic-l2";
  return "ic-l1";
}

export function scoreColorVar(s) {
  if (s === null || s === undefined) return "var(--null)";
  if (s >= 80) return "var(--s5)";
  if (s >= 60) return "var(--s4)";
  if (s >= 40) return "var(--s3)";
  if (s >= 20) return "var(--s2)";
  return "var(--s1)";
}

export function pctScoreColor(val, scale) {
  if (val === null || val === undefined) return "s-null";
  return scoreColor(Math.max(0, Math.min(100, (val / scale) * 50 + 50)));
}

export function actionLabel(a) {
  return a || "NA";
}

export function actionBadge(scores) {
  const a = scores?.composite_long?.action || "NA";
  return `<span class="action-badge action-${a}">${actionLabel(a)}</span>${riskFlags(scores)}`;
}

export function riskFlags(scores) {
  const flags = scores?.flags;
  if (!flags || !flags.length) return "";
  return " " + flags.map(f =>
    `<span class="risk-flag risk-${f.key}" title="${(f.title || "").replace(/"/g, "&quot;")}">${f.label}</span>`
  ).join(" ");
}

export function fmtBuyTargetHtml(bt) {
  if (!bt || bt.price == null) return "—";
  const thr = `<span class="subtext" style="font-size:10px">≤ $${bt.price.toFixed(2)}</span>`;
  if (bt.signal === "buy") {
    return `<span class="s-green" style="font-weight:600">BUY</span> ${thr}`;
  }
  const pct = bt.pct_from_current;
  const near = pct != null && pct >= -0.04;
  const cls = near ? "s-yellow" : "s-red";
  const label = near ? "NEAR" : "WAIT";
  const dip = pct != null ? `${(pct * 100).toFixed(0)}%` : "";
  return `<span class="${cls}" style="font-weight:600">${label} ${dip}</span> ${thr}`;
}



export function fmt52wRangeHtml(price, low, high) {
  if (price == null) return "—";
  const p = `<span class="range52-price">$${price.toFixed(2)}</span>`;
  if (low == null || high == null || high <= low) return `<div class="range52">${p}</div>`;
  const pct = Math.max(0, Math.min(1, (price - low) / (high - low))) * 100;
  const end = v => v >= 10 ? `$${Math.round(v)}` : `$${v.toFixed(1)}`;
  return `<div class="range52">
    ${p}
    <span class="range52-track"><span class="range52-fill" style="width:${pct.toFixed(1)}%"></span><span class="range52-dot" style="left:${pct.toFixed(1)}%"></span></span>
    <div class="range52-ends"><span class="range52-end">${end(low)}</span><span class="range52-end">${end(high)}</span></div>
  </div>`;
}


export function scoreLabel(s) {
  return (s === null || s === undefined) ? "—" : s.toFixed(1);
}
