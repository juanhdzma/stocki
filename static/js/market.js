// Market-context cards shown above the tables: 4 fetched indicators (VIX / S&P 500 / Nasdaq 100 /
// 10Y yield) each with a range bar, plus 2 watchlist-derived cards (Opportunities / Pulse).

function chip(chg) {
  if (chg == null) return "";
  const cls = chg >= 0 ? "s-green" : "s-red";
  return `<span class="mkt-chg ${cls}">${chg >= 0 ? "+" : ""}${(chg * 100).toFixed(2)}%</span>`;
}

function rangeCard(label, d, { fmt, vixBands = false, lowLbl, highLbl }) {
  if (!d || d.value == null) {
    return `<div class="mkt-card"><div class="mkt-card-top"><span class="mkt-label">${label}</span></div><div class="mkt-value">—</div></div>`;
  }
  const v = d.value;
  let pos, trackCls, valCls = "";
  if (vixBands) {
    pos = Math.max(0, Math.min(100, ((v - 10) / 30) * 100));  // scale 10→40
    trackCls = "mkt-track-vix";
    valCls = v < 20 ? "s-green" : v < 30 ? "s-yellow" : "s-red";
  } else {
    const lo = d.low52, hi = d.high52;
    pos = (lo != null && hi != null && hi > lo) ? Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100)) : 50;
    trackCls = "mkt-track-neutral";
  }
  const lo = lowLbl ?? (d.low52 != null ? fmt(d.low52) : "—");
  const hi = highLbl ?? (d.high52 != null ? fmt(d.high52) : "—");
  return `<div class="mkt-card">
    <div class="mkt-card-top"><span class="mkt-label">${label}</span>${chip(d.change)}</div>
    <div class="mkt-value ${valCls}">${fmt(v)}</div>
    <div class="mkt-range"><div class="mkt-track ${trackCls}"></div><div class="mkt-marker" style="left:${pos.toFixed(1)}%"></div></div>
    <div class="mkt-range-lbls"><span>${lo}</span><span>${hi}</span></div>
  </div>`;
}

function statCard(label, big, sub, bigCls = "") {
  return `<div class="mkt-card mkt-card-stat">
    <div class="mkt-card-top"><span class="mkt-label">${label}</span></div>
    <div class="mkt-value ${bigCls}">${big}</div>
    <div class="mkt-stat-sub">${sub}</div>
  </div>`;
}

function oppCard(wd) {
  let buys = 0, entries = 0;
  for (const t in (wd || {})) {
    const s = wd[t]?.scores;
    if (!s) continue;
    const a = s.composite_long?.action;
    if (a === "BUY" || a === "STRONG-BUY") buys++;
    if (s.buy_target?.signal === "buy") entries++;
  }
  return statCard("Opportunities", buys, `BUY verdict · ${entries} at entry price`, buys ? "s-green" : "");
}

function pulseCard(wd) {
  const chgs = Object.values(wd || {}).map(d => d?.snapshot?.day_change_pct).filter(v => v != null);
  if (!chgs.length) return statCard("Pulse", "—", "no data today");
  const avg = chgs.reduce((a, b) => a + b, 0) / chgs.length;  // day_change_pct is already in percent
  return statCard("Pulse", `${avg >= 0 ? "+" : ""}${avg.toFixed(2)}%`, `avg across ${chgs.length} names today`, avg >= 0 ? "s-green" : "s-red");
}

export function renderMarketBar(market, watchlistData) {
  const m = market || {};
  const num = v => Math.round(v).toLocaleString("en-US");
  const cards = [
    rangeCard("VIX", m.vix, { fmt: v => v.toFixed(1), vixBands: true, lowLbl: "calm", highLbl: "fear" }),
    rangeCard("S&P 500", m.sp500, { fmt: num }),
    rangeCard("Nasdaq 100", m.nasdaq, { fmt: num }),
    rangeCard("10Y Yield", m.tnx, { fmt: v => `${v.toFixed(2)}%` }),
    oppCard(watchlistData),
    pulseCard(watchlistData),
  ];
  return `<div class="mkt-cards">${cards.join("")}</div>`;
}
