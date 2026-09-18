/* Order-flow prototype — canvas renderer.
   Draws: volume profile (buy/sell) · value area · vPOC/VAH/VAL ·
   candles · per-candle delta bubbles. Click a candle for its real
   tick-level footprint. */

const $ = (id) => document.getElementById(id);
const canvas = $("chart");
const ctx = canvas.getContext("2d");

const state = {
  data: null,
  hover: -1,          // hovered candle index
  layout: null,       // computed geometry for hit-testing
  timer: null,
};

const COLORS = {
  bg: "#0a0d12",
  grid: "#161c25",
  axis: "#7d8794",
  up: "#26a65b",
  down: "#e0453e",
  wickUp: "#1f7d47",
  wickDown: "#a83530",
  buy: "#26a65b",
  sell: "#e0453e",
  poc: "#ff5a3c",
  va: "rgba(90,120,220,0.10)",
  vaLine: "rgba(120,150,240,0.55)",
};

const PROFILE_W = 150;   // px reserved for the left volume profile
const PAD = { top: 18, right: 66, bottom: 26, left: 8 };

// ---------------------------------------------------------------- data ----
async function load() {
  const symbol = $("symbol").value;
  const interval = $("interval").value;
  const candles = $("candles").value;
  $("status").textContent = "Cargando…";
  try {
    const r = await fetch(`/api/chart?symbol=${symbol}&interval=${interval}&candles=${candles}`);
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    state.data = d;
    $("hdr-symbol").textContent = `${symbol} · ${interval}`;
    updateStats(d);
    resize();
    $("status").textContent = "En vivo · " + new Date().toLocaleTimeString();
  } catch (e) {
    $("status").textContent = "Error: " + e.message;
  }
}

function fmt(n, d = 2) {
  return Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}
function signed(n, d = 2) {
  return (n >= 0 ? "+" : "") + fmt(n, d);
}

function updateStats(d) {
  $("s-last").textContent = fmt(d.lastPrice);
  const de = $("s-delta");
  de.textContent = signed(d.cumDelta);
  de.className = d.cumDelta >= 0 ? "pos" : "neg";
  $("s-vpoc").textContent = fmt(d.vpoc);
  $("s-vah").textContent = fmt(d.vah);
  $("s-val").textContent = fmt(d.val);
  $("s-vol").textContent = fmt(d.totalVol, 1);
}

// ------------------------------------------------------------- geometry ----
function resize() {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  draw();
}

function computeLayout(d, w, h) {
  const plotL = PAD.left + PROFILE_W;
  const plotR = w - PAD.right;
  const plotT = PAD.top;
  const plotB = h - PAD.bottom;
  const lo = d.priceLow, hi = d.priceHigh;
  const range = hi - lo || 1;

  const y = (p) => plotB - ((p - lo) / range) * (plotB - plotT);
  const n = d.candles.length;
  const cw = (plotR - plotL) / n;          // per-candle column width
  const x = (i) => plotL + cw * (i + 0.5); // candle centre x

  return { plotL, plotR, plotT, plotB, lo, hi, range, y, x, cw, n };
}

// ---------------------------------------------------------------- draw ----
function draw() {
  const d = state.data;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = COLORS.bg;
  ctx.fillRect(0, 0, w, h);
  if (!d || !d.candles.length) return;

  const L = computeLayout(d, w, h);
  state.layout = L;

  drawValueArea(d, L);
  drawGrid(d, L);
  drawProfile(d, L);
  drawLevels(d, L);
  drawCandles(d, L);
  drawBubbles(d, L);
  drawAxes(d, L);
}

function drawValueArea(d, L) {
  const yH = L.y(d.vah), yL = L.y(d.val);
  ctx.fillStyle = COLORS.va;
  ctx.fillRect(L.plotL, yH, L.plotR - L.plotL, yL - yH);
}

function drawGrid(d, L) {
  ctx.strokeStyle = COLORS.grid;
  ctx.lineWidth = 1;
  ctx.fillStyle = COLORS.axis;
  ctx.font = "10px ui-monospace, monospace";
  ctx.textAlign = "left";
  const ticks = 6;
  for (let i = 0; i <= ticks; i++) {
    const p = L.lo + (L.range * i) / ticks;
    const yy = Math.round(L.y(p)) + 0.5;
    ctx.beginPath();
    ctx.moveTo(L.plotL, yy);
    ctx.lineTo(L.plotR, yy);
    ctx.stroke();
    ctx.fillText(fmt(p, 1), L.plotR + 6, yy + 3);
  }
}

function drawProfile(d, L) {
  const maxVol = Math.max(...d.profile.map((p) => p.vol)) || 1;
  const bh = (L.plotB - L.plotT) / d.profile.length;
  d.profile.forEach((p) => {
    const yy = L.y(p.price) - bh / 2;
    const buyW = (p.buy / maxVol) * PROFILE_W;
    const sellW = (p.sell / maxVol) * PROFILE_W;
    const isPoc = Math.abs(p.price - d.vpoc) < (L.range / d.profile.length);
    // grow bars leftward from the plot's left edge
    ctx.fillStyle = isPoc ? COLORS.poc : COLORS.buy;
    ctx.globalAlpha = isPoc ? 0.9 : 0.55;
    ctx.fillRect(L.plotL - buyW, yy + 0.5, buyW, bh - 1);
    ctx.fillStyle = isPoc ? COLORS.poc : COLORS.sell;
    ctx.fillRect(L.plotL - buyW - sellW, yy + 0.5, sellW, bh - 1);
    ctx.globalAlpha = 1;
  });
  // divider between profile and candles
  ctx.strokeStyle = COLORS.grid;
  ctx.beginPath();
  ctx.moveTo(L.plotL + 0.5, L.plotT);
  ctx.lineTo(L.plotL + 0.5, L.plotB);
  ctx.stroke();
}

function levelLine(L, price, color, label, dashed) {
  const yy = Math.round(L.y(price)) + 0.5;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.setLineDash(dashed ? [5, 4] : []);
  ctx.beginPath();
  ctx.moveTo(L.plotL, yy);
  ctx.lineTo(L.plotR, yy);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = color;
  ctx.font = "10px ui-monospace, monospace";
  ctx.textAlign = "left";
  ctx.fillText(label, L.plotL + 4, yy - 3);
}

function drawLevels(d, L) {
  levelLine(L, d.vah, COLORS.vaLine, "VAH", true);
  levelLine(L, d.val, COLORS.vaLine, "VAL", true);
  levelLine(L, d.vpoc, COLORS.poc, "vPOC", false);
}

function drawCandles(d, L) {
  const bodyW = Math.max(1, Math.min(14, L.cw * 0.62));
  d.candles.forEach((c, i) => {
    const xc = L.x(i);
    const up = c.c >= c.o;
    const yO = L.y(c.o), yC = L.y(c.c), yH = L.y(c.h), yL = L.y(c.l);
    ctx.strokeStyle = up ? COLORS.wickUp : COLORS.wickDown;
    ctx.beginPath();
    ctx.moveTo(xc, yH);
    ctx.lineTo(xc, yL);
    ctx.stroke();
    ctx.fillStyle = up ? COLORS.up : COLORS.down;
    const top = Math.min(yO, yC);
    const hgt = Math.max(1, Math.abs(yC - yO));
    ctx.fillRect(xc - bodyW / 2, top, bodyW, hgt);
    if (i === state.hover) {
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 1;
      ctx.strokeRect(xc - bodyW / 2 - 1, top - 1, bodyW + 2, hgt + 2);
    }
  });
}

function drawBubbles(d, L) {
  const maxAbs = Math.max(...d.candles.map((c) => Math.abs(c.delta))) || 1;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  d.candles.forEach((c, i) => {
    if (c.delta === 0) return;
    const xc = L.x(i);
    const yc = L.y(c.c);
    const mag = Math.abs(c.delta) / maxAbs;
    const r = 5 + mag * 15;                 // radius scaled by |delta|
    ctx.beginPath();
    ctx.fillStyle = c.delta >= 0 ? COLORS.buy : COLORS.sell;
    ctx.globalAlpha = 0.92;
    ctx.arc(xc, yc, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
    if (r >= 9) {                            // label only when it fits
      ctx.fillStyle = "#ffffff";
      ctx.font = `bold ${Math.min(11, r * 0.9)}px ui-monospace, monospace`;
      const txt = Math.abs(c.delta) >= 10 ? Math.round(c.delta).toString() : c.delta.toFixed(1);
      ctx.fillText(txt.replace("-", ""), xc, yc + 0.5);
    }
  });
  ctx.textBaseline = "alphabetic";
}

function drawAxes(d, L) {
  ctx.fillStyle = COLORS.axis;
  ctx.font = "10px ui-monospace, monospace";
  ctx.textAlign = "center";
  const step = Math.ceil(L.n / 8);
  d.candles.forEach((c, i) => {
    if (i % step !== 0) return;
    const t = new Date(c.t);
    const hh = String(t.getHours()).padStart(2, "0");
    const mm = String(t.getMinutes()).padStart(2, "0");
    ctx.fillText(`${hh}:${mm}`, L.x(i), L.plotB + 15);
  });
}

// -------------------------------------------------------- interaction ----
function candleAt(px) {
  const L = state.layout;
  if (!L) return -1;
  if (px < L.plotL || px > L.plotR) return -1;
  const i = Math.floor((px - L.plotL) / L.cw);
  return i >= 0 && i < L.n ? i : -1;
}

canvas.addEventListener("mousemove", (e) => {
  const rect = canvas.getBoundingClientRect();
  const px = e.clientX - rect.left, py = e.clientY - rect.top;
  const i = candleAt(px);
  if (i !== state.hover) { state.hover = i; draw(); }
  const tip = $("tooltip");
  if (i < 0) { tip.classList.add("hidden"); return; }
  const c = state.data.candles[i];
  const t = new Date(c.t).toLocaleTimeString();
  tip.innerHTML =
    `<div class="row"><span>${t}</span></div>` +
    `<div class="row"><span>O</span>${fmt(c.o)}</div>` +
    `<div class="row"><span>H</span>${fmt(c.h)}</div>` +
    `<div class="row"><span>L</span>${fmt(c.l)}</div>` +
    `<div class="row"><span>C</span>${fmt(c.c)}</div>` +
    `<div class="row"><span>Vol</span>${fmt(c.v, 2)}</div>` +
    `<div class="row"><span>Δ</span><b class="${c.delta >= 0 ? "pos" : "neg"}">${signed(c.delta)}</b></div>`;
  tip.classList.remove("hidden");
  const tw = tip.offsetWidth;
  tip.style.left = Math.min(px + 14, canvas.clientWidth - tw - 8) + "px";
  tip.style.top = Math.max(py - 10, 8) + "px";
});
canvas.addEventListener("mouseleave", () => {
  state.hover = -1; $("tooltip").classList.add("hidden"); draw();
});

canvas.addEventListener("click", async (e) => {
  const rect = canvas.getBoundingClientRect();
  const i = candleAt(e.clientX - rect.left);
  if (i < 0) return;
  const c = state.data.candles[i];
  await showFootprint(c);
});

async function showFootprint(c) {
  const panel = $("fp");
  panel.classList.remove("hidden");
  $("fp-title").textContent = "Footprint · " + new Date(c.t).toLocaleTimeString();
  $("fp-meta").innerHTML = "Cargando trades…";
  $("fp-rows").innerHTML = "";
  const symbol = $("symbol").value, interval = $("interval").value;
  try {
    const r = await fetch(`/api/footprint?symbol=${symbol}&openTime=${c.t}&interval=${interval}`);
    const fp = await r.json();
    if (fp.error) throw new Error(fp.error);
    $("fp-meta").innerHTML =
      `<b>${fp.trades}</b> trades · Buy <b class="pos">${fmt(fp.buy, 2)}</b> · ` +
      `Sell <b class="neg">${fmt(fp.sell, 2)}</b> · Δ ` +
      `<b class="${fp.delta >= 0 ? "pos" : "neg"}">${signed(fp.delta, 2)}</b>`;
    const maxV = Math.max(1, ...fp.rows.map((x) => Math.max(x.buy, x.sell)));
    $("fp-rows").innerHTML = fp.rows.map((x) => {
      const bw = (x.buy / maxV) * 100, sw = (x.sell / maxV) * 100;
      return `<div class="fp-row">
        <div class="price">${fmt(x.price, 1)}</div>
        <div class="fp-bar b" style="width:${bw}%">${x.buy ? `<span>${fmt(x.buy, 2)}</span>` : ""}</div>
        <div class="fp-bar s" style="width:${sw}%">${x.sell ? `<span>${fmt(x.sell, 2)}</span>` : ""}</div>
      </div>`;
    }).join("") || "<p class='fp-note'>Sin trades en esta vela.</p>";
  } catch (e) {
    $("fp-meta").innerHTML = "Error: " + e.message;
  }
}

// ------------------------------------------------------------- wiring ----
$("fp-close").addEventListener("click", () => $("fp").classList.add("hidden"));
$("refresh").addEventListener("click", load);
["symbol", "interval", "candles"].forEach((id) => $(id).addEventListener("change", load));
$("auto").addEventListener("change", (e) => {
  clearInterval(state.timer);
  if (e.target.checked) state.timer = setInterval(load, 5000);
});
window.addEventListener("resize", resize);

load();
