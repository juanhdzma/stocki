// Market-context cards shown above the tables: 4 fetched indicators (VIX / S&P 500 / Nasdaq 100 /
// 10Y yield) each with a range bar, plus 2 watchlist-derived cards (Opportunities / Pulse).

import { timeAgo } from "./format.js";

function updatedFooter(iso) {
  return iso ? `<div class="mkt-updated">as of ${timeAgo(iso)}</div>` : "";
}

function chip(chg) {
  if (chg == null) return "";
  const cls = chg >= 0 ? "s-green" : "s-red";
  return `<span class="mkt-chg ${cls}">${chg >= 0 ? "+" : ""}${(chg * 100).toFixed(2)}%<span class="mkt-chg-lbl">1d</span></span>`;
}

function rangeCard(label, d, { fmt, vixBands = false, lowLbl, highLbl, title = "", updated = "" }) {
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
  const tag = vixBands ? "" : `<span class="mkt-range-tag">52w</span>`;
  return `<div class="mkt-card"${title ? ` title="${title}"` : ""}>
    <div class="mkt-card-top"><span class="mkt-label">${label}</span>${chip(d.change)}</div>
    <div class="mkt-value ${valCls}">${fmt(v)}</div>
    <div class="mkt-range"><div class="mkt-track ${trackCls}"></div><div class="mkt-marker" style="left:${pos.toFixed(1)}%"></div></div>
    <div class="mkt-range-lbls"><span>${lo}</span>${tag}<span>${hi}</span></div>
    ${updatedFooter(updated)}
  </div>`;
}

function statCard(label, big, sub, bigCls = "", title = "", updated = "") {
  return `<div class="mkt-card mkt-card-stat"${title ? ` title="${title}"` : ""}>
    <div class="mkt-card-top"><span class="mkt-label">${label}</span></div>
    <div class="mkt-value ${bigCls}">${big}</div>
    <div class="mkt-stat-sub">${sub}</div>
    ${updatedFooter(updated)}
  </div>`;
}

function oppCard(wd, updated) {
  let buys = 0;
  const sectors = new Set();
  for (const t in (wd || {})) {
    const d = wd[t];
    if (d?.scores?.composite_long?.action === "STRONG-BUY") {
      buys++;
      if (d?.snapshot?.sector) sectors.add(d.snapshot.sector);
    }
  }
  const sub = buys ? `across ${sectors.size} sector${sectors.size === 1 ? "" : "s"}` : "none right now";
  return statCard("Opportunities", buys, sub, buys ? "s-green" : "",
    "Names with a STRONG-BUY verdict, and how many distinct sectors they span", updated);
}

function pulseCard(wd, updated) {
  const chgs = Object.values(wd || {}).map(d => d?.snapshot?.day_change_pct).filter(v => v != null);
  if (!chgs.length) return statCard("Pulse", "—", "no data today");
  const avg = chgs.reduce((a, b) => a + b, 0) / chgs.length;  // day_change_pct is already in percent
  return statCard("Pulse", `${avg >= 0 ? "+" : ""}${avg.toFixed(2)}%`, `avg 1d move of ${chgs.length} names`,
    avg >= 0 ? "s-green" : "s-red", "Average daily price change across your watchlist — the pulse of your list today", updated);
}

export function renderMarketBar(market, watchlistData, loadedAt) {
  const m = market || {};
  const mkUpd = m.fetched_at;
  const num = v => Math.round(v).toLocaleString("en-US");
  const rangeTitle = "Current level, its 1-day change, and where it sits in its 52-week low→high range";
  const cards = [
    rangeCard("VIX", m.vix, { fmt: v => v.toFixed(1), vixBands: true, lowLbl: "calm", highLbl: "fear", updated: mkUpd,
      title: "Market fear gauge — expected volatility. Higher = more fear. ≈10 calm, 20+ elevated, 30+ panic" }),
    rangeCard("S&P 500", m.sp500, { fmt: num, title: rangeTitle, updated: mkUpd }),
    rangeCard("Nasdaq 100", m.nasdaq, { fmt: num, title: rangeTitle, updated: mkUpd }),
    rangeCard("10Y Yield", m.tnx, { fmt: v => `${v.toFixed(2)}%`, title: rangeTitle, updated: mkUpd }),
    oppCard(watchlistData, loadedAt),
    pulseCard(watchlistData, loadedAt),
  ];
  return `<div class="mkt-cards">${cards.join("")}</div>`;
}
