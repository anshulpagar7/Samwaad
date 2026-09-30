// Samwaad app shell: boot, hash router, WebSocket event pump, global shortcuts, rail status.
import { closeCmdk, cmdkOpen, initCmdk, openCmdk } from "./cmdk.js";
import { $, $$, api, emit, esc, on, post, state } from "./core.js";
import { renderHome } from "./home.js";
import { hydrateIcons } from "./icons.js";
import { initLibrary, openNote, renderLibrary } from "./library.js";
import { applyLiquidGlass } from "./liquidglass.js";
import { fillLanguages, initLive, onEvent, renderPipeline, setCaptionScale, setLanguage, setRunning, toggle } from "./live.js";
import { maybeOnboard } from "./onboarding.js";
import { renderPerf } from "./perf.js";
import { createScene } from "./scene.js";
import { applyPrefs, renderSettings } from "./settings.js";

hydrateIcons();
const scene = createScene($("scene"));

// ------------------------------------------------------------------ router
const VIEWS = ["home", "live", "library", "note", "performance", "settings"];
let current = "";

function route() {
  const [, raw = "home", arg] = location.hash.split("/");
  const projector = raw === "projector";
  const name = projector ? "live" : VIEWS.includes(raw) ? raw : "home";
  document.body.classList.toggle("projector", projector);
  $$(".view").forEach((s) => s.classList.toggle("on", s.dataset.view === name));
  $$("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === (name === "note" ? "library" : name)));
  if (name === "live") scene.follow($(projector ? "bgAnchor" : "liveAnchor"));
  else if (name !== "home") scene.follow($("bgAnchor"));
  scene.setDim(name === "live" && !projector ? 1 : name === "home" ? 1 : projector ? 0.35 : 0.5);
  current = name;
  if (name === "home") renderHome(scene);
  if (name === "library") renderLibrary();
  if (name === "note" && arg) openNote(arg);
  if (name === "performance") renderPerf();
  if (name === "settings") renderSettings();
  document.title = { home: "Samwaad", live: "Live · Samwaad", library: "My lectures · Samwaad", note: "Lecture · Samwaad", performance: "On-device AI · Samwaad", settings: "Settings · Samwaad" }[name];
  requestAnimationFrame(() => applyLiquidGlass());
}
addEventListener("hashchange", route);

// ------------------------------------------------------------------ status
async function loadMe() {
  state.me = await api("/api/auth/me");
  state.prefs = state.me.prefs || {};
  applyPrefs();
  $("meName").textContent = state.me.name;
  $("meUser").textContent = "@" + state.me.username;
  $("avatar").textContent = state.me.name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
}

async function refreshStatus() {
  const s = (state.status = await api("/api/status"));
  const rt = s.runtime;
  $("epChip").className = "chip " + (rt.on_npu ? "good" : "warn");
  $("epChip").innerHTML = `<span class="dot"></span>${rt.on_npu ? "Snapdragon NPU" : "CPU · " + esc(rt.machine)}`;
  $("netChip").className = "chip " + (s.online ? "" : "good");
  $("netChip").innerHTML = s.online ? "Online · unused" : `<span class="dot"></span>Offline`;
  const asr = s.engines?.asr, mt = s.target ? (s.engines?.translate?.per_language?.[s.target] || "") : "";
  $("engines").textContent = `Whisper → ${(asr?.device || "cpu").toUpperCase()}` + (mt ? ` · ${mt.startsWith("opus") ? "OPUS-MT" : "IndicTrans2"} → ${(mt.split(":")[1] || "cpu").toUpperCase()}` : "") + ` · ${s.llm === "extractive" ? "offline summariser" : "local LLM"}`;
  if (!Object.keys(state.languages).length) {
    state.languages = s.languages; state.native = s.native || {};
    fillLanguages(); renderPipeline();
  }
  if (s.running !== state.running) {
    if (s.running && s.started_at) state.startedAt = s.started_at * 1000;
    setRunning(s.running);
  }
  if (s.busy) $("statusText").textContent = "Another account is captioning";
}

// ------------------------------------------------------------------ websocket
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onmessage = (m) => onEvent(JSON.parse(m.data));
  ws.onclose = (e) => { if (e.code === 4401) location.href = "/login"; else setTimeout(connect, 1200); };
}
on("library-changed", () => { if (current === "library") renderLibrary(); else api("/api/sessions").then((l) => { state.libCache = l; $("libCount").textContent = l.length || ""; }).catch(() => {}); });

// ------------------------------------------------------------------ global keys
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); cmdkOpen() ? closeCmdk() : openCmdk(); return; }
  if (e.target.closest("input, textarea, select, [contenteditable='true']") || cmdkOpen() || document.querySelector(".modal-wrap, .coach")) return;
  if (e.key === " " && (current === "live" || current === "home")) { e.preventDefault(); toggle(); }
  else if (e.key.toLowerCase() === "p" && current === "live") location.hash = location.hash === "#/projector" ? "#/live" : "#/projector";
  else if (e.key === "Escape" && location.hash === "#/projector") location.hash = "#/live";
  else if (e.key.toLowerCase() === "l" && (current === "live" || current === "home")) {
    const codes = ["", ...Object.keys(state.languages)], i = codes.indexOf(state.status?.target || "");
    setLanguage(codes[(i + 1) % codes.length]);
  } else if ((e.key === "+" || e.key === "=") && current === "live") setCaptionScale((state.prefs.caption_scale || 1) + 0.1);
  else if (e.key === "-" && current === "live") setCaptionScale((state.prefs.caption_scale || 1) - 0.1);
});

$("logoutBtn").onclick = async () => { await post("/api/auth/logout").catch(() => {}); location.href = "/login"; };

// ------------------------------------------------------------------ boot
(async () => {
  initLive(scene);
  initLibrary();
  initCmdk();
  await loadMe();
  await refreshStatus();
  on("target", () => refreshStatus().catch(() => {}));
  route();
  connect();
  emit("library-changed");
  setInterval(() => refreshStatus().catch(() => {}), 5000);
  maybeOnboard();
})();
