// Settings: captions & accessibility, translation engine, microphone, system check, account.
import { $, $$, api, esc, isoLang, langNative, post, state, toast } from "./core.js";
import { icon } from "./icons.js";
import { applyLiquidGlass } from "./liquidglass.js";
import { renderPipeline, setCaptionScale, setLanguage } from "./live.js";

export function applyPrefs(p = state.prefs) {
  document.documentElement.style.setProperty("--caption-scale", p.caption_scale || 1);
  document.body.classList.toggle("contrast", !!p.contrast);
  document.body.classList.toggle("readable", !!p.readable_font);
  document.body.classList.toggle("reduce-motion", !!p.reduce_motion);
  const sc = document.getElementById("scene");
  if (sc) sc.style.visibility = p.reduce_motion ? "hidden" : "";
}

async function save(patch) {
  try {
    state.prefs = await api("/api/settings", { method: "PUT", body: JSON.stringify(patch) });
    applyPrefs();
  } catch (e) { toast(e.message, "err"); }
}

const sw = (key, on) => `<button class="switch" role="switch" aria-checked="${!!on}" data-sw="${key}"></button>`;
const row = (title, sub, ctl) => `<div class="srow"><div class="txt"><b>${title}</b><span>${sub}</span></div>${ctl}</div>`;

export async function renderSettings() {
  const p = state.prefs, s = state.status || {}, per = s.engines?.translate?.per_language || {};
  const devices = await api("/api/devices").catch(() => []);
  const tgt = s.target;
  $("settingsGrid").innerHTML = `
    <section class="sgroup glass" data-lg>
      <h3>${icon("type")}Captions &amp; accessibility</h3>
      <div class="preview-cap" aria-hidden="true"><div class="cap-line">The leader replicates every log entry to its followers.</div>
        <div class="tr-line indic" lang="hi">लीडर हर लॉग एंट्री को अपने फॉलोअर्स तक पहुँचाता है।</div></div>
      ${row("Caption size", "Also adjustable live with A− / A+ or the + and − keys",
            `<input type="range" class="range" id="capScale" min="0.8" max="2.2" step="0.1" value="${p.caption_scale || 1}" style="width:200px" aria-label="Caption size">`)}
      ${row("High-contrast captions", "Solid black caption box, brighter text — easier to read from the back row", sw("contrast", p.contrast))}
      ${row("Readable font &amp; spacing", "Wider letter and line spacing — helpful for dyslexia", sw("readable_font", p.readable_font))}
      ${row("Reduce motion", "Turns off the 3D orb and animations", sw("reduce_motion", p.reduce_motion))}
    </section>

    <section class="sgroup glass" data-lg>
      <h3>${icon("globe")}Translation</h3>
      ${row("Translate into", "Used for new lectures; switch any time during a lecture",
            `<select class="field" id="setLang"><option value="">No translation</option>${Object.entries(state.languages).map(([k, v]) => `<option value="${k}" ${k === tgt ? "selected" : ""}>${v} · ${langNative(k)}</option>`).join("")}</select>`)}
      ${row("Engine", "Fast = OPUS-MT on the NPU where available · Best quality = IndicTrans2 on the CPU",
            `<div class="seg glass thin" id="preferSeg"><span class="thumb"></span><button data-p="npu" class="${(p.prefer || "npu") === "npu" ? "on" : ""}">Fast · NPU</button><button data-p="quality" class="${p.prefer === "quality" ? "on" : ""}">Best quality</button></div>`)}
      <table class="eng-table" aria-label="Engine per language">${Object.keys(state.languages).map((k) => {
        const [n, d] = String(per[k] || "none").split(":");
        return `<tr><td><span class="indic" lang="${isoLang[k]}">${esc(langNative(k))}</span> <span class="muted">· ${esc(state.languages[k])}</span></td>
          <td>${n === "none" ? `<span class="chip">not installed</span>` : `<span class="chip ${d === "npu" ? "good" : ""}">${esc(n === "opus-mt" ? "OPUS-MT" : n === "indictrans2" ? "IndicTrans2" : n)} · ${esc((d || "cpu").toUpperCase())}</span>`}</td></tr>`;
      }).join("")}</table>
    </section>

    <section class="sgroup glass" data-lg>
      <h3>${icon("mic")}Audio</h3>
      ${row("Microphone", "Pick a loopback / “Stereo Mix” device to caption Zoom, Teams or YouTube",
            `<select class="field" id="setMic"><option value="">System default</option>${devices.map((d) => `<option value="${d.id}" ${String(p.mic) === String(d.id) ? "selected" : ""}>${esc(d.name)}${d.default ? " (default)" : ""}</option>`).join("")}</select>`)}
      ${!devices.length ? `<p class="note-src">No input devices were detected by the audio backend — use Demo mode with a recording, or plug in a microphone.</p>` : ""}
    </section>

    <section class="sgroup glass" data-lg>
      <h3>${icon("shield")}System check<span style="flex:1"></span><button class="btn sm" id="rerun">${icon("refresh")}Re-run</button></h3>
      <div id="doctor"><div class="skel" style="height:220px;margin:10px 0"></div></div>
    </section>

    <section class="sgroup glass" data-lg>
      <h3>${icon("lock")}Account &amp; privacy</h3>
      ${row(esc(state.me?.name || ""), `@${esc(state.me?.username || "")} · local account on this laptop`, `<button class="btn sm" id="setLogout">${icon("logout")}Sign out</button>`)}
      ${row("Where your data lives", "Lectures, translations and study kits are plain files in <code>sessions/</code>. Passwords are salted PBKDF2 hashes. The server only listens on 127.0.0.1.", "")}
      ${row("Internet", s.online ? "Connected — Samwaad never uses it after setup" : "Offline — everything still works", `<span class="chip good"><span class="dot"></span>Private</span>`)}
    </section>

    <section class="sgroup glass" data-lg>
      <h3>${icon("info")}About</h3>
      ${row("Samwaad", "संवाद — “dialogue”. Built for the Snapdragon AI Lab Build &amp; Present Challenge.", `<span class="chip">v1.0</span>`)}
      ${row("Models", "Whisper (OpenAI, via Qualcomm AI Hub) · OPUS-MT (Helsinki-NLP) · IndicTrans2 (AI4Bharat) · Silero VAD · Llama 3.2 3B (Meta, via AI Hub)", "")}
      ${row("Keyboard", "Space start/stop · Ctrl K palette · P projector · L language · + / − caption size", "")}
    </section>`;

  $("capScale").oninput = (e) => setCaptionScale(+e.target.value);
  $$("[data-sw]").forEach((b) => (b.onclick = () => {
    const v = b.getAttribute("aria-checked") !== "true";
    b.setAttribute("aria-checked", v);
    save({ [b.dataset.sw]: v });
  }));
  $("setLang").onchange = (e) => setLanguage(e.target.value);
  const seg = $("preferSeg");
  const move = () => { const b = seg.querySelector("button.on"), th = seg.querySelector(".thumb"); if (b) { th.style.width = `${b.offsetWidth}px`; th.style.transform = `translateX(${b.offsetLeft - 4}px)`; } };
  requestAnimationFrame(move);
  seg.querySelectorAll("button").forEach((b) => (b.onclick = async () => {
    seg.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b)); move();
    await save({ prefer: b.dataset.p });
    state.status = await api("/api/status"); renderPipeline();
    toast(b.dataset.p === "npu" ? "Fast mode — NPU translation where available" : "Best-quality mode — IndicTrans2");
  }));
  $("setMic").onchange = (e) => save({ mic: e.target.value === "" ? null : +e.target.value });
  $("setLogout").onclick = async () => { await post("/api/auth/logout").catch(() => {}); location.href = "/login"; };
  $("rerun").onclick = loadDoctor;
  applyLiquidGlass($("settingsGrid"));
  loadDoctor();
}

async function loadDoctor() {
  const box = $("doctor");
  try {
    const checks = await api("/api/doctor");
    const mark = { ok: "✓", warn: "!", info: "i", error: "×" };
    box.innerHTML = checks.map((c) => `<div class="check"><span class="st ${c.status}">${mark[c.status]}</span><div><b>${esc(c.name)}</b><span>${esc(c.detail)}</span>
      ${c.fix && (c.status === "warn" || c.status === "error") ? `<span>Fix: <code>${esc(c.fix)}</code></span>` : ""}</div></div>`).join("");
  } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
}
