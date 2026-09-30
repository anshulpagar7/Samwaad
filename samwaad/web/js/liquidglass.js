// Liquid Glass — real edge refraction for glass panels.
//
// Technique (after kube.io's "Liquid Glass in the Browser"): for every panel we render a
// displacement map of a rounded-rect "lens" whose bezel bends the backdrop inward like a
// convex glass edge. R = x-offset, G = y-offset, 128 = no shift. It's fed to an SVG
// <feDisplacementMap> and applied with `backdrop-filter: url(#id)`. Only Chromium (Edge,
// Chrome) supports SVG backdrop filters, so other browsers keep the frosted fallback in CSS.

const NS = "http://www.w3.org/2000/svg";
const supported = (() => {
  if (new URLSearchParams(location.search).has("nolg")) return false;
  const brands = navigator.userAgentData?.brands?.map((b) => b.brand).join(" ") || "";
  return /Chromium|Google Chrome|Microsoft Edge/.test(brands) || /Chrome\/\d+/.test(navigator.userAgent);
})();

let defs, seq = 0;
function ensureDefs() {
  if (defs) return defs;
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("width", "0");
  svg.setAttribute("height", "0");
  svg.style.cssText = "position:absolute;width:0;height:0;pointer-events:none";
  svg.setAttribute("aria-hidden", "true");
  defs = document.createElementNS(NS, "defs");
  svg.appendChild(defs);
  document.body.appendChild(svg);
  return defs;
}

// Signed distance to a rounded rectangle centred at the origin (negative inside).
function sdRoundRect(px, py, hx, hy, r) {
  const qx = Math.abs(px) - (hx - r), qy = Math.abs(py) - (hy - r);
  const ox = Math.max(qx, 0), oy = Math.max(qy, 0);
  return Math.hypot(ox, oy) + Math.min(Math.max(qx, qy), 0) - r;
}

function displacementMap(w, h, radius, bezel) {
  const s = Math.min(1, 420 / Math.max(w, h));           // render small, the filter upsamples smoothly
  const cw = Math.max(8, Math.round(w * s)), ch = Math.max(8, Math.round(h * s));
  const canvas = document.createElement("canvas");
  canvas.width = cw; canvas.height = ch;
  const ctx = canvas.getContext("2d");
  const img = ctx.createImageData(cw, ch);
  const hx = w / 2, hy = h / 2, r = Math.min(radius, hx, hy), e = 0.75;
  for (let y = 0; y < ch; y++) {
    for (let x = 0; x < cw; x++) {
      const px = (x + 0.5) / s - hx, py = (y + 0.5) / s - hy;
      const d = -sdRoundRect(px, py, hx, hy, r);           // distance inside the edge (px)
      let dx = 0, dy = 0;
      if (d > 0 && d < bezel) {
        // outward normal from the SDF gradient
        let nx = sdRoundRect(px + e, py, hx, hy, r) - sdRoundRect(px - e, py, hx, hy, r);
        let ny = sdRoundRect(px, py + e, hx, hy, r) - sdRoundRect(px, py - e, hx, hy, r);
        const len = Math.hypot(nx, ny) || 1;
        nx /= len; ny /= len;
        const t = 1 - d / bezel;                            // 1 at the rim → 0 at the inner edge of the bezel
        const mag = t * t * (3 - 2 * t);                    // smooth convex lens profile
        dx = -nx * mag; dy = -ny * mag;                     // sample inward → magnified, bent edge
      }
      const i = (y * cw + x) * 4;
      img.data[i] = 128 + dx * 127;
      img.data[i + 1] = 128 + dy * 127;
      img.data[i + 2] = 128;
      img.data[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  return canvas.toDataURL();
}

function el(tag, attrs) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}

function build(node) {
  const rect = node.getBoundingClientRect();
  const w = Math.round(rect.width), h = Math.round(rect.height);
  if (w < 20 || h < 20) return;
  const key = `${w}x${h}`;
  if (node._lgKey === key) return;
  node._lgKey = key;
  const radius = parseFloat(getComputedStyle(node).borderTopLeftRadius) || 20;
  const bezel = Math.min(parseFloat(node.dataset.bezel || 26), w / 2, h / 2);
  const strength = parseFloat(node.dataset.refract || 46);
  const blur = parseFloat(node.dataset.blur || 9);
  const id = node._lgId || (node._lgId = `lg-${++seq}`);

  const f = el("filter", { id, x: 0, y: 0, width: w, height: h, filterUnits: "userSpaceOnUse",
                           "color-interpolation-filters": "sRGB" });
  f.append(
    el("feGaussianBlur", { in: "SourceGraphic", stdDeviation: blur, result: "blur" }),
    el("feImage", { href: displacementMap(w, h, radius, bezel), x: 0, y: 0, width: w, height: h,
                    preserveAspectRatio: "none", result: "map" }),
    el("feDisplacementMap", { in: "blur", in2: "map", scale: strength, xChannelSelector: "R",
                              yChannelSelector: "G", result: "refract" }),
    el("feColorMatrix", { in: "refract", type: "saturate", values: "1.7", result: "sat" }),
    el("feComponentTransfer", { in: "sat" }),
  );
  const ct = f.lastChild;
  for (const c of ["feFuncR", "feFuncG", "feFuncB"]) ct.appendChild(el(c, { type: "linear", slope: "1.06" }));

  document.getElementById(id)?.remove();
  ensureDefs().appendChild(f);
  node.style.setProperty("--lg-filter", `url(#${id})`);
  node.classList.add("lg-on");
}

const ro = supported ? new ResizeObserver((entries) => {
  for (const e of entries) {
    clearTimeout(e.target._lgT);
    e.target._lgT = setTimeout(() => build(e.target), 120);
  }
}) : null;

/** Turn on refraction for every `.glass[data-lg]` under root (idempotent). */
export function applyLiquidGlass(root = document) {
  if (!supported) return;
  root.querySelectorAll(".glass[data-lg]").forEach((n) => {
    if (n._lgObserved) return;
    n._lgObserved = true;
    build(n);
    ro.observe(n);
  });
}

// Specular sheen follows the pointer across every glass surface.
window.addEventListener("pointermove", (ev) => {
  const t = ev.target.closest?.(".glass");
  if (!t) return;
  const r = t.getBoundingClientRect();
  t.style.setProperty("--mx", `${((ev.clientX - r.left) / r.width) * 100}%`);
  t.style.setProperty("--my", `${((ev.clientY - r.top) / r.height) * 100}%`);
}, { passive: true });

/** Subtle 3D tilt toward the pointer (cards, login panel). */
export function tilt(node, max = 8) {
  node.classList.add("tilt");
  node.addEventListener("pointermove", (ev) => {
    const r = node.getBoundingClientRect();
    const x = (ev.clientX - r.left) / r.width - 0.5, y = (ev.clientY - r.top) / r.height - 0.5;
    node.style.transform = `perspective(900px) rotateX(${(-y * max).toFixed(2)}deg) rotateY(${(x * max).toFixed(2)}deg) translateZ(0)`;
  });
  node.addEventListener("pointerleave", () => { node.style.transform = ""; });
}

export const liquidGlassSupported = supported;
