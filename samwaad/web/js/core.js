// Shared helpers: DOM, API, toasts, modals, formatting, app state and an event bus.
import { applyLiquidGlass } from "./liquidglass.js";
import { icon } from "./icons.js";

export const $ = (id) => document.getElementById(id);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const bus = new EventTarget();
export const on = (type, fn) => bus.addEventListener(type, (e) => fn(e.detail));
export const emit = (type, detail) => bus.dispatchEvent(new CustomEvent(type, { detail }));

export const state = {
  me: null, status: null, prefs: {}, languages: {}, native: {},
  running: false, session: null, startedAt: 0, lines: [], libCache: [],
};

// ------------------------------------------------------------------ formatting
export const fmtT = (t) => { t = Math.max(0, Math.floor(t || 0)); const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  return (h ? `${h}:${String(m).padStart(2, "0")}` : String(m).padStart(2, "0")) + `:${String(s).padStart(2, "0")}`; };
export const fmtDate = (ts, opts = { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) =>
  ts ? new Date(ts * 1000).toLocaleString(undefined, opts) : "";
export const idDate = (id) => { const m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/.exec(id || ""); return m ? new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5]).getTime() / 1000 : 0; };
export const compact = (n) => n >= 1e6 ? (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M" : n >= 1e4 ? Math.round(n / 1e3) + "K" : n >= 1e3 ? (n / 1e3).toFixed(1).replace(/\.0$/, "") + "K" : String(Math.round(n));
export const mins = (s) => s >= 3600 ? `${(s / 3600).toFixed(1)} h` : `${Math.max(1, Math.round(s / 60))} min`;
export const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
export const langName = (code) => state.languages[code] || code || "";
export const langNative = (code) => state.native[code] || "";
export const isoLang = { hin_Deva: "hi", mar_Deva: "mr", tam_Taml: "ta", tel_Telu: "te", ben_Beng: "bn", guj_Gujr: "gu", kan_Knda: "kn", mal_Mlym: "ml", pan_Guru: "pa", ory_Orya: "or", urd_Arab: "ur" };
export const devLabel = (engine) => {
  const [name, dev] = String(engine || "").split(":");
  const pretty = { "onnx-qnn": "Whisper", "faster-whisper": "Whisper", "opus-mt": "OPUS-MT", indictrans2: "IndicTrans2", mock: "Mock", script: "Demo script" }[name] || name;
  return { name: pretty, dev: (dev || "cpu").toUpperCase() };
};

// ------------------------------------------------------------------ API
export async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (r.status === 401) { location.href = "/login"; throw new Error("Signed out"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : (r.statusText || "Request failed"));
  return data;
}
export const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body ?? {}) });

// ------------------------------------------------------------------ toasts
export function toast(msg, kind = "ok") {
  const t = document.createElement("div");
  t.className = `toast glass ${kind}`;
  t.setAttribute("role", kind === "err" ? "alert" : "status");
  t.innerHTML = icon(kind === "err" ? "alert" : kind === "info" ? "info" : "check") + `<div>${esc(msg)}</div>`;
  $("toasts").appendChild(t);
  setTimeout(() => t.animate([{ opacity: 1 }, { opacity: 0, transform: "translateY(8px)" }], { duration: 280 }).finished.then(() => t.remove()), 3800);
}

// ------------------------------------------------------------------ modal (focus-trapped, Esc to close)
export function modal({ title, body = "", input = null, ok = "OK", danger = false, cancel = "Cancel" }) {
  return new Promise((resolve) => {
    const prev = document.activeElement;
    const wrap = document.createElement("div");
    wrap.className = "modal-wrap";
    wrap.innerHTML = `<div class="modal glass" role="dialog" aria-modal="true" aria-labelledby="mdT"><h3 id="mdT">${esc(title)}</h3><p>${body}</p>
      ${input !== null ? `<input class="field" value="${esc(input)}" aria-label="${esc(title)}">` : ""}
      <div class="row">${cancel ? `<button class="btn ghost" data-v="0">${esc(cancel)}</button>` : ""}<button class="btn ${danger ? "danger" : "primary"}" data-v="1">${esc(ok)}</button></div></div>`;
    document.body.appendChild(wrap);
    applyLiquidGlass(wrap);
    const inp = wrap.querySelector("input");
    (inp || wrap.querySelector('[data-v="1"]')).focus();
    inp?.select();
    const done = (v) => { wrap.remove(); prev?.focus?.(); resolve(v ? (inp ? inp.value : true) : null); };
    wrap.onclick = (e) => { if (e.target === wrap) done(false); const b = e.target.closest("[data-v]"); if (b) done(b.dataset.v === "1"); };
    wrap.onkeydown = (e) => {
      if (e.key === "Enter") { e.preventDefault(); done(true); }
      if (e.key === "Escape") done(false);
      if (e.key === "Tab") {
        const f = [...wrap.querySelectorAll("input,button")];
        const i = f.indexOf(document.activeElement);
        e.preventDefault();
        f[(i + (e.shiftKey ? -1 : 1) + f.length) % f.length].focus();
      }
    };
  });
}

// count-up animation for big numbers
export function countUp(el, to, { dur = 900, fmt = (v) => compact(v) } = {}) {
  if (document.body.classList.contains("reduce-motion") || !Number.isFinite(to)) { el.textContent = fmt(to || 0); return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    el.textContent = fmt(to * e);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// keyword extraction for lecture chips (client-side, no model)
const STOP = new Set(("a an the and or but if of to in on at for with by from is are was were be been being this that these those it its as so we you they he she i our your their there here what which who whom when where why how can could will would should may might must do does did not no yes just also very really then than now okay ok um uh like actually basically right going get got have has had one two let lets say see know think into about over more most such each other some any only same both all out up down new used use make made way lot thing things because while after before between during through today").split(" "));
export function keywords(text, n = 8) {
  const freq = new Map();
  for (const w of (text.toLowerCase().match(/[a-z][a-z-]{3,}/g) || [])) if (!STOP.has(w)) freq.set(w, (freq.get(w) || 0) + 1);
  return [...freq.entries()].filter(([, c]) => c > 1).sort((a, b) => b[1] - a[1]).slice(0, n).map(([w]) => w);
}
