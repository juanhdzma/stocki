// "Today & Yesterday" section: insider trades and earnings in the last two market days, as tables.
// Built entirely from the already-fetched watchlist payload (each ticker carries
// insider_transactions + snapshot.earnings_events) — no dedicated endpoint. Dates are ET, the
// market reference the earnings datetimes are stamped in.

import { escapeHtml } from "./format.js";

function etDateStr(ms) {
  return new Date(ms).toLocaleDateString("en-CA", { timeZone: "America/New_York" });
}

function fmtTime(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" }) + " ET";
}

function dayTag(date, today, yesterday) {
  if (date === today) return `<span class="ty-day ty-today">today</span>`;
  if (date === yesterday) return `<span class="ty-day">yesterday</span>`;
  return "";
}

function tickerCell(ticker, name) {
  const company = name ? `<div class="ty-company">${escapeHtml(name)}</div>` : "";
  return `<td><a class="ticker-link" href="#ticker/${ticker}">${ticker}</a>${company}</td>`;
}

// openinsider trade_type looks like "P - Purchase" / "S - Sale"; classify by the leading code.
function isBuy(tradeType) {
  return /(^|\b)P\b|purchase|buy/i.test(tradeType || "");
}

// openinsider Value is a string like "-$4,263,469" / "+$73,820" → signed number.
function parseUsd(s) {
  if (!s) return null;
  const neg = /[-−]/.test(String(s));
  const n = parseFloat(String(s).replace(/[^0-9.]/g, ""));
  if (isNaN(n)) return null;
  return neg ? -n : n;
}

function fmtCompactUsd(n) {
  if (n == null) return "";
  const a = Math.abs(n), sign = n < 0 ? "−" : "+";
  let s;
  if (a >= 1e9) s = (a / 1e9).toFixed(1) + "B";
  else if (a >= 1e6) s = (a / 1e6).toFixed(1) + "M";
  else if (a >= 1e3) s = Math.round(a / 1e3) + "K";
  else s = a.toFixed(0);
  return `${sign}$${s}`;
}

// Collapse a verbose openinsider title to a single canonical role, most senior first.
const _MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const _ROLE_RANK = ["CEO", "Pres", "CFO", "COO", "CTO", "EVP", "SVP", "VP", "C-level", "GC", "Dir", "10%"];
function canonRole(title) {
  const t = (title || "").toUpperCase();
  if (/\bCEO\b|CHIEF EXECUTIVE/.test(t)) return "CEO";
  if (/\bCFO\b|CHIEF FINANCIAL/.test(t)) return "CFO";
  if (/\bCOO\b|CHIEF OPERATING/.test(t)) return "COO";
  if (/\bCTO\b|CHIEF TECH/.test(t)) return "CTO";
  if (/\bPRES(IDENT)?\b/.test(t)) return "Pres";
  if (/\bCHIEF\b|\bC[A-Z]O\b/.test(t)) return "C-level";
  if (/\bEVP\b/.test(t)) return "EVP";
  if (/\bSVP\b/.test(t)) return "SVP";
  if (/\bVP\b/.test(t)) return "VP";
  if (/\bGC\b|GENERAL COUNSEL/.test(t)) return "GC";
  if (/\bDIR\b|DIRECTOR/.test(t)) return "Dir";
  if (/10%/.test(t)) return "10%";
  return title || "";
}
function roleRank(r) {
  const i = _ROLE_RANK.indexOf(r);
  return i < 0 ? 99 : i;
}

function shortDate(iso) {
  const [, m, d] = (iso || "").split("-").map(Number);
  return m ? `${_MONTHS[m]} ${d}` : (iso || "");
}

function earningsRow(ev, today, yesterday, nowMs) {
  const reported = ev.reported_eps != null;
  const time = fmtTime(ev.datetime);
  let eps, estrep;
  if (reported) {
    const beat = ev.surprise_pct != null
      ? ev.surprise_pct > 0
      : (ev.eps_estimate != null && ev.reported_eps > ev.eps_estimate);
    const sPct = ev.surprise_pct != null ? `${ev.surprise_pct >= 0 ? "+" : ""}${ev.surprise_pct.toFixed(1)}%` : "";
    eps = `<span class="${beat ? "s-green" : "s-red"}">${beat ? "beat" : "miss"} ${sPct}</span>`;
    estrep = `${ev.eps_estimate != null ? ev.eps_estimate.toFixed(2) : "—"} → ${ev.reported_eps.toFixed(2)}`;
  } else {
    // Report time already passed but yahoo hasn't published the actuals yet → "awaiting".
    const past = new Date(ev.datetime).getTime() <= nowMs;
    eps = `<span class="ty-badge ${past ? "ty-await" : "ty-upcoming"}">${past ? "awaiting" : "upcoming"}</span>`;
    estrep = ev.eps_estimate != null ? `${ev.eps_estimate.toFixed(2)} → —` : "—";
  }
  return `<tr>
    ${tickerCell(ev.ticker, ev.name)}
    <td>${dayTag(ev.date, today, yesterday)}</td>
    <td class="subtext">${time || "—"}</td>
    <td>${eps}</td>
    <td class="ty-num subtext">${estrep}</td>
  </tr>`;
}

// One row per ticker+direction group — the person's name is noise (dropped), same-side trades
// are collapsed (count shown next to the value), role is the single most-senior one.
function insiderRow(g, today, yesterday) {
  const cls = g.buy ? "s-green" : "s-red";
  const cnt = g.count > 1 ? ` <span class="subtext" style="font-weight:400">×${g.count}</span>` : "";
  return `<tr>
    ${tickerCell(g.ticker, g.name)}
    <td>${dayTag(g.filedate, today, yesterday)}</td>
    <td class="ty-move ${cls}">${g.buy ? "▲ BUY" : "▼ SELL"}</td>
    <td class="ty-num ${cls}" style="font-weight:600">${fmtCompactUsd(g.total)}${cnt}</td>
    <td class="ty-role">${g.role ? escapeHtml(g.role) : "—"}</td>
    <td class="subtext">${g.traded ? escapeHtml(shortDate(g.traded)) : "—"}</td>
  </tr>`;
}

function tyTable(headCells, rows, emptyMsg, colspan) {
  const body = rows.length
    ? rows.join("")
    : `<tr><td colspan="${colspan}" class="ty-empty subtext">${emptyMsg}</td></tr>`;
  return `<table class="ty-table"><thead><tr>${headCells}</tr></thead><tbody>${body}</tbody></table>`;
}

export function renderTodayYesterday(watchlistData) {
  const today = etDateStr(Date.now());
  const yesterday = etDateStr(Date.now() - 864e5);
  const inWindow = d => d === today || d === yesterday;

  const nowMs = Date.now();
  const earnings = [];
  const groups = {};  // keyed by ticker+direction → aggregated insider activity
  for (const [ticker, d] of Object.entries(watchlistData || {})) {
    if (!d) continue;
    const name = d.snapshot?.name || "";
    const seenDates = new Set();
    for (const ev of (d.snapshot?.earnings_events || [])) {
      if (inWindow(ev.date)) { earnings.push({ ...ev, ticker, name }); seenDates.add(ev.date); }
    }
    // get_earnings_dates drops the upcoming row for a day around the report — backfill from the
    // stable quote-summary next-earnings datetime so a name reporting today doesn't vanish.
    const ne = d.snapshot?.next_earnings;
    if (ne) {
      const neDate = new Date(ne).toLocaleDateString("en-CA", { timeZone: "America/New_York" });
      if (inWindow(neDate) && !seenDates.has(neDate)) {
        // Backfill the actual from earnings_history, but only if its quarter-end sits ≤70 days
        // before the report — i.e. it's THIS report's quarter, not a stale prior one (yahoo lags
        // the newest quarter into earnings_history per-ticker; without the gate AAPL would show
        // last quarter's beat as today's).
        const lr = d.snapshot?.latest_earnings_result;
        let rep = null, est = d.snapshot?.next_earnings_eps_est ?? null, surp = null;
        if (lr && lr.quarter) {
          const gapDays = (new Date(ne) - new Date(lr.quarter)) / 864e5;
          if (gapDays >= 0 && gapDays <= 70) { rep = lr.eps_actual; est = lr.eps_estimate; surp = lr.surprise_pct; }
        }
        earnings.push({ ticker, name, date: neDate, datetime: ne, eps_estimate: est, reported_eps: rep, surprise_pct: surp });
      }
    }
    for (const tx of (d.insider_transactions || [])) {
      const filed = (tx.filing_date || "").slice(0, 10);
      if (!inWindow(filed)) continue;
      const buy = isBuy(tx.trade_type);
      const key = ticker + (buy ? "|B" : "|S");
      const g = groups[key] || (groups[key] = { ticker, name, buy, total: 0, count: 0, role: "", filedate: "", traded: "" });
      g.total += parseUsd(tx.Value || tx.value) || 0;
      g.count += 1;
      const r = canonRole(tx.title);
      if (r && roleRank(r) < roleRank(g.role)) g.role = r;  // keep only the most senior role
      if (filed > g.filedate) g.filedate = filed;
      if ((tx.trade_date || "") > g.traded) g.traded = tx.trade_date || "";
    }
  }
  const insiders = Object.values(groups);
  // today before yesterday
  earnings.sort((a, b) => a.date < b.date ? 1 : -1);
  insiders.sort((a, b) => a.filedate < b.filedate ? 1 : -1);

  const eHead = `<th>Ticker</th><th>When</th><th>Time</th><th>EPS</th><th class="ty-num">Est → Rep</th>`;
  const iHead = `<th>Ticker</th><th>When</th><th>Side</th><th class="ty-num">Value</th><th>Role</th><th>Traded</th>`;
  const eTable = tyTable(eHead, earnings.map(e => earningsRow(e, today, yesterday, nowMs)), "No earnings today or yesterday.", 5);
  const iTable = tyTable(iHead, insiders.map(g => insiderRow(g, today, yesterday)), "No insider trades today or yesterday.", 6);

  return `<section class="cat-section">
    <h2>Today &amp; Yesterday</h2>
    <div class="ty-stack">
      <div class="ty-col">
        <h3 class="ty-h3">Earnings <span class="subtext">${earnings.length || ""}</span></h3>
        <div class="ty-scroll">${eTable}</div>
      </div>
      <div class="ty-col">
        <h3 class="ty-h3">Insider activity <span class="subtext">${insiders.length || ""}</span></h3>
        <div class="ty-scroll">${iTable}</div>
      </div>
    </div>
  </section>`;
}
