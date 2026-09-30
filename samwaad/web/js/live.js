// Live lecture view: big two-line captions, audio ring, pipeline visualizer, transcript feed.
import { $, api, devLabel, emit, esc, fmtT, isoLang, langName, langNative, modal, post, state, toast } from "./core.js";
import { icon } from "./icons.js";
import { createRing } from "./ring.js";

let scene, ring, follow = true;
const stats = { asr: [], e2e: [], rtf: null };
const avg = (xs) => (xs.length ? Math.round(xs.reduce((a, b) => a + b, 0) / xs.length) : null);

// ------------------------------------------------------------------ pipeline visualizer
const NODES = [
  { id: "mic", icon: "mic", name: "Mic", sub: "16 kHz" },
  { id: "vad", icon: "wave", name: "VAD", sub: "Silero" },
  { id: "asr", icon: "npu", name: "Whisper", sub: "speech → text" },
  { id: "mt", icon: "globe", name: "Translate", sub: "→ Indic" },
  { id: "store", icon: "save", name: "Saved", sub: "on disk" },
];

export function renderPipeline() {
  const eng = state.status?.engines || {};
  const asrDev = (eng.asr?.device || "cpu").toUpperCase();
  const tgt = state.status?.target;
  const mt = tgt ? devLabel(eng.translate?.per_language?.[tgt] || "") : { name: "Off", dev: "—" };
  const dev = { mic: "", vad: "CPU", asr: asrDev, mt: mt.dev, store: "" };
  const name = { asr: eng.asr?.name === "script" ? "Demo" : "Whisper", mt: mt.name === "Demo script" ? "Demo" : mt.name };
  $("pipe").innerHTML = NODES.map((n, i) => `
    ${i ? `<div class="pwire" data-w="${n.id}"><i></i></div>` : ""}
    <div class="pnode" id="pn-${n.id}" title="${esc(n.sub)}">
      ${dev[n.id] ? `<span class="dev ${dev[n.id] === "NPU" ? "npu" : ""}">${dev[n.id]}</span>` : ""}
      <span class="pi">${icon(n.icon)}</span>
      <div><b>${esc(name[n.id] || n.name)}</b><span id="pv-${n.id}">${esc(n.sub)}</span></div>
    </div>`).join("");
}

function pulse(id, ms, busy = false) {
  const n = $(`pn-${id}`);
  if (!n) return;
  n.classList.toggle("busy", busy);
  if (!busy) {
    n.classList.remove("flash"); void n.offsetWidth; n.classList.add("flash");
    const w = document.querySelector(`.pwire[data-w="${id}"]`);
    if (w) { w.classList.remove("go"); void w.offsetWidth; w.classList.add("go"); }
    if (ms != null && $(`pv-${id}`)) $(`pv-${id}`).textContent = id === "vad" ? `${(ms / 1000).toFixed(1)} s cut` : `${Math.round(ms)} ms`;
  }
}

// ------------------------------------------------------------------ captions
function showCaption(text) {
  const words = text.split(/\s+/);
  $("nowCap").innerHTML = `<div class="cap-line">${words.map((w, i) => `<span class="w" style="animation-delay:${Math.min(i * 32, 600)}ms">${esc(w)}</span>`).join(" ")}</div>`;
  $("nowTr").textContent = "";
}

function feedEmpty() {
  return `<div class="feed-empty">Every sentence lands here with its translation,<br>and is saved to <b>My lectures</b> automatically.</div>`;
}

function addLine(l) {
  const feed = $("feed");
  feed.querySelector(".feed-empty")?.remove();
  const div = document.createElement("div");
  div.className = "ln";
  div.id = `ln-${l.idx}`;
  const ms = l.asr_ms > 0 ? `<span class="ms">${Math.round(l.asr_ms)} ms · ${esc(devLabel(l.asr_backend).dev)}</span>` : "";
  div.innerHTML = `<div class="meta"><span>${fmtT(l.start_s)}</span>${ms}</div><div class="en">${esc(l.text)}</div>`;
  feed.appendChild(div);
  if (follow) feed.scrollTop = feed.scrollHeight;
  $("lineStat").textContent = `${feed.querySelectorAll(".ln").length} lines`;
}

function addTranslation(ev) {
  const row = $(`ln-${ev.idx}`);
  const lang = isoLang[ev.target] || "";
  if (row) row.insertAdjacentHTML("beforeend", `<div class="tr indic" lang="${lang}">${esc(ev.text)}</div>`);
  $("nowTr").setAttribute("lang", lang);
  $("nowTr").textContent = ev.text;
  if (follow) $("feed").scrollTop = $("feed").scrollHeight;
}

function updateMini() {
  $("mAsr").textContent = avg(stats.asr) ?? "—";
  $("mE2e").textContent = avg(stats.e2e) ?? "—";
  $("mRtf").textContent = stats.rtf ? `${Math.max(1, Math.round(1 / stats.rtf))}×` : "—";
}

// ------------------------------------------------------------------ run state
export function setRunning(on) {
  state.running = on;
  document.body.classList.toggle("live-on", on);
  scene.setActive(on);
  ring?.setActive(on);
  $("startLbl").textContent = on ? "Stop" : "Start lecture";
  $("demoBtn").disabled = on;
  $("statusText").textContent = on ? "Listening" : "Ready";
  if (!on) { $("timer").textContent = ""; $("hearing").hidden = true; }
}

setInterval(() => { if (state.running && state.startedAt) $("timer").textContent = fmtT((Date.now() - state.startedAt) / 1000); }, 500);

export async function toggle() {
  try {
    if (state.running) await post("/api/stop");
    else {
      if (location.hash !== "#/live" && location.hash !== "#/projector") location.hash = "#/live";
      await post("/api/start", { source: "mic", title: $("title").value.trim() || null });
    }
  } catch (e) { toast(e.message, "err"); }
}

export async function demo() {
  const wav = await modal({ title: "Replay a recording", body: "Path to a 16-bit WAV on this PC. It flows through the exact same pipeline as a live microphone — handy for demos.",
                            input: "samples/lecture.wav", ok: "Play" });
  if (!wav) return;
  if (location.hash !== "#/live") location.hash = "#/live";
  try { await post("/api/start", { source: "file", wav, title: $("title").value.trim() || null }); }
  catch (e) { toast(e.message, "err"); }
}

export function fillLanguages() {
  const sel = $("lang");
  sel.innerHTML = `<option value="">No translation</option>` +
    Object.entries(state.languages).map(([k, v]) => `<option value="${k}">${v} · ${langNative(k)}</option>`).join("");
  sel.value = state.status?.target || "";
}

export async function setLanguage(code) {
  try {
    await post("/api/target", { target: code || null });
    state.status.target = code || null;
    state.prefs.target = code || null;
    $("lang").value = code || "";
    renderPipeline();
    emit("target", code);
  } catch (e) { toast(e.message, "err"); }
}

export function setCaptionScale(v) {
  v = Math.max(0.8, Math.min(2.2, Math.round(v * 10) / 10));
  document.documentElement.style.setProperty("--caption-scale", v);
  state.prefs.caption_scale = v;
  clearTimeout(setCaptionScale._t);
  setCaptionScale._t = setTimeout(() => api("/api/settings", { method: "PUT", body: JSON.stringify({ caption_scale: v }) }).catch(() => {}), 400);
}

// ------------------------------------------------------------------ events from the pipeline
export function onEvent(ev) {
  switch (ev.type) {
    case "started":
      state.session = ev.session; state.startedAt = Date.now(); follow = true;
      stats.asr = []; stats.e2e = []; stats.rtf = null; updateMini();
      $("feed").innerHTML = feedEmpty();
      $("nowCap").innerHTML = `<div class="empty-cap">Listening… start speaking.</div>`; $("nowTr").textContent = "";
      $("lineStat").textContent = "0 lines";
      setRunning(true);
      pulse("mic", null);
      break;
    case "level":
      scene.setLevel(ev.rms, ev.speech);
      ring?.set(ev.bands, ev.speech);
      $("hearing").hidden = !(ev.speech > 0.5);
      $("pn-mic")?.classList.toggle("busy", ev.rms > 0.05);
      break;
    case "stage":
      pulse(ev.stage, ev.ms, ev.state === "start");
      break;
    case "caption":
      showCaption(ev.line.text);
      addLine(ev.line);
      if (ev.line.asr_ms > 0) stats.asr.push(ev.line.asr_ms);
      if (ev.line.e2e_ms > 0) stats.e2e.push(ev.line.e2e_ms);
      updateMini();
      break;
    case "translation":
      addTranslation(ev);
      break;
    case "metrics":
      stats.rtf = ev.rtf;
      updateMini();
      emit("metrics", ev);
      break;
    case "stopped":
      setRunning(false);
      toast(`Saved · ${ev.stats.lines} sentences. Open it in My lectures for a study kit.`);
      emit("library-changed");
      emit("metrics", ev.metrics);
      break;
    case "error":
      toast(`${ev.where}: ${ev.message}`, "err");
      break;
  }
}

// ------------------------------------------------------------------ init
export function initLive(sc) {
  scene = sc;
  ring = createRing($("ring"), $("liveAnchor"));
  $("startBtn").onclick = toggle;
  $("demoBtn").onclick = demo;
  $("lang").onchange = () => setLanguage($("lang").value);
  $("projBtn").onclick = () => (location.hash = "#/projector");
  $("projExit").onclick = () => (location.hash = "#/live");
  $("capUp").onclick = () => setCaptionScale((state.prefs.caption_scale || 1) + 0.1);
  $("capDown").onclick = () => setCaptionScale((state.prefs.caption_scale || 1) - 0.1);
  const feed = $("feed");
  feed.addEventListener("scroll", () => {
    follow = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 40;
    $("jumpBtn").classList.toggle("on", !follow);
  });
  $("jumpBtn").onclick = () => { follow = true; feed.scrollTop = feed.scrollHeight; $("jumpBtn").classList.remove("on"); };
  renderPipeline();
  return { langName };
}
