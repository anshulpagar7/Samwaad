// Library (search / filter / sort / star) and the lecture view (transcript + study kit).
import { $, $$, api, esc, fmtDate, fmtT, idDate, isoLang, keywords, langName, langNative, mins, modal, plural, post, state, toast } from "./core.js";
import { icon } from "./icons.js";
import { applyLiquidGlass, tilt } from "./liquidglass.js";

let filter = "all", sort = "new", query = "", searchT;

function highlight(text, q) {
  const s = esc(text);
  if (!q) return s;
  return s.replace(new RegExp(esc(q).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "ig"), (m) => `<mark>${m}</mark>`);
}

function moveThumb(seg) {
  const on = seg.querySelector("button.on"), th = seg.querySelector(".thumb");
  if (on && th) { th.style.width = `${on.offsetWidth}px`; th.style.transform = `translateX(${on.offsetLeft - 4}px)`; }
}

export function initLibrary() {
  $("search").oninput = () => { clearTimeout(searchT); searchT = setTimeout(() => { query = $("search").value.trim(); renderLibrary(); }, 160); };
  $$("#libFilter button").forEach((b) => (b.onclick = () => {
    $$("#libFilter button").forEach((x) => x.classList.toggle("on", x === b));
    filter = b.dataset.f; moveThumb($("libFilter")); renderLibrary();
  }));
  $("libSort").onchange = () => { sort = $("libSort").value; renderLibrary(); };
  initNote();
}

export async function renderLibrary() {
  requestAnimationFrame(() => moveThumb($("libFilter")));
  const cards = $("cards");
  if (!cards.children.length) cards.innerHTML = Array.from({ length: 6 }, () => `<div class="skel" style="height:204px"></div>`).join("");
  let list;
  try { list = await api(`/api/sessions?q=${encodeURIComponent(query)}`); } catch { return; }
  if (!query) { state.libCache = list; $("libCount").textContent = list.length || ""; }
  if (filter === "starred") list = list.filter((s) => s.starred);
  if (filter === "kit") list = list.filter((s) => s.has_kit);
  const by = { new: (a, b) => b.id.localeCompare(a.id), old: (a, b) => a.id.localeCompare(b.id), long: (a, b) => b.audio_s - a.audio_s, az: (a, b) => a.title.localeCompare(b.title) };
  list.sort(by[sort]);
  $("libTitle").textContent = query ? `${plural(list.length, "result")} for “${query}”` : "My lectures";

  const html = list.map((s, i) => `
    <article class="card glass" data-id="${s.id}" tabindex="0" role="link" aria-label="${esc(s.title)}" style="animation-delay:${Math.min(i, 12) * 35}ms">
      <button class="star ${s.starred ? "on" : ""}" data-star="${s.id}" aria-label="${s.starred ? "Unstar" : "Star"}" aria-pressed="${s.starred}">${icon("star")}</button>
      <div class="top"><span class="eyebrow">${esc(fmtDate(s.created || idDate(s.id)))}</span></div>
      <h3>${esc(s.title)}</h3>
      <p class="snip">${highlight(s.snippet || "No speech captured.", query)}</p>
      <div class="meta">
        ${s.live ? `<span class="chip bad"><span class="dot"></span>Live</span>` : ""}
        <span class="chip">${mins(s.audio_s)}</span><span class="chip">${plural(s.lines, "line")}</span>
        ${s.languages.map((l) => `<span class="chip accent"><span class="indic" lang="${isoLang[l]}">${esc(langNative(l) || langName(l))}</span></span>`).join("")}
        ${s.has_kit ? `<span class="chip good">${icon("sparkles")}Kit</span>` : ""}
      </div>
    </article>`).join("");
  const newCard = !query && filter === "all" ? `<a class="card glass new" href="#/live"><div><div class="plus">+</div><b>New lecture</b><div class="muted" style="font-size:12.5px;margin-top:4px">Captions, translation &amp; notes</div></div></a>` : "";
  cards.innerHTML = newCard + html || `<div class="empty-state"><div><div class="big">🔎</div><b style="color:var(--ink)">Nothing here yet</b><p>${query ? "No lecture mentions that — try another word." : filter === "starred" ? "Star a lecture to pin it here." : "Build a study kit from any lecture."}</p></div></div>`;
  $$(".card[data-id]", cards).forEach((c) => {
    tilt(c, 6);
    c.onclick = (e) => { if (!e.target.closest("[data-star]")) location.hash = `#/note/${c.dataset.id}`; };
    c.onkeydown = (e) => { if (e.key === "Enter") location.hash = `#/note/${c.dataset.id}`; };
  });
  $$("[data-star]", cards).forEach((b) => (b.onclick = async (e) => {
    e.stopPropagation();
    const on = !b.classList.contains("on");
    b.classList.toggle("on", on);
    await api(`/api/sessions/${b.dataset.star}`, { method: "PATCH", body: JSON.stringify({ starred: on }) }).catch((err) => toast(err.message, "err"));
    if (filter === "starred") renderLibrary();
  }));
}

// ================================================================== lecture view
let note = null, tab = "summary", deckIdx = 0, quiz = { know: 0, again: 0 }, chat = "";

function initNote() {
  $("noteTitle").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); e.target.blur(); } };
  $("noteTitle").onblur = async () => {
    const t = $("noteTitle").textContent.trim();
    if (!note || !t || t === note.title) { $("noteTitle").textContent = note?.title || ""; return; }
    try { note.title = (await api(`/api/sessions/${note.id}`, { method: "PATCH", body: JSON.stringify({ title: t }) })).title; toast("Renamed"); }
    catch (e) { toast(e.message, "err"); }
  };
  $("noteStar").onclick = async () => {
    if (!note) return;
    note.starred = !note.starred;
    $("noteStar").classList.toggle("on", note.starred);
    await api(`/api/sessions/${note.id}`, { method: "PATCH", body: JSON.stringify({ starred: note.starred }) }).catch(() => {});
  };
  $("deleteBtn").onclick = async () => {
    if (!note) return;
    const ok = await modal({ title: "Delete this lecture?", body: `“${esc(note.title)}” and its study kit will be removed from this laptop. This can't be undone.`, ok: "Delete", danger: true });
    if (!ok) return;
    try { await api(`/api/sessions/${note.id}`, { method: "DELETE" }); toast("Deleted"); location.hash = "#/library"; }
    catch (e) { toast(e.message, "err"); }
  };
  $("tSearch").oninput = () => filterTranscript($("tSearch").value.trim());
  $$(".tab").forEach((t) => (t.onclick = () => { tab = t.dataset.tab; renderKit(); }));
  $("askForm").onsubmit = (e) => { e.preventDefault(); ask($("q").value.trim()); };
  document.addEventListener("keydown", (e) => {
    if (tab !== "cards" || !document.querySelector('[data-view="note"].on') || e.target.closest("input,[contenteditable],select,textarea")) return;
    if (e.key === "ArrowRight") $("next")?.click();
    if (e.key === "ArrowLeft") $("prev")?.click();
    if (e.key === " ") { e.preventDefault(); document.querySelector(`.fc[data-i="${deckIdx}"]`)?.classList.toggle("flip"); }
  });
}

function filterTranscript(q) {
  $$(".tline", $("transcript")).forEach((row) => {
    const en = row.querySelector(".en"), tr = row.querySelector(".tr");
    const hit = !q || (row.dataset.text || "").toLowerCase().includes(q.toLowerCase());
    row.classList.toggle("hidden", !hit);
    en.innerHTML = highlight(en.dataset.raw, q);
    if (tr) tr.innerHTML = highlight(tr.dataset.raw, q);
  });
  $$("#keywords .chip").forEach((c) => c.classList.toggle("on", c.dataset.kw === q));
}

export async function openNote(id) {
  try { note = await api(`/api/sessions/${id}`); }
  catch (e) { toast(e.message, "err"); location.hash = "#/library"; return; }
  tab = "summary"; deckIdx = 0; quiz = { know: 0, again: 0 }; chat = "";
  $("noteDate").textContent = fmtDate(note.created || idDate(note.id), { weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });
  $("noteTitle").textContent = note.title;
  $("noteStar").classList.toggle("on", !!note.starred);
  const st = note.stats;
  $("noteChips").innerHTML = `<span class="chip">${mins(st.audio_s)}</span><span class="chip">${st.words.toLocaleString()} words</span>` +
    st.languages.map((l) => `<span class="chip accent"><span class="indic" lang="${isoLang[l]}">${esc(langNative(l) || langName(l))}</span></span>`).join("") +
    (st.rtf ? `<span class="chip good" title="Processing time ÷ audio time">${Math.max(1, Math.round(1 / st.rtf))}× real-time</span>` : "");
  $("exportBtn").href = `/api/sessions/${note.id}/export`;
  $("tSearch").value = "";
  const text = note.lines.map((l) => l.text).join(" ");
  $("keywords").innerHTML = keywords(text).map((k) => `<button class="chip" data-kw="${esc(k)}">${esc(k)}</button>`).join("");
  $$("#keywords .chip").forEach((c) => (c.onclick = () => {
    const q = $("tSearch").value === c.dataset.kw ? "" : c.dataset.kw;
    $("tSearch").value = q; filterTranscript(q);
  }));
  $("transcript").innerHTML = note.lines.length ? note.lines.map((l) => `
    <div class="tline" data-text="${esc(l.text + " " + (l.translation || ""))}"><span class="ts">${fmtT(l.start_s)}</span>
      <div><div class="en" data-raw="${esc(l.text)}">${esc(l.text)}</div>${l.translation ? `<div class="tr indic" lang="${isoLang[l.target] || ""}" data-raw="${esc(l.translation)}">${esc(l.translation)}</div>` : ""}</div></div>`).join("")
    : `<div class="feed-empty">No speech was captured in this lecture.</div>`;
  renderKit();
  applyLiquidGlass();
}

function renderKit() {
  $$(".tab").forEach((t) => t.classList.toggle("on", t.dataset.tab === tab));
  $("askForm").hidden = tab !== "ask";
  const k = note?.studykit, box = $("kit");
  if (tab === "ask") {
    const sug = ["Summarise this lecture in 3 lines", "What are the key definitions?", "What might come in the exam?"];
    box.innerHTML = `<div class="chat" id="chat">${chat || `<div class="bubble a">Ask me anything about this lecture — I only use what was said, and I run entirely on this laptop.</div>
      <div class="suggest">${sug.map((s) => `<button class="chip" data-sug="${esc(s)}">${esc(s)}</button>`).join("")}</div>`}</div>`;
    $$("[data-sug]", box).forEach((b) => (b.onclick = () => ask(b.dataset.sug)));
    setTimeout(() => $("q").focus(), 50);
    return;
  }
  if (!k) {
    box.innerHTML = `<div class="kit-cta"><div><div class="sparkle">✦</div><b style="color:var(--ink);font-size:16px">Turn this lecture into a study kit</b>
      <p style="margin:8px 0 18px;line-height:1.6">Summary, key points, 3D flashcards and a glossary —<br>generated on-device in seconds.</p>
      <button class="btn primary" id="kitBtn">${icon("sparkles")}Build study kit</button></div></div>`;
    $("kitBtn").onclick = buildKit;
    return;
  }
  if (tab === "summary") {
    box.innerHTML = `<p class="muted" style="font-size:12px;margin-top:0">${icon("brain", "").replace("<svg", '<svg style="width:13px;height:13px;vertical-align:-2px"')} ${esc(k.engine === "extractive" ? "Offline summariser" : k.engine)} · ${k.latency_s}s · <a href="#" id="rebuild" style="color:inherit">rebuild</a></p>
      <p style="color:var(--ink);font-size:15px">${esc(k.summary)}</p>${k.key_points?.length ? `<h4 class="eyebrow">Key points</h4><ul>${k.key_points.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>` : ""}`;
    $("rebuild").onclick = (e) => { e.preventDefault(); buildKit(); };
  } else if (tab === "terms") {
    box.innerHTML = k.terms?.length ? k.terms.map((t) => `<div class="term"><b>${esc(t.term)}</b><span>${esc(t.meaning || "—")}</span></div>`).join("") : `<div class="feed-empty">No terms extracted.</div>`;
  } else if (tab === "cards") renderDeck(k.flashcards || []);
}

function renderDeck(cards) {
  const box = $("kit");
  if (!cards.length) { box.innerHTML = `<div class="feed-empty">No flashcards yet.</div>`; return; }
  deckIdx = Math.min(deckIdx, cards.length - 1);
  box.innerHTML = `<div class="deck" id="deck">${cards.map((c, i) => `
      <div class="fc" data-i="${i}" role="button" tabindex="${i === deckIdx ? 0 : -1}" aria-label="Flashcard ${i + 1}: ${esc(c.q)}">
        <div class="face front"><small>Question ${i + 1} of ${cards.length}</small>${esc(c.q)}<span class="hint">Tap or press Space to flip</span></div>
        <div class="face back"><small>Answer</small><b>${esc(c.a)}</b></div>
      </div>`).join("")}</div>
    <div class="deck-nav"><button class="btn icon sm" id="prev" aria-label="Previous">${icon("back")}</button><span class="pos" id="deckPos"></span>
      <button class="btn icon sm" id="next" aria-label="Next" style="transform:scaleX(-1)">${icon("back")}</button></div>
    <div class="quiz-score"><button class="btn sm" id="again">↺ Again <span class="muted" id="againN">${quiz.again}</span></button><button class="btn sm" id="know">✓ Knew it <span class="muted" id="knowN">${quiz.know}</span></button></div>`;
  const layout = () => {
    $$(".fc", box).forEach((el) => {
      const d = +el.dataset.i - deckIdx;
      el.classList.remove("flip");
      el.style.zIndex = 100 - Math.abs(d);
      el.style.opacity = d < 0 || d > 3 ? 0 : 1 - d * 0.2;
      el.style.pointerEvents = d === 0 ? "auto" : "none";
      el.tabIndex = d === 0 ? 0 : -1;
      el.style.transform = d < 0 ? "translateX(-115%) rotateY(-30deg)" : `translateY(${d * 13}px) translateZ(${-d * 60}px) rotateX(${d * 2}deg)`;
    });
    $("deckPos").textContent = `${deckIdx + 1} / ${cards.length}`;
  };
  $$(".fc", box).forEach((el) => {
    el.onclick = () => el.classList.toggle("flip");
    el.onkeydown = (e) => { if (e.key === "Enter") el.classList.toggle("flip"); };
  });
  $("prev").onclick = () => { deckIdx = Math.max(0, deckIdx - 1); layout(); };
  $("next").onclick = () => { deckIdx = Math.min(cards.length - 1, deckIdx + 1); layout(); };
  const mark = (k) => { quiz[k]++; $("knowN").textContent = quiz.know; $("againN").textContent = quiz.again; if (deckIdx < cards.length - 1) { deckIdx++; layout(); } else toast(`Deck done — you knew ${quiz.know} of ${quiz.know + quiz.again}`); };
  $("know").onclick = () => mark("know");
  $("again").onclick = () => mark("again");
  layout();
}

async function buildKit() {
  $("kit").innerHTML = `<div class="kit-cta"><div><div class="sparkle">✦</div><div class="hearing" style="justify-content:center"><i></i><i></i><i></i></div>
    <p>Reading the lecture on-device…<br><span class="muted">The first run loads the model.</span></p></div></div>`;
  try { note.studykit = await post(`/api/sessions/${note.id}/studykit`); toast("Study kit ready"); }
  catch (e) { toast(e.message, "err"); }
  renderKit();
}

async function ask(q) {
  if (!q || !note) return;
  if (tab !== "ask") { tab = "ask"; renderKit(); }
  $("q").value = "";
  const box = $("chat");
  box.querySelector(".suggest")?.remove();
  box.insertAdjacentHTML("beforeend", `<div class="bubble q">${esc(q)}</div><div class="bubble a" id="pending"><span class="hearing"><i></i><i></i><i></i></span></div>`);
  $("kit").scrollTop = 1e9;
  try {
    const r = await post(`/api/sessions/${note.id}/ask`, { question: q });
    $("pending").outerHTML = `<div class="bubble a">${esc(r.answer)}<small>${esc(r.engine === "retrieval" ? "Found in transcript" : r.engine)} · ${r.latency_s}s</small></div>`;
  } catch (err) { $("pending").outerHTML = `<div class="bubble a">${esc(err.message)}</div>`; }
  chat = box.innerHTML;
  $("kit").scrollTop = 1e9;
}
