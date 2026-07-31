// ── Source URLs ───────────────────────────────────────────────────────────────
export const INSIDER_SOURCE = t => `https://openinsider.com/screener?s=${t}`;

// ── Format helpers ────────────────────────────────────────────────────────────
export function srcLink(url) {
  if (!url) return "";
  return ` <a href="${url}" target="_blank" rel="noopener" class="src-link">↗</a>`;
}

export function timeAgo(isoStr) {
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

export function shortPeriod(p) {
  if (!p) return "";
  const qm = p.match(/Q\d/);
  if (qm) return qm[0];
  return String(p).slice(-4);
}

// ── SVG mini charts ───────────────────────────────────────────────────────────
export function fmtShort(v) {
  if (v === null || v === undefined) return "";
  const n = Number(v), abs = Math.abs(n), sign = n < 0 ? "-" : "";
  if (abs >= 1e9) return sign + (abs / 1e9).toFixed(1) + "B";
  if (abs >= 1e6) return sign + (abs / 1e6).toFixed(0) + "M";
  if (abs >= 1e3) return sign + (abs / 1e3).toFixed(0) + "K";
  return n.toFixed(0);
}

export function fmtCompact(n) {
  if (n == null) return "—";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(0)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(0)}K`;
  return `${sign}${abs.toFixed(0)}`;
}

export function fmtPctSigned(v) { return v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`; }
export function fmtPctLevel(v)  { return v == null ? "—" : `${(v * 100).toFixed(1)}%`; }

export function shortQLabel(period) {
  const m = /^(\d{4})-Q(\d)$/.exec(period);
  return m ? `Q${m[2]} '${m[1].slice(2)}` : period;
}

export function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
