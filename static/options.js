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

/* ------------------------------------------- analyst verdict + track record */
const BADGE = { ENTRAR: "badge-entrar", CAUTELA: "badge-cautela", EVITAR: "badge-evitar" };

function renderVerdicts() {
  const picks = (DATA.top_picks || []).filter(r => r.verdict);
  const box = $("verdict-cards");
  if (!picks.length) {
    box.innerHTML = `<p class="foot" style="border:none">Sin veredictos en este escaneo.</p>`;
    return;
  }
  const top = picks.slice(0, 4);
  box.innerHTML = top.map(r => {
    const fam = FAMILY_BY_KEY[r.family];
    return `<div class="verdict-card">
      <div class="v-head">
        <span class="badge ${BADGE[r.verdict]}">${r.verdict} · ${r.analyst_score}</span>
        <span><span class="chip" style="background:${fam.color}"></span>${r.ticker} ${r.name} · ${r.dte}d</span>
        <span style="margin-left:auto;color:var(--ink-2);font-weight:400">EV ${fmt$(r.ev_exec)} · POP ${fmtPct(r.pop_exec)}</span>
      </div>
      <ul class="v-reasons">${r.reasons.map(x => `<li>${x}</li>`).join("")}</ul>
    </div>`;
  }).join("");
}

function renderTrackRecord() {
  const tr = DATA.track_record;
  const tiles = $("track-tiles"), note = $("track-note");
  if (!tr || tr.error) {
    tiles.innerHTML = "";
    note.textContent = tr && tr.error ? `Historial no disponible: ${tr.error}` : "Historial no disponible.";
    return;
  }
  const items = [
    { label: "Picks registrados", value: tr.tracked.toLocaleString("es"), detail: `${tr.pending} esperando vencimiento` },
    { label: "Verificados", value: tr.verified.toLocaleString("es"), detail: "vencidos y comprobados" },
  ];
  if (tr.verified > 0) {
    items.push(
      { label: "POP prometida", value: fmtPct(tr.predicted_pop), detail: "media de los verificados" },
      { label: "Acierto real", value: fmtPct(tr.realized_winrate), cls: tr.realized_winrate >= tr.predicted_pop ? "pos" : "neg", detail: "lo que pasó de verdad" },
      { label: "EV prometido", value: fmt$(tr.predicted_ev), detail: "suma de los verificados" },
      { label: "P/L realizado", value: fmt$(tr.realized_pl), cls: tr.realized_pl >= 0 ? "pos" : "neg", detail: "al cierre real de Yahoo" },
    );
    note.textContent = "Si «acierto real» se mantiene cerca de «POP prometida» con volumen creciente, el motor está calibrado. Si no, desconfía de él.";
  } else {
    note.textContent = "Aún no hay picks vencidos que verificar — el historial se construye solo: cada escaneo registra sus picks y los comprueba contra el precio real de cierre cuando vencen.";
  }
  tiles.innerHTML = items.map(t => `
    <div class="tile" style="padding:10px 12px">
      <div class="t-label">${t.label}</div>
      <div class="t-value ${t.cls || ""}" style="font-size:19px">${t.value}</div>
      <div class="t-detail">${t.detail}</div>
    </div>`).join("");
}

/* ------------------------------------------------- top picks + portfolio */
function renderPicksTable() {
  const rows = DATA.top_picks || [];
  const tbody = $("picks-table").querySelector("tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="status-muted">Ninguna estrategia pasa el filtro de consistencia en este escaneo.</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map((r, i) => {
    const fam = FAMILY_BY_KEY[r.family];
    const badge = r.verdict
      ? `<span class="badge ${BADGE[r.verdict]}" title="${(r.reasons || []).join(' · ')}">${r.analyst_score}</span>`
      : "—";
    return `<tr data-i="${i}">
      <td>${badge}</td>
      <td><span class="chip" style="background:${fam.color}"></span>${r.name}</td>
      <td>${r.ticker}</td>
      <td class="num">${r.dte}d</td>
      <td class="num">${fmtPct(r.pop_exec)}</td>
      <td class="num pos">${fmt$(r.ev_exec)}</td>
      <td class="num">${fmt$(r.capital)}</td>
      <td class="num pos">${fmtPct(r.roc_annual_exec)}</td>
      <td class="num neg">${fmt$(r.cvar5)}</td>
      <td class="num neg">${fmt$(r.max_loss)}</td>
    </tr>`;
  }).join("");
  tbody.querySelectorAll("tr").forEach(tr => {
    tr.style.cursor = "pointer";
    tr.addEventListener("click", () => {
      selectedRow = rows[parseInt(tr.dataset.i, 10)];
      renderPayoff(selectedRow);
      document.querySelector("#payoff-title").scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });
}

function buildPortfolio() {
  const bankroll = Math.max(parseFloat($("bankroll").value) || 0, 0);
  const maxPosFrac = parseFloat($("max-pos").value);
  const maxPerPos = bankroll * maxPosFrac;
  const maxPerTicker = bankroll * Math.max(maxPosFrac, 0.25);

  const picks = DATA.top_picks || [];
  const positions = [];
  const tickerUsed = {};
  let used = 0;

  for (const r of picks) {
    if (r.capital > maxPerPos) continue;
    if ((tickerUsed[r.ticker] || 0) + r.capital > maxPerTicker) continue;
    if (used + r.capital > bankroll) continue;
    positions.push(r);
    tickerUsed[r.ticker] = (tickerUsed[r.ticker] || 0) + r.capital;
    used += r.capital;
    if (positions.length >= 12) break;
  }

  const totalEV = positions.reduce((a, r) => a + r.ev_exec, 0);
  const monthlyEV = positions.reduce((a, r) => a + r.ev_exec * 30.44 / r.dte, 0);
  const worstCase = positions.reduce((a, r) => a + r.max_loss, 0);
  const totalCvar = positions.reduce((a, r) => a + r.cvar5, 0);
  const avgPop = positions.length ? positions.reduce((a, r) => a + r.pop_exec, 0) / positions.length : 0;

  $("portfolio-summary").innerHTML = [
    { label: "Capital usado", value: fmt$(used), detail: `de ${fmt$(bankroll)}` },
    { label: "EV total", value: fmt$(totalEV), cls: totalEV >= 0 ? "pos" : "neg", detail: "al vencimiento (modelo)" },
    { label: "EV mensual", value: fmt$(monthlyEV), cls: "pos", detail: "normalizado a 30 días" },
    { label: "CVaR 5%", value: fmt$(totalCvar), cls: "neg", detail: "media del 5% peor, por posición" },
    { label: "Peor caso", value: fmt$(worstCase), cls: "neg", detail: "todas las posiciones en contra" },
    { label: "POP media", value: fmtPct(avgPop), detail: `${positions.length} posiciones` },
  ].map(t => `
    <div class="tile" style="padding:10px 12px">
      <div class="t-label">${t.label}</div>
      <div class="t-value ${t.cls || ""}" style="font-size:19px">${t.value}</div>
      <div class="t-detail">${t.detail}</div>
    </div>`).join("");

  const tbody = $("portfolio-table").querySelector("tbody");
  if (!positions.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="status-muted">Capital insuficiente para las oportunidades disponibles — sube el capital o el % por posición.</td></tr>`;
    return;
  }
  tbody.innerHTML = positions.map(r => {
    const fam = FAMILY_BY_KEY[r.family];
    return `<tr>
      <td><span class="chip" style="background:${fam.color}"></span>${r.name} · ${r.dte}d</td>
      <td>${r.ticker}</td>
      <td class="num">${fmtPct(r.pop_exec)}</td>
      <td class="num">${fmt$(r.capital)}</td>
      <td class="num pos">${fmt$(r.ev_exec)}</td>
      <td class="num neg">${fmt$(r.max_loss)}</td>
    </tr>`;
  }).join("");
}

/* ------------------------------------------------------------- smile chart */
function renderSmile() {
  const smiles = DATA.smiles || {};
  const sel = $("smile-ticker");
  const ticker = sel.value || Object.keys(smiles)[0];
  const { ctx, w, h } = prep($("smile"));
  const s = smiles[ticker];
  if (!s) {
    axisText(ctx, 12);
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText("Sin datos de sonrisa para este ticker", w / 2, h / 2);
    return;
  }

  const ks = s.points.map(p => p[0]), ivs = s.points.map(p => p[1]);
  const xLo = Math.min(...ks), xHi = Math.max(...ks);
  let yLo = Math.min(...ivs), yHi = Math.max(...ivs);
  const span = (yHi - yLo) || 1; yLo -= span * 0.12; yHi += span * 0.12;

  const pad = { l: 46, r: 14, t: 12, b: 30 };
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
  const X = k => pad.l + (k - xLo) / (xHi - xLo) * iw;
  const Y = v => pad.t + (1 - (v - yLo) / (yHi - yLo)) * ih;

  ctx.strokeStyle = GRID; ctx.lineWidth = 1;
  axisText(ctx);
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (const t of niceTicks(yLo, yHi, 5)) {
    ctx.beginPath(); ctx.moveTo(pad.l, Y(t)); ctx.lineTo(w - pad.r, Y(t)); ctx.stroke();
    ctx.fillText(t.toFixed(0) + "%", pad.l - 6, Y(t));
  }
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (const t of niceTicks(xLo, xHi, 6)) {
    ctx.fillText("$" + t.toFixed(0), X(t), h - pad.b + 6);
  }

  // spot marker
  ctx.strokeStyle = MUTED; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(X(s.spot), pad.t); ctx.lineTo(X(s.spot), pad.t + ih); ctx.stroke();
  ctx.setLineDash([]);
  axisText(ctx);
  ctx.textAlign = "center"; ctx.textBaseline = "bottom";
  ctx.fillText(`spot $${s.spot}`, X(s.spot), pad.t + 10);

  // smile line + markers (single series: puts OTM left, calls OTM right)
  ctx.strokeStyle = "#3987e5"; ctx.lineWidth = 2;
  ctx.beginPath();
  s.points.forEach((p, i) => i === 0 ? ctx.moveTo(X(p[0]), Y(p[1])) : ctx.lineTo(X(p[0]), Y(p[1])));
  ctx.stroke();
  for (const p of s.points) {
    ctx.fillStyle = "#3987e5";
    ctx.beginPath(); ctx.arc(X(p[0]), Y(p[1]), 3.5, 0, Math.PI * 2); ctx.fill();
  }
  axisText(ctx, 10);
  ctx.textAlign = "left"; ctx.textBaseline = "top";
  ctx.fillText(`${ticker} · vence ${s.expiry} (${s.dte} DTE) · IV por strike`, pad.l + 4, pad.t + 2);

  const canvas = $("smile");
  canvas.onmousemove = e => {
    const r = canvas.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    let best = null, bd = 200;
    for (const p of s.points) {
      const dd = (X(p[0]) - mx) ** 2 + (Y(p[1]) - my) ** 2;
      if (dd < bd) { bd = dd; best = p; }
    }
    if (best) {
      const side = best[0] <= s.spot ? "put OTM" : "call OTM";
      showTip(`<div class="tt-row">Strike <b>$${best[0]}</b> (${side})</div>
        <div class="tt-row">IV <b>${best[1].toFixed(1)}%</b></div>`, e.clientX, e.clientY);
    } else hideTip();
  };
  canvas.onmouseleave = hideTip;
}

/* ------------------------------------------------------- Monte Carlo sim */
function sampleTerminal(quantiles, u) {
  // quantiles: 101 prices at cumulative probs 0.005..0.995
  const x = u * (quantiles.length - 1);
  const i = Math.min(Math.floor(x), quantiles.length - 2);
  return quantiles[i] + (quantiles[i + 1] - quantiles[i]) * (x - i);
}

// standard normal CDF (Abramowitz-Stegun 7.1.26, |err| < 1.5e-7)
function normCdf(x) {
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return x >= 0 ? 0.5 * (1 + y) : 0.5 * (1 - y);
}

function randn() {
  // Box-Muller
  let u = 0, v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/**
 * Correlated uniforms per ticker via Gaussian copula with the real 1y
 * correlation matrix (Cholesky shipped by the server). Falls back to
 * independent draws when a ticker has no history.
 */
function drawCopula(tickersNeeded) {
  const corr = DATA.correlations;
  const out = {};
  if (!corr) {
    for (const t of tickersNeeded) out[t] = Math.random();
    return out;
  }
  const idx = corr.tickers;
  const z = idx.map(() => randn());
  for (const t of tickersNeeded) {
    const i = idx.indexOf(t);
    if (i < 0) { out[t] = Math.random(); continue; }
    let s = 0;
    for (let j = 0; j <= i; j++) s += corr.chol[i][j] * z[j];
    out[t] = normCdf(s);
  }
  return out;
}

function runSimulation() {
  const capital = Math.max(parseFloat($("sim-capital").value) || 0, 0);
  const ticker = $("sim-ticker").value;
  const nWanted = parseInt($("sim-n").value, 10);
  const dens = DATA.densities || {};

  // N best executable picks for the chosen underlying (or overall)
  const pool = (DATA.top_picks || []).filter(r =>
    (!ticker || r.ticker === ticker) && dens[r.ticker] && dens[r.ticker][r.expiry]);
  const picks = pool.slice(0, nWanted);
  if (!picks.length) {
    $("sim-note").textContent = "No hay oportunidades ejecutables para ese activo en este escaneo.";
    $("sim-summary").innerHTML = "";
    $("sim-table").querySelector("tbody").innerHTML = "";
    prep($("sim-hist"));
    return;
  }

  // equal-budget sizing: whole contracts only
  const budget = capital / picks.length;
  const positions = picks
    .map(r => ({ r, contracts: Math.floor(budget / Math.max(r.capital, 1)) }))
    .filter(p => p.contracts >= 1);
  const deployed = positions.reduce((a, p) => a + p.contracts * p.r.capital, 0);

  if (!positions.length) {
    $("sim-note").textContent = `Con ${fmt$(capital)} no cubres ni una posición (la más barata requiere ${fmt$(Math.min(...picks.map(r => r.capital)))}).`;
    $("sim-summary").innerHTML = "";
    $("sim-table").querySelector("tbody").innerHTML = "";
    prep($("sim-hist"));
    return;
  }

  // 10,000 trials; same-ticker positions share one uniform draw per trial
  // (comonotonic across expiries); across tickers, a Gaussian copula with
  // the real 1-year correlation matrix
  const TRIALS = 10000;
  const simTickers = [...new Set(positions.map(p => p.r.ticker))];
  const finals = new Float64Array(TRIALS);
  for (let t = 0; t < TRIALS; t++) {
    const uByTicker = drawCopula(simTickers);
    let pl = 0;
    for (const p of positions) {
      const S = sampleTerminal(dens[p.r.ticker][p.r.expiry], uByTicker[p.r.ticker]);
      pl += p.contracts * (payoffAt(p.r, S) - p.r.slippage);
    }
    finals[t] = capital + pl;
  }

  const sorted = Array.from(finals).sort((a, b) => a - b);
  const q = p => sorted[Math.min(Math.floor(p * TRIALS), TRIALS - 1)];
  const mean = sorted.reduce((a, v) => a + v, 0) / TRIALS;
  const probWin = sorted.filter(v => v > capital).length / TRIALS;

  $("sim-note").textContent = `${positions.length} posiciones · ${fmt$(deployed)} desplegados de ${fmt$(capital)}`;
  $("sim-summary").innerHTML = [
    { label: "Capital final medio", value: fmt$(mean), cls: mean >= capital ? "pos" : "neg", detail: `${((mean / capital - 1) * 100).toFixed(1)}% sobre inicial` },
    { label: "Mediana", value: fmt$(q(0.5)), cls: q(0.5) >= capital ? "pos" : "neg", detail: "escenario central" },
    { label: "Prob. de acabar en verde", value: fmtPct(probWin), cls: probWin >= 0.5 ? "pos" : "neg", detail: "capital final > inicial" },
    { label: "Percentil 5 (malo)", value: fmt$(q(0.05)), cls: "neg", detail: "1 de cada 20 veces peor" },
    { label: "Percentil 95 (bueno)", value: fmt$(q(0.95)), cls: "pos", detail: "1 de cada 20 veces mejor" },
    { label: "Peor / mejor de 10.000", value: `${fmt$(sorted[0])}`, cls: "neg", detail: `mejor: ${fmt$(sorted[TRIALS - 1])}` },
  ].map(t => `
    <div class="tile" style="padding:10px 12px">
      <div class="t-label">${t.label}</div>
      <div class="t-value ${t.cls || ""}" style="font-size:19px">${t.value}</div>
      <div class="t-detail">${t.detail}</div>
    </div>`).join("");

  // histogram of final capital, with the starting-capital marker
  const lo = q(0.005), hi = q(0.995);
  const BINS = 45;
  const counts = new Array(BINS).fill(0);
  for (const v of sorted) {
    const i = Math.min(Math.max(Math.floor((v - lo) / (hi - lo) * BINS), 0), BINS - 1);
    counts[i]++;
  }
  const { ctx, w, h } = prep($("sim-hist"));
  const pad = { l: 46, r: 12, t: 10, b: 28 };
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
  const maxC = Math.max(...counts, 1);
  const bw = iw / BINS;
  for (let i = 0; i < BINS; i++) {
    const bh = counts[i] / maxC * ih;
    const binLo = lo + (hi - lo) * i / BINS;
    ctx.fillStyle = binLo >= capital ? GOOD : CRITICAL;
    ctx.beginPath();
    ctx.roundRect(pad.l + i * bw + 1, pad.t + ih - bh, Math.max(bw - 2, 1), Math.max(bh, 0), [3, 3, 0, 0]);
    ctx.fill();
  }
  ctx.strokeStyle = BASELINE; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(pad.l, pad.t + ih); ctx.lineTo(w - pad.r, pad.t + ih); ctx.stroke();
  // starting-capital marker
  const xCap = pad.l + (capital - lo) / (hi - lo) * iw;
  if (xCap >= pad.l && xCap <= pad.l + iw) {
    ctx.strokeStyle = INK; ctx.lineWidth = 1.5; ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(xCap, pad.t); ctx.lineTo(xCap, pad.t + ih); ctx.stroke();
    ctx.setLineDash([]);
    axisText(ctx);
    ctx.textAlign = "center"; ctx.textBaseline = "bottom";
    ctx.fillText("inicial " + fmt$(capital), xCap, pad.t + 10);
  }
  axisText(ctx);
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (const t of niceTicks(lo, hi, 6)) ctx.fillText("$" + Math.round(t).toLocaleString("es"), pad.l + (t - lo) / (hi - lo) * iw, pad.t + ih + 5);

  const canvas = $("sim-hist");
  canvas.onmousemove = e => {
    const r = canvas.getBoundingClientRect();
    const i = Math.floor((e.clientX - r.left - pad.l) / bw);
    if (i >= 0 && i < BINS) {
      const bLo = lo + (hi - lo) * i / BINS, bHi = lo + (hi - lo) * (i + 1) / BINS;
      showTip(`<div class="tt-row"><b>${(counts[i] / TRIALS * 100).toFixed(1)}%</b> de escenarios</div>
        <div class="tt-row">acaban entre ${fmt$(bLo)} y ${fmt$(bHi)}</div>`, e.clientX, e.clientY);
    } else hideTip();
  };
  canvas.onmouseleave = hideTip;

  // positions table
  $("sim-table").querySelector("tbody").innerHTML = positions.map(p => {
    const fam = FAMILY_BY_KEY[p.r.family];
    return `<tr>
      <td><span class="chip" style="background:${fam.color}"></span>${p.r.ticker} ${p.r.name}</td>
      <td class="num">${p.r.dte}d</td>
      <td class="num">${p.contracts}</td>
      <td class="num">${fmt$(p.contracts * p.r.capital)}</td>
      <td class="num">${fmtPct(p.r.pop_exec)}</td>
      <td class="num pos">${fmt$(p.contracts * p.r.ev_exec)}</td>
    </tr>`;
  }).join("");
}

/* -------------------------------------------------------------- CSV export */
function exportCSV() {
  const rows = DATA.top_picks || [];
  const cols = ["ticker", "name", "family", "expiry", "dte", "legs", "pop_exec", "ev_exec",
                "capital", "roc_annual_exec", "cvar5", "max_loss", "slippage", "delta", "theta", "vega"];
  const esc = v => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const csv = [cols.join(",")]
    .concat(rows.map(r => cols.map(c => esc(r[c])).join(",")))
    .join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `top-picks-${(DATA.generated_at || "scan").slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
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
  const smileSel = $("smile-ticker");
  smileSel.innerHTML = Object.keys(DATA.smiles || {})
    .map(t => `<option value="${t}">${t}</option>`).join("");
  // simulator: only tickers that actually have executable picks
  const pickTickers = [...new Set((DATA.top_picks || []).map(r => r.ticker))];
  $("sim-ticker").innerHTML = '<option value="">Todos (correlaciones reales 1a)</option>' +
    pickTickers.map(t => `<option value="${t}">${t}</option>`).join("");
}

function renderAll() {
  renderTiles();
  renderVerdicts();
  renderTrackRecord();
  renderPicksTable();
  buildPortfolio();
  renderScatter();
  renderHistogram("ev-hist", DATA.ev_histogram, v => "$" + Math.round(v), "#3987e5");
  renderHistogram("pop-hist", DATA.pop_histogram, v => fmtPct(v, 0), "#199e70");
  renderHeatmap();
  renderFamilyTable();
  renderTopTable();
  renderTickerTable();
  renderSmile();
  if (selectedRow) renderPayoff(selectedRow);
}

function rerenderFiltered() {
  renderScatter();
  selectedRow = null;
  renderTopTable();
}

["f-ticker", "f-family", "f-sort"].forEach(id =>
  $(id).addEventListener("change", rerenderFiltered));
["bankroll", "max-pos"].forEach(id =>
  $(id).addEventListener("input", () => { if (DATA) buildPortfolio(); }));
$("smile-ticker").addEventListener("change", () => { if (DATA) renderSmile(); });
$("csv-btn").addEventListener("click", () => { if (DATA) exportCSV(); });
$("sim-btn").addEventListener("click", () => { if (DATA) runSimulation(); });
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
