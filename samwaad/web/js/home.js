// Home: a bento dashboard — hero with the orb, stats, activity, on-device engines, recents.
import { columns } from "./charts.js";
import { $, api, compact, countUp, devLabel, esc, fmtDate, idDate, isoLang, langNative, mins, plural, state } from "./core.js";
import { icon } from "./icons.js";
import { demo, setLanguage, toggle } from "./live.js";
import { applyLiquidGlass, tilt } from "./liquidglass.js";

const QUICK = ["hin_Deva", "mar_Deva", "tam_Taml", "tel_Telu", "ben_Beng", "kan_Knda"];

function greet() {
  const h = new Date().getHours();
  return h < 5 ? "Burning the midnight oil" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

function engineRow(ic, title, sub, dev) {
  const chip = dev === "NPU" ? `<span class="chip good"><span class="dot"></span>NPU</span>`
    : dev === "OFF" ? `<span class="chip">Off</span>` : dev === "OK" ? `<span class="chip good"><span class="dot"></span>Ready</span>` : `<span class="chip warn">${esc(dev)}</span>`;
  return `<div class="engine"><span class="ei">${icon(ic)}</span><div><b>${esc(title)}</b><span>${esc(sub)}</span></div>${chip}</div>`;
}

export async function renderHome(scene) {
  const grid = $("homeGrid");
  const name = (state.me?.name || "").split(/\s+/)[0];
  $("today").textContent = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  const [stats, recent] = await Promise.all([api("/api/stats"), api("/api/sessions")]).catch(() => [null, []]);
  const s = state.status || {}, eng = s.engines || {}, tgt = s.target;
  const mt = tgt ? devLabel(eng.translate?.per_language?.[tgt]) : null;
  const asrDev = (eng.asr?.device || "cpu").toUpperCase();

  grid.innerHTML = `
    <section class="tile glass hero-tile span-6 rows-2" aria-label="Start">
      <div>
        <div class="eyebrow">${esc(greet())}${name ? `, ${esc(name)}` : ""}</div>
        <h2>Every lecture.<br><span class="grad-text">Every language.</span><br>On this laptop.</h2>
        <div class="lang-quick" role="group" aria-label="Translate into">
          ${QUICK.map((c) => `<button class="chip ${tgt === c ? "on" : ""}" data-lang="${c}"><span class="indic" lang="${isoLang[c]}">${esc(langNative(c))}</span></button>`).join("")}
          <button class="chip ${!tgt ? "on" : ""}" data-lang="">English only</button>
        </div>
      </div>
      <div class="hero-actions">
        <button class="btn primary lg" id="heroStart">${icon("mic")}${state.running ? "Back to live lecture" : "Start a lecture"}</button>
        <button class="btn lg ghost" id="heroDemo">${icon("play")}Play demo</button>
      </div>
      <div class="orb-slot" id="homeAnchor"></div>
    </section>

    ${[["book", "v1", "Lectures", stats?.lectures ?? 0, "", `${stats?.study_kits ?? 0} with a study kit`],
       ["clock", "v2", "Captioned", stats?.minutes ?? 0, "min", "of speech, fully offline"],
       ["type", "v3", "Words transcribed", stats?.words ?? 0, "", "searchable in your library"],
       ["sparkles", "v4", "Flashcards", stats?.flashcards ?? 0, "", "generated on-device"]].map(([ic, c, label, v, unit, sub]) => `
    <section class="tile glass stat span-3" aria-label="${esc(label)}">
      <div class="ico ${c}">${icon(ic)}</div>
      <div class="eyebrow">${esc(label)}</div>
      <div class="v"><span data-count="${v}">0</span>${unit ? `<small>${unit}</small>` : ""}</div>
      <div class="sub">${esc(sub)}</div>
    </section>`).join("")}

    <section class="tile glass span-6" aria-label="Activity">
      <div class="eyebrow">Minutes captioned · last 14 days<span class="spacer"></span>
        ${stats?.streak ? `<span class="chip warm">${icon("flame")}${plural(stats.streak, "day")} streak</span>` : ""}</div>
      <div id="activity" data-label="Minutes captioned per day, last 14 days"></div>
    </section>

    <section class="tile glass span-3 rows-2" data-lg aria-label="On-device AI">
      <div class="eyebrow">On-device AI<span class="spacer"></span><a href="#/performance" class="muted" style="font-size:11px;text-decoration:none">Details →</a></div>
      <div class="engine-list">
        ${engineRow("npu", "Speech recognition", eng.asr?.name === "onnx-qnn" ? "Whisper Base · AI Hub" : eng.asr?.name === "script" ? "Demo script" : "Whisper", asrDev)}
        ${engineRow("globe", "Translation", mt ? `${mt.name} → ${state.languages[tgt]}` : "English only", mt ? mt.dev : "OFF")}
        ${engineRow("brain", "Study kit", s.llm === "extractive" ? "Offline summariser" : s.llm === "genie" ? "Llama 3.2 3B · Genie" : "Local LLM", s.llm === "genie" ? "NPU" : "OK")}
        ${engineRow("wifioff", "Internet", s.online ? "Connected — but not used" : "Offline — nothing leaves this PC", "OK")}
      </div>
      <p class="note-src" style="margin-top:auto">Processor: ${esc(s.runtime?.processor || s.runtime?.machine || "")}</p>
    </section>

    <section class="tile glass span-3" aria-label="Languages">
      <div class="eyebrow">Languages you use</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px">
        ${(stats?.languages || []).length ? stats.languages.map((l) => `<span class="chip accent"><span class="indic" lang="${isoLang[l.code]}">${esc(langNative(l.code))}</span> · ${l.count}</span>`).join("")
          : `<span class="muted" style="font-size:13px;line-height:1.5">Pick a language on the left — 11 Indian languages are available.</span>`}
      </div>
    </section>

    <section class="tile glass span-6" aria-label="Recent lectures">
      <div class="eyebrow">Recent lectures<span class="spacer"></span><a href="#/library" class="muted" style="font-size:11px;text-decoration:none">View all →</a></div>
      <div class="recent">${recent.slice(0, 4).map((r) => `
        <a href="#/note/${r.id}"><span class="rdot">${esc((r.title.match(/[A-Za-z0-9]/) || ["•"])[0].toUpperCase())}</span>
          <span class="grow"><b>${esc(r.title)}</b><span>${esc(fmtDate(r.created || idDate(r.id)))} · ${mins(r.audio_s)} · ${plural(r.lines, "line")}</span></span>
          ${r.has_kit ? `<span class="chip good">Study kit</span>` : ""}${r.starred ? `<span class="chip warm">${icon("star")}</span>` : ""}</a>`).join("")
        || `<p class="muted" style="font-size:13.5px;margin:6px 2px">No lectures yet — press <b>Start a lecture</b> or <b>Play demo</b>.</p>`}</div>
    </section>

    <section class="tile glass span-3" aria-label="Keyboard shortcuts">
      <div class="eyebrow">Shortcuts</div>
      <div class="kbd-list">
        <kbd>Space</kbd><span>Start / stop captions</span>
        <kbd>Ctrl K</kbd><span>Command palette</span>
        <kbd>P</kbd><span>Projector mode</span>
        <kbd>L</kbd><span>Next language</span>
        <kbd>+ / −</kbd><span>Caption size</span>
      </div>
    </section>`;

  grid.querySelectorAll("[data-count]").forEach((el) => countUp(el, +el.dataset.count, { fmt: (v) => (+el.dataset.count < 10 && +el.dataset.count % 1 ? v.toFixed(1) : compact(v)) }));
  if (stats) columns($("activity"), stats.days.map((d) => ({ label: d.label[0], tip: new Date(d.date).toDateString(), value: d.minutes })), { unit: "min", height: 136, labelEvery: 1 });
  grid.querySelectorAll("[data-lang]").forEach((b) => (b.onclick = async () => { await setLanguage(b.dataset.lang); renderHome(scene); }));
  $("heroStart").onclick = () => (state.running ? (location.hash = "#/live") : toggle());
  $("heroDemo").onclick = demo;
  grid.querySelectorAll(".stat").forEach((t) => tilt(t, 6));
  scene.follow($("homeAnchor"));
  applyLiquidGlass(grid);
}
