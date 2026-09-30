// Minimal SVG charts following the dataviz method: thin marks (≤24 px bars, 4 px rounded data-end,
// square at the baseline), 2 px lines with a 10 % area wash, hairline recessive grid, selective
// direct labels, legend for ≥2 series, and a hover tooltip on every mark.
import { esc } from "./core.js";

const tip = () => document.getElementById("tip");
function showTip(ev, html) {
  const t = tip();
  t.innerHTML = html;
  t.classList.add("on");
  const pad = 14, r = t.getBoundingClientRect();
  let x = ev.clientX + pad, y = ev.clientY - r.height - pad;
  if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - pad;
  if (y < 8) y = ev.clientY + pad;
  t.style.left = `${x}px`;
  t.style.top = `${y}px`;
}
const hideTip = () => tip().classList.remove("on");

function niceMax(v) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v))), n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
}
const fmt = (v, d = 1) => (Math.abs(v) >= 100 ? Math.round(v) : +v.toFixed(d)).toLocaleString();

// vertical bar with rounded top only
function colPath(x, y, w, h, r = 4) {
  if (h <= 0) return "";
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}
// horizontal bar with rounded right end only
function barPath(x, y, w, h, r = 4) {
  if (w <= 0) return "";
  r = Math.min(r, h / 2, w);
  return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
}

function wire(el) {
  el.querySelectorAll("[data-tip]").forEach((n) => {
    n.addEventListener("pointermove", (e) => {
      el.querySelectorAll(".bar").forEach((b) => b.classList.toggle("hl", b.dataset.k === n.dataset.k));
      showTip(e, n.dataset.tip);
    });
    n.addEventListener("pointerleave", () => { hideTip(); el.querySelectorAll(".bar.hl").forEach((b) => b.classList.remove("hl")); });
  });
}

/** Single-series column chart (e.g. minutes captioned per day). */
export function columns(el, data, { unit = "", color = "var(--series-1)", height = 150, labelEvery = 2 } = {}) {
  const W = Math.max(280, el.clientWidth || 520), H = height, top = 18, bottom = 22, left = 30;
  const max = niceMax(Math.max(...data.map((d) => d.value), 0.0001));
  const slot = (W - left) / data.length, bw = Math.min(24, slot * 0.62);
  const y = (v) => top + (H - top - bottom) * (1 - v / max);
  const grid = [0, 0.5, 1].map((k) => `<line x1="${left}" x2="${W}" y1="${y(max * k)}" y2="${y(max * k)}"/>`
    ).join("") + [0.5, 1].map((k) => `<text class="axis" x="${left - 6}" y="${y(max * k) + 4}" text-anchor="end">${fmt(max * k, max < 1 ? 2 : max < 10 ? 1 : 0)}</text>`).join("");
  const iMax = data.reduce((b, d, i) => (d.value > data[b].value ? i : b), 0);
  const bars = data.map((d, i) => {
    const x = left + slot * i + (slot - bw) / 2, yy = y(d.value), h = H - bottom - yy;
    const label = (i === iMax && d.value > 0) || (i === data.length - 1 && d.value > 0)
      ? `<text class="val" x="${x + bw / 2}" y="${yy - 5}" text-anchor="middle">${fmt(d.value)}</text>` : "";
    const tipHtml = `<b>${esc(d.tip || d.label)}</b><br>${fmt(d.value)} ${esc(unit)}`;
    return `<path class="bar" data-k="${i}" d="${colPath(x, yy, bw, Math.max(h, d.value > 0 ? 2 : 0))}" fill="${color}"/>${label}
      ${i % labelEvery === (data.length - 1) % labelEvery ? `<text class="axis" x="${x + bw / 2}" y="${H - 5}" text-anchor="middle">${esc(d.label)}</text>` : ""}
      <rect class="hit" data-k="${i}" data-tip="${esc(tipHtml)}" x="${left + slot * i}" y="${top - 10}" width="${slot}" height="${H - top}"/>`;
  }).join("");
  el.innerHTML = `<div class="chart"><svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="${esc(el.dataset.label || "Column chart")}">
    <g class="grid">${grid}</g><line x1="${left}" x2="${W}" y1="${H - bottom}" y2="${H - bottom}" stroke="rgba(255,255,255,.18)"/>${bars}</svg></div>`;
  wire(el);
}

/** Grouped horizontal bars — rows × series (e.g. latency per model on X Elite vs X2 Elite). */
export function groupedBars(el, rows, series, { unit = "ms", labelW = 170 } = {}) {
  const W = Math.max(320, el.clientWidth || 600), bh = 12, gap = 2, rowGap = 14, top = 6;
  const rowH = series.length * bh + (series.length - 1) * gap;
  const H = top + rows.length * (rowH + rowGap);
  const max = niceMax(Math.max(...rows.flatMap((r) => r.values.filter((v) => v != null))));
  const plotW = W - labelW - 56, x = (v) => labelW + (plotW * v) / max;
  const grid = [0, 0.25, 0.5, 0.75, 1].map((k) => `<line x1="${x(max * k)}" x2="${x(max * k)}" y1="0" y2="${H - rowGap}"/>`).join("");
  const body = rows.map((r, i) => {
    const y0 = top + i * (rowH + rowGap);
    const bars = r.values.map((v, j) => {
      if (v == null) return "";
      const y = y0 + j * (bh + gap), w = x(v) - labelW;
      const t = `<b>${esc(r.label)}</b><br>${esc(series[j].name)}: ${fmt(v)} ${esc(unit)}${r.note ? `<br><span style="opacity:.7">${esc(r.note)}</span>` : ""}`;
      return `<path class="bar" data-k="${i}-${j}" d="${barPath(labelW, y, Math.max(w, 2), bh)}" fill="${series[j].color}"/>
        <text class="val" x="${labelW + w + 6}" y="${y + bh - 2}">${fmt(v)}</text>
        <rect class="hit" data-k="${i}-${j}" data-tip="${esc(t)}" x="${labelW}" y="${y - 1}" width="${plotW + 40}" height="${bh + 2}"/>`;
    }).join("");
    return `<text class="lbl" x="${labelW - 12}" y="${y0 + rowH / 2 + 4}" text-anchor="end">${esc(r.label)}</text>${bars}`;
  }).join("");
  el.innerHTML = `<div class="legend">${series.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join("")}<span class="muted" style="margin-left:auto">${esc(unit)} · lower is better</span></div>
    <div class="chart"><svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="${esc(el.dataset.label || "Bar chart")}"><g class="grid">${grid}</g>
    <line x1="${labelW}" x2="${labelW}" y1="0" y2="${H - rowGap}" stroke="rgba(255,255,255,.18)"/>${body}</svg></div>`;
  wire(el);
}

/** Sparkline with area wash, end dot + crosshair tooltip. */
export function spark(el, values, { color = "var(--series-1)", unit = "ms", height = 46, label = "" } = {}) {
  const W = Math.max(120, el.clientWidth || 240), H = height, pad = 5;
  if (!values || values.length < 2) {
    el.innerHTML = `<div class="muted" style="font-size:12px;height:${H}px;display:grid;place-items:center">Waiting for data…</div>`;
    return;
  }
  const max = Math.max(...values) * 1.15 || 1, min = 0;
  const x = (i) => pad + ((W - 2 * pad) * i) / (values.length - 1);
  const y = (v) => pad + (H - 2 * pad) * (1 - (v - min) / (max - min));
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  const last = values.length - 1;
  el.innerHTML = `<div class="chart spark"><svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="${esc(label)}">
    <path d="M${pts[0]}L${pts.join("L")}L${x(last)},${H - pad}L${x(0)},${H - pad}Z" fill="${color}" opacity=".12"/>
    <polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    <line class="xh" x1="0" x2="0" y1="${pad}" y2="${H - pad}" stroke="rgba(255,255,255,.25)" style="display:none"/>
    <circle cx="${x(last)}" cy="${y(values[last])}" r="4" fill="${color}" stroke="#12162b" stroke-width="2"/>
    <rect class="hit" x="0" y="0" width="${W}" height="${H}"/></svg></div>`;
  const svg = el.querySelector("svg"), xh = el.querySelector(".xh");
  svg.addEventListener("pointermove", (e) => {
    const r = svg.getBoundingClientRect();
    const i = Math.max(0, Math.min(last, Math.round(((e.clientX - r.left) / r.width * W - pad) / ((W - 2 * pad) / last))));
    xh.setAttribute("x1", x(i)); xh.setAttribute("x2", x(i)); xh.style.display = "";
    showTip(e, `<b>${esc(label || "Value")}</b><br>#${i + 1}: ${fmt(values[i])} ${esc(unit)}`);
  });
  svg.addEventListener("pointerleave", () => { xh.style.display = "none"; hideTip(); });
}
