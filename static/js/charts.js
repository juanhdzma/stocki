import { fmtShort, shortPeriod, fmtCompact, fmtPctSigned } from "./format.js";
import { positionTooltip, hideTooltip, showOverlay } from "./overlay.js";
import { state } from "./state.js";

export function miniGroupedChart(revVals, niVals, labels, width) {
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

export function priceTargetBar(price, low, mean, high, width, height) {
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

  const lX = sc(low).toFixed(1), hX = sc(high).toFixed(1), pX = sc(price).toFixed(1);
  const hasMean = mean != null;
  const mX = hasMean ? sc(mean).toFixed(1) : null;
  const meanMarker = hasMean
    ? `<line x1="${mX}" y1="${midY - 8}" x2="${mX}" y2="${midY + 8}" stroke="#d29922" stroke-width="2"/>
<text x="${mX}" y="${height - 1}" text-anchor="middle" fill="#d29922" font-size="10" font-family="monospace">${fmt(mean)}</text>`
    : "";

  return `<svg width="${width}" height="${height}" overflow="visible" style="display:block;height:${height}px;margin-bottom:12px" xmlns="http://www.w3.org/2000/svg">
<rect x="${lX}" y="${(midY - 3)}" width="${(sc(high) - sc(low)).toFixed(1)}" height="6" fill="#21262d" rx="3"/>
<line x1="${lX}" y1="${midY - 6}" x2="${lX}" y2="${midY + 6}" stroke="#484f58" stroke-width="1.5"/>
<line x1="${hX}" y1="${midY - 6}" x2="${hX}" y2="${midY + 6}" stroke="#484f58" stroke-width="1.5"/>
${meanMarker}
<circle cx="${pX}" cy="${midY}" r="5" fill="#58a6ff"/>
<text x="${pX}" y="${midY - 14}" text-anchor="middle" fill="#58a6ff" font-size="10" font-family="monospace" font-weight="600">${fmt(price)}</text>
<text x="${lX}" y="${height - 1}" text-anchor="start" fill="#8b949e" font-size="10" font-family="monospace">${fmt(low)}</text>
<text x="${hX}" y="${height - 1}" text-anchor="end" fill="#8b949e" font-size="10" font-family="monospace">${fmt(high)}</text>
</svg>`;
}

export function analystBar(sb, b, h, s, ss, width) {
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
${w >= 30 ? `<text x="${cx}" y="${barH + labelH}" text-anchor="middle" fill="${seg.color}" font-size="9" font-family="monospace">${seg.label}</text>` : (w < 18 ? `<text x="${cx}" y="${barH + labelH}" text-anchor="middle" fill="${seg.color}" font-size="9" font-family="monospace">${seg.n}</text>` : "")}`;
    x += w;
    return out;
  });
  return `<svg width="${width}" height="${height}" overflow="visible" style="display:block;height:${height}px" xmlns="http://www.w3.org/2000/svg">${parts.join("")}</svg>`;
}

// ── Trajectory charts (detail view) ────────────────────────────────────────────
export function svgUserX(event, svgEl, viewBoxW) {
  const rect = svgEl.getBoundingClientRect();
  const relX = event.clientX - rect.left;
  return Math.max(0, Math.min(viewBoxW, relX * (viewBoxW / rect.width)));
}

export function chartHoverEnd(id) {
  const cross = document.getElementById(`${id}-cross`);
  const dot   = document.getElementById(`${id}-dot`);
  if (cross) cross.style.display = "none";
  if (dot)   dot.style.display = "none";
  hideTooltip();
}

export function priceChartHover(event, id) {
  const reg = state.chartRegistry[id];
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

  showOverlay(event, `<div class="tt-head"><span class="tt-ticker">${p.date}</span></div><div style="padding:4px 2px;font-size:13px;font-weight:600">$${p.close.toFixed(2)}</div>`);
}

export function calendarTicks(points, mode) {
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

export function fmtTickDate(dateStr, mode) {
  const d = new Date(dateStr + "T00:00:00");
  if (mode === "month") return d.toLocaleDateString("en-US", { month: "short" });
  const [, m, day] = dateStr.split("-");
  return `${m}/${day}`;
}

export function comboFundamentalsSvg(periods, id) {
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

export function priceLineSvg(points, id, mode) {
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

  state.chartRegistry[id] = { points, padX: padXL, gap, plotTop, plotH, min, range, W, kind: "price" };

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

export function rangeBar(lo, hi, markers, loLabel, hiLabel) {
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

export function statColumn(label, valueHtml, extraClass = "") {
  return `<div class="stat-col ${extraClass}">
    ${valueHtml}
    <div class="range-title">${label}</div>
  </div>`;
}

export function changeVal(v) {
  const cls = v == null ? "s-null" : v >= 0 ? "s-green" : "s-red";
  return `<span class="poc-val ${cls}">${fmtPctSigned(v)}</span>`;
}

export function renderPriceOverview(snap, returns) {
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

export function renderPriceCharts(points, ticker) {
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
