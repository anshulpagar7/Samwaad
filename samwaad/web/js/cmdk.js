// Command palette (Ctrl/⌘ K): actions, navigation, languages and every lecture, fuzzy-filtered.
import { $, esc, fmtDate, idDate, langNative, state } from "./core.js";
import { icon } from "./icons.js";
import { demo, setLanguage, toggle } from "./live.js";

let items = [], sel = 0, open = false, prevFocus = null;

function build() {
  const a = [
    { g: "Actions", ic: "mic", t: state.running ? "Stop captioning" : "Start a lecture", s: "Space", run: toggle },
    { g: "Actions", ic: "play", t: "Play demo recording", run: demo },
    { g: "Actions", ic: "expand", t: "Projector mode — giant captions", s: "P", run: () => (location.hash = "#/projector") },
    { g: "Go to", ic: "home", t: "Home", run: () => (location.hash = "#/home") },
    { g: "Go to", ic: "mic", t: "Live lecture", run: () => (location.hash = "#/live") },
    { g: "Go to", ic: "library", t: "My lectures", run: () => (location.hash = "#/library") },
    { g: "Go to", ic: "gauge", t: "On-device AI performance", run: () => (location.hash = "#/performance") },
    { g: "Go to", ic: "settings", t: "Settings", run: () => (location.hash = "#/settings") },
    { g: "Translate into", ic: "globe", t: "English only (no translation)", run: () => setLanguage("") },
    ...Object.entries(state.languages).map(([k, v]) => ({ g: "Translate into", ic: "globe", t: `${v}`, s: langNative(k), run: () => setLanguage(k) })),
    ...state.libCache.map((l) => ({ g: "Lectures", ic: "book", t: l.title, s: fmtDate(l.created || idDate(l.id), { day: "numeric", month: "short" }), run: () => (location.hash = `#/note/${l.id}`) })),
  ];
  return a;
}

function render() {
  const q = $("cmdkInput").value.trim().toLowerCase();
  items = build().filter((i) => !q || (i.t + " " + (i.s || "") + " " + i.g).toLowerCase().includes(q)).slice(0, 40);
  sel = Math.min(sel, Math.max(0, items.length - 1));
  let g = "";
  $("cmdkList").innerHTML = items.map((it, i) => {
    const head = it.g !== g ? `<div class="grp">${esc((g = it.g))}</div>` : "";
    return `${head}<div class="it ${i === sel ? "sel" : ""}" role="option" aria-selected="${i === sel}" data-i="${i}">${icon(it.ic)}<span>${esc(it.t)}</span>${it.s ? `<span class="s">${esc(it.s)}</span>` : ""}</div>`;
  }).join("") || `<div class="grp" style="padding:18px">No matches</div>`;
  $("cmdkList").querySelector(".sel")?.scrollIntoView({ block: "nearest" });
}

export function openCmdk() {
  open = true; sel = 0; prevFocus = document.activeElement;
  $("cmdk").classList.add("on");
  $("cmdkInput").value = "";
  render();
  $("cmdkInput").focus();
}
export function closeCmdk() {
  open = false;
  $("cmdk").classList.remove("on");
  prevFocus?.focus?.();
}

export function initCmdk() {
  $("cmdkInput").oninput = () => { sel = 0; render(); };
  $("cmdkInput").onkeydown = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(items.length - 1, sel + 1); render(); }
    if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(0, sel - 1); render(); }
    if (e.key === "Enter") { e.preventDefault(); const it = items[sel]; closeCmdk(); it?.run(); }
    if (e.key === "Escape") closeCmdk();
  };
  $("cmdkList").onclick = (e) => { const r = e.target.closest("[data-i]"); if (r) { const it = items[+r.dataset.i]; closeCmdk(); it.run(); } };
  $("cmdk").onclick = (e) => { if (e.target.id === "cmdk") closeCmdk(); };
  document.querySelectorAll("[data-cmdk]").forEach((b) => (b.onclick = openCmdk));
}
export const cmdkOpen = () => open;
