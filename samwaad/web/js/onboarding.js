// First-run welcome: three quick cards, then never again (stored as a per-account setting).
import { api, esc, state } from "./core.js";
import { applyLiquidGlass } from "./liquidglass.js";

const STEPS = [
  { art: "🎙️", t: "Captions, live — even offline", p: "Press <b>Start lecture</b> (or <kbd>Space</kbd>). Whisper runs on your Snapdragon NPU, so every word appears within a blink — no internet, nothing uploaded." },
  { art: "🌏", t: "In your language", p: "Pick Hindi, Marathi, Tamil or 8 more. Each sentence is translated as it's spoken. Use <b>Projector mode</b> to put giant captions on the classroom screen." },
  { art: "✦", t: "Revise in minutes", p: "Every lecture is saved to <b>My lectures</b>. One click builds a summary, 3D flashcards and a glossary — and you can ask the lecture questions." },
];

export function maybeOnboard() {
  if (state.prefs.onboarded) return;
  let i = 0;
  const wrap = document.createElement("div");
  wrap.className = "coach";
  wrap.setAttribute("role", "dialog");
  wrap.setAttribute("aria-modal", "true");
  const draw = () => {
    const s = STEPS[i];
    wrap.innerHTML = `<div class="card-c glass"><div class="art" aria-hidden="true">${s.art}</div>
      <div class="eyebrow">Welcome${state.me?.name ? `, ${esc(state.me.name.split(" ")[0])}` : ""} · ${i + 1} of ${STEPS.length}</div>
      <h3>${s.t}</h3><p>${s.p}</p>
      <div class="row"><div class="dots">${STEPS.map((_, j) => `<i class="${j === i ? "on" : ""}"></i>`).join("")}</div>
        <div style="display:flex;gap:8px"><button class="btn ghost" data-a="skip">Skip</button><button class="btn primary" data-a="next">${i === STEPS.length - 1 ? "Let's go" : "Next"}</button></div></div></div>`;
    applyLiquidGlass(wrap);
    wrap.querySelector('[data-a="next"]').focus();
  };
  const finish = () => {
    wrap.remove();
    state.prefs.onboarded = true;
    api("/api/settings", { method: "PUT", body: JSON.stringify({ onboarded: true }) }).catch(() => {});
  };
  wrap.onclick = (e) => {
    const a = e.target.closest("[data-a]")?.dataset.a;
    if (a === "skip") finish();
    if (a === "next") { if (++i >= STEPS.length) finish(); else draw(); }
  };
  wrap.onkeydown = (e) => { if (e.key === "Escape") finish(); };
  document.body.appendChild(wrap);
  draw();
}
