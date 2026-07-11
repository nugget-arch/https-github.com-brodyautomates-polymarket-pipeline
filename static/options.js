/* Options Strategy Analyzer — frontend. Vanilla canvas charts, no dependencies. */
"use strict";

const FAMILIES = [
  { key: "long_call",         label: "Long Call",       color: "#3987e5" },
  { key: "long_put",          label: "Long Put",        color: "#199e70" },
  { key: "covered_call",      label: "Covered Call",    color: "#c98500" },
  { key: "csp",               label: "CSP",             color: "#008300" },
  { key: "debit_spread",      label: "Spread débito",   color: "#9085e9" },
  { key: "credit_spread",     label: "Spread crédito",  color: "#e66767" },
  { key: "straddle_strangle", label: "Straddle/Strangle", color: "#d55181" },
  { key: "iron_condor",       label: "Iron Condor",     color: "#d95926" },
];
const FAMILY_BY_KEY = Object.fromEntries(FAMILIES.map(f => [f.key, f]));

const INK = "#f2f2ef", INK2 = "#b9b8b0", MUTED = "#8a8983";
const GRID = "#26262b", BASELINE = "#38383f", SURFACE = "#16161a";
const GOOD = "#0ca30c", CRITICAL = "#d03b3b";
const DIV_POS = "#3987e5", DIV_NEG = "#e66767", DIV_MID = "#383835";

let DATA = null;          // last full payload.result
let selectedRow = null;   // currently charted strategy row

const $ = id => document.getElementById(id);
const fmt$ = v => v === null ? "∞" : (v < 0 ? "-$" : "$") + Math.abs(v).toFixed(2);
const fmtPct = (v, d = 1) => (v * 100).toFixed(d) + "%";

/* ---------------------------------------------------------------- tooltip */
const tooltip = $("tooltip");
function showTip(html, x, y) {
  tooltip.innerHTML = html;
  tooltip.style.display = "block";
  const r = tooltip.getBoundingClientRect();
  tooltip.style.left = Math.min(x + 14, window.innerWidth - r.width - 8) + "px";
  tooltip.style.top = Math.min(y + 14, window.innerHeight - r.height - 8) + "px";
}
function hideTip() { tooltip.style.display = "none"; }

/* ------------------------------------------------------------ canvas prep */
function prep(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w: rect.width, h: rect.height };
}

function axisText(ctx, size = 10) {
  ctx.fillStyle = MUTED;
  ctx.font = `${size}px ui-monospace, "SF Mono", Consolas, monospace`;
}

function niceTicks(lo, hi, n = 5) {
  const span = hi - lo || 1;
  const step0 = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => span / s <= n + 1) || mag * 10;
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(v);
  return ticks;
}

function percentile(sorted, p) {
  if (!sorted.length) return 0;
  const i = Math.min(sorted.length - 1, Math.max(0, Math.floor(p * (sorted.length - 1))));
  return sorted[i];
}

/* ---------------------------------------------------------------- filters */
function currentFilters() {
  return {
    ticker: $("f-ticker").value,
    family: $("f-family").value,
    minPop: parseInt($("f-pop").value, 10) / 100,
    sort: $("f-sort").value,
  };
}

function filterScatter() {
  const f = currentFilters();
  return DATA.scatter.filter(p =>
    (!f.ticker || p.ticker === f.ticker) &&
    (!f.family || p.family === f.family) &&
    p.pop >= f.minPop);
}

function filterTop() {
  const f = currentFilters();
  const rows = DATA.top_strategies.filter(r =>
    (!f.ticker || r.ticker === f.ticker) &&
    (!f.family || r.family === f.family) &&
    r.pop >= f.minPop);
  // null = unlimited (max profit of a long call), so it sorts first
  const v = r => r[f.sort] === null ? Infinity : (r[f.sort] ?? 0);
  rows.sort((a, b) => v(b) - v(a));
  return rows.slice(0, 60);
}

/* ------------------------------------------------------------- stat tiles */
function renderTiles() {
  const s = DATA.summary;
  const tiles = [
    { label: "Estrategias analizadas", value: DATA.total_strategies.toLocaleString("es"), detail: `en ${DATA.elapsed_seconds}s de escaneo` },
    { label: "Contratos reales", value: DATA.total_contracts.toLocaleString("es"), detail: `${DATA.tickers.length} subyacentes · CBOE` },
    { label: "% con EV positivo", value: fmtPct(s.pct_positive_ev), cls: s.pct_positive_ev >= 0.5 ? "pos" : "", detail: "tras coste del spread" },
    { label: "EV mediana", value: fmt$(s.median_ev), cls: s.median_ev >= 0 ? "pos" : "neg", detail: "por contrato" },
    { label: "POP media", value: fmtPct(s.mean_pop), detail: "probabilidad de beneficio" },
    { label: "Mejor estrategia", value: s.best.ticker, detail: `${s.best.name} · EV ${fmt$(s.best.ev)}` },
  ];
  $("tiles").innerHTML = tiles.map(t => `
    <div class="tile">
      <div class="t-label">${t.label}</div>
      <div class="t-value ${t.cls || ""}">${t.value}</div>
      <div class="t-detail">${t.detail}</div>
    </div>`).join("");
}

/* ---------------------------------------------------------------- scatter */
function renderScatter() {
  const { ctx, w, h } = prep($("scatter"));
  const pts = filterScatter();
  const pad = { l: 52, r: 14, t: 10, b: 30 };
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;

  const ys = pts.map(p => p.ev_pct).sort((a, b) => a - b);
  let yLo = Math.min(percentile(ys, 0.02), -0.1);
  let yHi = Math.max(percentile(ys, 0.98), 0.1);

  const X = p => pad.l + p.pop * iw;
  const Y = v => pad.t + (1 - (Math.min(Math.max(v, yLo), yHi) - yLo) / (yHi - yLo)) * ih;

  // grid + axes
  ctx.strokeStyle = GRID; ctx.lineWidth = 1;
  axisText(ctx);
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (const t of niceTicks(yLo, yHi, 5)) {
    ctx.beginPath(); ctx.moveTo(pad.l, Y(t)); ctx.lineTo(w - pad.r, Y(t)); ctx.stroke();
    ctx.fillText(fmtPct(t, 0), pad.l - 6, Y(t));
  }
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (const t of [0, 0.25, 0.5, 0.75, 1]) {
    ctx.beginPath(); ctx.moveTo(X({ pop: t }), pad.t); ctx.lineTo(X({ pop: t }), h - pad.b); ctx.stroke();
    ctx.fillText(fmtPct(t, 0), X({ pop: t }), h - pad.b + 6);
  }
  // zero line emphasized
  if (yLo < 0 && yHi > 0) {
    ctx.strokeStyle = BASELINE; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(pad.l, Y(0)); ctx.lineTo(w - pad.r, Y(0)); ctx.stroke();
  }
  axisText(ctx, 10);
  ctx.textAlign = "center";
  ctx.fillText("probabilidad de beneficio (POP)", pad.l + iw / 2, h - 12);
  ctx.save();
  ctx.translate(12, pad.t + ih / 2); ctx.rotate(-Math.PI / 2);
  ctx.fillText("retorno esperado / capital", 0, 0);
  ctx.restore();

  // points — skip the few beyond the percentile domain instead of smearing
  // them along the clamped edge
  const drawn = [];
  let clipped = 0;
  for (const p of pts) {
    if (p.ev_pct < yLo || p.ev_pct > yHi) { clipped++; continue; }
    const fam = FAMILY_BY_KEY[p.family];
    const x = X(p), y = Y(p.ev_pct);
    ctx.beginPath();
    ctx.fillStyle = fam.color + "cc";
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fill();
    drawn.push({ x, y, p });
  }
  if (clipped) {
    axisText(ctx);
    ctx.textAlign = "right"; ctx.textBaseline = "top";
    ctx.fillText(`${clipped} fuera de rango`, w - pad.r - 2, pad.t + 2);
  }

  const canvas = $("scatter");
  canvas.onmousemove = e => {
    const r = canvas.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    let best = null, bd = 144;
    for (const d of drawn) {
      const dd = (d.x - mx) ** 2 + (d.y - my) ** 2;
      if (dd < bd) { bd = dd; best = d; }
    }
    if (best) {
      const p = best.p, fam = FAMILY_BY_KEY[p.family];
      showTip(`<div class="tt-title">${p.ticker} · ${p.name}</div>
        <div class="tt-row">${fam.label} · ${p.dte} DTE</div>
        <div class="tt-row">POP <b>${fmtPct(p.pop)}</b> · EV <b>${fmt$(p.ev)}</b> · ROC <b>${fmtPct(p.ev_pct)}</b></div>`,
        e.clientX, e.clientY);
    } else hideTip();
  };
  canvas.onmouseleave = hideTip;

  // legend (direct-labeled, fixed order)
  $("scatter-legend").innerHTML = FAMILIES.map(f =>
    `<span class="l-item"><span class="l-chip" style="background:${f.color}"></span>${f.label}</span>`).join("");
}

/* ------------------------------------------------------------- histograms */
function renderHistogram(canvasId, hist, fmtX, barColor) {
  const { ctx, w, h } = prep($(canvasId));
  const pad = { l: 40, r: 10, t: 8, b: 22 };
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
  const counts = hist.counts, edges = hist.edges;
  const maxC = Math.max(...counts, 1);
  const bw = iw / counts.length;

  ctx.strokeStyle = GRID; ctx.lineWidth = 1;
  axisText(ctx);
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (const t of niceTicks(0, maxC, 3)) {
    const y = pad.t + (1 - t / maxC) * ih;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
    ctx.fillText(t.toLocaleString("es"), pad.l - 5, y);
  }

  const bars = [];
  for (let i = 0; i < counts.length; i++) {
    const bh = (counts[i] / maxC) * ih;
    const x = pad.l + i * bw + 1, y = pad.t + ih - bh;  // 2px gap between bars
    ctx.fillStyle = barColor;
    ctx.beginPath();
    ctx.roundRect(x, y, Math.max(bw - 2, 1), Math.max(bh, 0), [3, 3, 0, 0]);
    ctx.fill();
    bars.push({ x, w: bw - 2, i });
  }

  // baseline
  ctx.strokeStyle = BASELINE; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(pad.l, pad.t + ih); ctx.lineTo(w - pad.r, pad.t + ih); ctx.stroke();

  axisText(ctx);
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  const nLab = 5;
  for (let j = 0; j <= nLab; j++) {
    const i = Math.round(j * (edges.length - 1) / nLab);
    ctx.fillText(fmtX(edges[i]), pad.l + (i / counts.length) * iw, pad.t + ih + 5);
  }

  const canvas = $(canvasId);
  canvas.onmousemove = e => {
    const r = canvas.getBoundingClientRect();
    const mx = e.clientX - r.left;
    const i = Math.floor((mx - pad.l) / bw);
    if (i >= 0 && i < counts.length) {
      showTip(`<div class="tt-row"><b>${counts[i].toLocaleString("es")}</b> estrategias</div>
        <div class="tt-row">entre ${fmtX(edges[i])} y ${fmtX(edges[i + 1])}</div>`, e.clientX, e.clientY);
    } else hideTip();
  };
  canvas.onmouseleave = hideTip;
}

/* ---------------------------------------------------------------- heatmap */
function divergingColor(v, vmax) {
  if (v === null || v === undefined) return null;
  const t = Math.min(Math.abs(v) / vmax, 1);
  const pole = v >= 0 ? DIV_POS : DIV_NEG;
  const mix = (a, b, t2) => Math.round(a + (b - a) * t2);
  const pr = parseInt(pole.slice(1, 3), 16), pg = parseInt(pole.slice(3, 5), 16), pb = parseInt(pole.slice(5, 7), 16);
  const mr = 0x38, mg = 0x38, mb = 0x35; // neutral midpoint #383835
  return `rgb(${mix(mr, pr, t)},${mix(mg, pg, t)},${mix(mb, pb, t)})`;
}

function renderHeatmap() {
  const { ctx, w, h } = prep($("heatmap"));
  const hm = DATA.heatmap;
  const padL = 52, padT = 30, padB = 8, padR = 8;
  const iw = w - padL - padR, ih = h - padT - padB;
  const cw = iw / hm.families.length, ch = ih / hm.tickers.length;

  // scale poles to the 90th percentile of |v| so mid-range cells keep contrast
  const vals = hm.cells.flat().map(c => c.median_ev_pct).filter(v => v !== null);
  const absSorted = vals.map(Math.abs).sort((a, b) => a - b);
  const vmax = Math.max(percentile(absSorted, 0.9), 0.005);

  const SHORT = {
    long_call: "L.Call", long_put: "L.Put", covered_call: "C.Call", csp: "CSP",
    debit_spread: "Débito", credit_spread: "Crédito",
    straddle_strangle: "Strad.", iron_condor: "Condor",
  };
  axisText(ctx);
  ctx.textAlign = "center"; ctx.textBaseline = "bottom";
  hm.families.forEach((fam, j) => {
    ctx.fillText(SHORT[fam] || fam, padL + (j + 0.5) * cw, padT - 6);
  });
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  hm.tickers.forEach((t, i) => ctx.fillText(t, padL - 7, padT + (i + 0.5) * ch));

  const cells = [];
  hm.tickers.forEach((t, i) => {
    hm.families.forEach((fam, j) => {
      const cell = hm.cells[i][j];
      const color = divergingColor(cell.median_ev_pct, vmax);
      const x = padL + j * cw + 1, y = padT + i * ch + 1;
      ctx.fillStyle = color || "#1a1a1e";
      ctx.beginPath();
      ctx.roundRect(x, y, cw - 2, ch - 2, 3);  // 2px surface gap
      ctx.fill();
      cells.push({ x, y, w: cw - 2, h: ch - 2, ticker: t, fam, cell });
    });
  });

  const canvas = $("heatmap");
  canvas.onmousemove = e => {
    const r = canvas.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const c = cells.find(c => mx >= c.x && mx <= c.x + c.w && my >= c.y && my <= c.y + c.h);
    if (c) {
      const v = c.cell.median_ev_pct;
      showTip(`<div class="tt-title">${c.ticker} · ${FAMILY_BY_KEY[c.fam].label}</div>
        <div class="tt-row">Mediana ROC: <b>${v === null ? "sin datos" : fmtPct(v)}</b></div>
        <div class="tt-row"><b>${c.cell.count.toLocaleString("es")}</b> estrategias</div>`, e.clientX, e.clientY);
    } else hideTip();
  };
  canvas.onmouseleave = hideTip;
}

/* ----------------------------------------------------------------- payoff */
function payoffAt(row, S) {
  let pl = 0;
  for (const leg of row.payoff_legs) {
    const intrinsic = leg.kind === "C" ? Math.max(S - leg.strike, 0) : Math.max(leg.strike - S, 0);
    pl += leg.qty * (intrinsic - leg.mid);
  }
  if (row.family === "covered_call") pl += S - row.spot;
  return pl * 100;
}

function renderPayoff(row) {
  const { ctx, w, h } = prep($("payoff"));
  if (!row) {
    axisText(ctx, 12);
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText("Selecciona una estrategia del ranking →", w / 2, h / 2);
    $("payoff-meta").innerHTML = "";
    return;
  }

  const strikes = row.payoff_legs.map(l => l.strike);
  const lo = Math.min(...strikes, row.spot) * 0.82;
  const hi = Math.max(...strikes, row.spot) * 1.18;
  const N = 240;
  const xs = [], ys = [];
  for (let i = 0; i <= N; i++) {
    const S = lo + (hi - lo) * i / N;
    xs.push(S); ys.push(payoffAt(row, S));
  }
  let yLo = Math.min(...ys), yHi = Math.max(...ys);
  const span = (yHi - yLo) || 1; yLo -= span * 0.1; yHi += span * 0.1;

  const pad = { l: 58, r: 14, t: 12, b: 30 };
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
  const X = s => pad.l + (s - lo) / (hi - lo) * iw;
  const Y = v => pad.t + (1 - (v - yLo) / (yHi - yLo)) * ih;

  // grid
  ctx.strokeStyle = GRID; ctx.lineWidth = 1;
  axisText(ctx);
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (const t of niceTicks(yLo, yHi, 5)) {
    ctx.beginPath(); ctx.moveTo(pad.l, Y(t)); ctx.lineTo(w - pad.r, Y(t)); ctx.stroke();
    ctx.fillText(fmt$(t), pad.l - 6, Y(t));
  }
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (const t of niceTicks(lo, hi, 6)) {
    ctx.fillText("$" + t.toFixed(0), X(t), h - pad.b + 6);
  }

  // profit / loss fills against the zero line (status colors, 18% alpha)
  const y0 = Y(0);
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(X(xs[0]), y0);
  xs.forEach((s, i) => ctx.lineTo(X(s), Y(ys[i])));
  ctx.lineTo(X(xs[N]), y0);
  ctx.closePath();
  ctx.clip();
  ctx.fillStyle = GOOD + "2e";
  ctx.fillRect(pad.l, pad.t, iw, Math.max(y0 - pad.t, 0));
  ctx.fillStyle = CRITICAL + "2e";
  ctx.fillRect(pad.l, y0, iw, Math.max(pad.t + ih - y0, 0));
  ctx.restore();

  // zero baseline
  ctx.strokeStyle = BASELINE; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(pad.l, y0); ctx.lineTo(w - pad.r, y0); ctx.stroke();

  // payoff line
  ctx.strokeStyle = INK; ctx.lineWidth = 2;
  ctx.beginPath();
  xs.forEach((s, i) => i === 0 ? ctx.moveTo(X(s), Y(ys[i])) : ctx.lineTo(X(s), Y(ys[i])));
  ctx.stroke();

  // spot marker (dashed vertical)
  ctx.strokeStyle = MUTED; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(X(row.spot), pad.t); ctx.lineTo(X(row.spot), pad.t + ih); ctx.stroke();
  ctx.setLineDash([]);
  axisText(ctx);
  ctx.textAlign = "center"; ctx.textBaseline = "bottom";
  ctx.fillText(`spot $${row.spot}`, X(row.spot), pad.t + 10);

  // breakevens
  for (const be of row.breakevens || []) {
    if (be < lo || be > hi) continue;
    ctx.fillStyle = INK;
    ctx.beginPath(); ctx.arc(X(be), y0, 4.5, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = SURFACE; ctx.lineWidth = 2; ctx.stroke(); // 2px surface ring
    axisText(ctx);
    ctx.textAlign = "center"; ctx.textBaseline = "bottom";
    ctx.fillText("BE $" + be, X(be), y0 - 8);
  }

  // hover crosshair
  const canvas = $("payoff");
  canvas.onmousemove = e => {
    const r = canvas.getBoundingClientRect();
    const mx = e.clientX - r.left;
    if (mx < pad.l || mx > pad.l + iw) { hideTip(); return; }
    const S = lo + (mx - pad.l) / iw * (hi - lo);
    const pl = payoffAt(row, S);
    showTip(`<div class="tt-row">Precio al vencimiento: <b>$${S.toFixed(2)}</b></div>
      <div class="tt-row">P/L: <b style="color:${pl >= 0 ? GOOD : CRITICAL}">${fmt$(pl)}</b></div>`,
      e.clientX, e.clientY);
  };
  canvas.onmouseleave = hideTip;

  // title + meta
  const fam = FAMILY_BY_KEY[row.family];
  $("payoff-title").innerHTML = `Payoff — ${row.ticker} ${row.name} <span class="sub">${fam.label} · vence ${row.expiry} (${row.dte} DTE)</span>`;
  $("payoff-meta").innerHTML = `
    <span>EV <b>${fmt$(row.ev)}</b></span>
    <span>POP <b>${fmtPct(row.pop)}</b></span>
    <span>Máx beneficio <b>${fmt$(row.max_profit)}</b></span>
    <span>Máx pérdida <b>${fmt$(row.max_loss)}</b></span>
    <span>Capital <b>${fmt$(row.capital)}</b></span>
    <span>Δ <b>${row.delta}</b></span>
    <span>Θ <b>${row.theta}</b>/día</span>
    <span>Vega <b>${row.vega}</b></span>
    <span>Legs <b>${row.legs}</b></span>`;
}

/* ----------------------------------------------------------------- tables */
function renderFamilyTable() {
  const tbody = $("family-table").querySelector("tbody");
  tbody.innerHTML = DATA.family_stats.map(f => {
    const fam = FAMILY_BY_KEY[f.family];
    return `<tr>
      <td><span class="chip" style="background:${fam.color}"></span>${fam.label}</td>
      <td class="num">${f.count.toLocaleString("es")}</td>
      <td class="num ${f.median_ev >= 0 ? "pos" : "neg"}">${fmt$(f.median_ev)}</td>
      <td class="num">${fmtPct(f.mean_pop)}</td>
      <td class="num">${fmtPct(f.pct_positive_ev)}</td>
      <td class="num pos">${fmt$(f.best_ev)}</td>
    </tr>`;
  }).join("");
}

function renderTopTable() {
  const rows = filterTop();
  const tbody = $("top-table").querySelector("tbody");
  tbody.innerHTML = rows.map((r, i) => {
    const fam = FAMILY_BY_KEY[r.family];
    return `<tr data-i="${i}">
      <td><span class="chip" style="background:${fam.color}"></span>${r.name}</td>
      <td>${r.ticker}</td>
      <td class="num">${r.dte}d</td>
      <td class="num ${r.ev >= 0 ? "pos" : "neg"}">${fmt$(r.ev)}</td>
      <td class="num">${fmtPct(r.pop)}</td>
      <td class="num">${fmt$(r.max_profit)}</td>
      <td class="num">${fmt$(r.max_loss)}</td>
      <td class="num ${r.ev_pct >= 0 ? "pos" : "neg"}">${fmtPct(r.ev_pct)}</td>
    </tr>`;
  }).join("");
  $("filter-count").textContent =
    `${filterScatter().length.toLocaleString("es")} estrategias en gráfica · ${rows.length} en ranking`;

  tbody.querySelectorAll("tr").forEach(tr => {
    tr.addEventListener("click", () => {
      tbody.querySelectorAll("tr.selected").forEach(x => x.classList.remove("selected"));
      tr.classList.add("selected");
      selectedRow = rows[parseInt(tr.dataset.i, 10)];
      renderPayoff(selectedRow);
    });
  });

  // auto-select first row on fresh render if nothing selected
  if (!selectedRow && rows.length) {
    tbody.querySelector("tr").classList.add("selected");
    selectedRow = rows[0];
    renderPayoff(selectedRow);
  }
}

function renderTickerTable() {
  const tbody = $("ticker-table").querySelector("tbody");
  tbody.innerHTML = DATA.tickers.map(t => `<tr>
    <td>${t.ticker}</td>
    <td class="num">$${t.spot.toFixed(2)}</td>
    <td class="num">${t.iv30.toFixed(1)}%</td>
    <td class="num">${t.contracts.toLocaleString("es")}</td>
    <td class="num">${t.expirations}</td>
    <td class="num">${t.strategies.toLocaleString("es")}</td>
  </tr>`).join("");
}

/* ------------------------------------------------------------ page wiring */
function populateFilters() {
  const tickSel = $("f-ticker");
  tickSel.innerHTML = '<option value="">Todos</option>' +
    DATA.tickers.map(t => `<option value="${t.ticker}">${t.ticker}</option>`).join("");
  const famSel = $("f-family");
  famSel.innerHTML = '<option value="">Todas</option>' +
    FAMILIES.map(f => `<option value="${f.key}">${f.label}</option>`).join("");
}

function renderAll() {
  renderTiles();
  renderScatter();
  renderHistogram("ev-hist", DATA.ev_histogram, v => "$" + Math.round(v), "#3987e5");
  renderHistogram("pop-hist", DATA.pop_histogram, v => fmtPct(v, 0), "#199e70");
  renderHeatmap();
  renderFamilyTable();
  renderTopTable();
  renderTickerTable();
  if (selectedRow) renderPayoff(selectedRow);
}

function rerenderFiltered() {
  renderScatter();
  selectedRow = null;
  renderTopTable();
}

["f-ticker", "f-family", "f-sort"].forEach(id =>
  $(id).addEventListener("change", rerenderFiltered));
$("f-pop").addEventListener("input", () => {
  $("f-pop-val").textContent = $("f-pop").value + "%";
  rerenderFiltered();
});

let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (DATA) renderAll(); }, 150);
});

async function poll() {
  try {
    const resp = await fetch("/api/options");
    if (!resp.ok) return;
    const payload = await resp.json();
    const el = $("scan-status");
    el.textContent = payload.scanning
      ? "◌ " + payload.activity
      : (payload.result ? `● escaneo #${payload.scan_number} · ${payload.result.generated_at}` : payload.activity);

    if (payload.result && (!DATA || payload.result.generated_at !== DATA.generated_at)) {
      const isFirst = !DATA;
      DATA = payload.result;
      if (isFirst) populateFilters();
      selectedRow = null;
      renderAll();
    }
  } catch (err) {
    console.error("poll failed", err);
  }
}

poll();
setInterval(poll, 8000);
