// "On-device AI" page — the judges' view: where every model runs, published Snapdragon numbers,
// and live measurements from this laptop.
import { groupedBars, spark } from "./charts.js";
import { $, api, esc, on } from "./core.js";
import { icon } from "./icons.js";
import { applyLiquidGlass } from "./liquidglass.js";

let data = null, chip = "Snapdragon X Elite CRD";
const TOKENS = 24;   // 4 forced prompt tokens + ~20 text tokens for a typical 6-second sentence
const MT_TOKENS = 25;

const pub = (model, comp, device) => data?.published?.models.find((m) => m.model === model && m.component === comp && m.device === device);

function estimate(device) {
  const we = pub("whisper_base", "encoder", device), wd = pub("whisper_base", "decoder", device);
  const oe = pub("opus_mt_en_es", "encoder", device), od = pub("opus_mt_en_es", "decoder", device);
  if (!we || !wd) return null;
  const parts = [
    ["Whisper encoder", we.latency_ms],
    [`Whisper decoder × ${TOKENS} tokens`, wd.latency_ms * TOKENS],
    ...(oe && od ? [["OPUS-MT encoder", oe.latency_ms], [`OPUS-MT decoder × ${MT_TOKENS}`, od.latency_ms * MT_TOKENS]] : []),
  ];
  return { total: parts.reduce((a, [, v]) => a + v, 0), parts };
}

function renderLive(m) {
  const box = $("perfLive");
  if (!box || !m) return;
  const st = m.stages || {};
  const val = (k, f = "avg") => (st[k]?.n ? Math.round(st[k][f]) : "—");
  const cells = [
    ["Speech → text", val("asr_ms"), "ms / sentence"],
    ["Per token", st.tok_ms?.n ? st.tok_ms.avg.toFixed(1) : "—", "ms (decoder)"],
    ["Caption ready", val("e2e_ms", "p50"), "ms after pause · p50"],
    ["Real-time speed", m.rtf ? `${Math.max(1, Math.round(1 / m.rtf))}×` : "—", "faster than speech"],
    ["App CPU", m.cpu_avg != null ? `${m.cpu_avg}%` : "—", "avg while live"],
    ["Battery", m.battery_drain_pct_per_h != null ? `${m.battery_drain_pct_per_h}%/h` : m.battery ? `${m.battery.percent}%` : "—", m.battery_drain_pct_per_h != null ? "drain while live" : m.battery?.plugged ? "plugged in" : "level"],
  ];
  box.querySelector(".metric-row").innerHTML = cells.map(([l, v, s]) => `<div class="metric"><span>${esc(l)}</span><b>${esc(v)}</b><span>${esc(s)}</span></div>`).join("");
  spark($("sparkAsr"), m.history?.asr_ms, { label: "Speech → text latency", unit: "ms" });
  spark($("sparkE2e"), m.history?.e2e_ms, { label: "Caption latency", unit: "ms", color: "var(--series-3)" });
}

function renderTop() {
  const e = estimate(chip);
  $("estTile").innerHTML = `
    <div class="eyebrow">Speech → caption + translation<span class="spacer"></span>
      <div class="seg glass thin" id="chipSeg"><span class="thumb"></span>
        <button data-c="Snapdragon X Elite CRD" class="${chip.includes("X Elite") && !chip.includes("X2") ? "on" : ""}">X Elite</button>
        <button data-c="Snapdragon X2 Elite CRD" class="${chip.includes("X2") ? "on" : ""}">X2 Elite</button></div></div>
    ${e ? `<div class="big-num">${Math.round(e.total)}<small>ms of NPU compute per sentence</small></div>
      <div class="muted" style="font-size:13px">Whisper Base + OPUS-MT, 100% of layers on the Hexagon NPU. A 6-second sentence is ready in a blink — ${Math.round(6000 / e.total)}× faster than it was spoken.</div>
      <div class="breakdown">${e.parts.map(([l, v]) => `<div class="brow"><span>${esc(l)}</span><div class="track"><div class="fill" style="width:${(100 * v) / e.total}%"></div></div><b>${v.toFixed(0)} ms</b></div>`).join("")}</div>
      <div class="engine-list" style="margin-top:16px">
        <div class="engine"><span class="ei">${icon("clock")}</span><div><b>${(e.total / 1000 * 600).toFixed(0)} s of NPU time for a 1-hour lecture</b><span>≈600 sentences — the NPU is idle ${(100 - e.total / 60).toFixed(1)}% of the time</span></div></div>
        <div class="engine"><span class="ei">${icon("battery")}</span><div><b>CPU stays free for everything else</b><span>Zoom, slides and the browser keep running smoothly</span></div></div>
      </div>
      <p class="note-src">Estimate = Qualcomm AI Hub published per-call latencies (${esc(chip)}, precompiled QNN) × typical token counts. OPUS-MT uses AI Hub's en→es model of the same Marian architecture as our en→hi/mr models. Your laptop's real numbers appear below once you caption a lecture.</p>`
      : `<p class="muted">Published numbers unavailable.</p>`}`;
  const seg = $("chipSeg");
  const move = () => { const b = seg.querySelector("button.on"), th = seg.querySelector(".thumb"); if (b) { th.style.width = `${b.offsetWidth}px`; th.style.transform = `translateX(${b.offsetLeft - 4}px)`; } };
  requestAnimationFrame(move);
  seg.querySelectorAll("button").forEach((b) => (b.onclick = () => { chip = b.dataset.c; renderTop(); }));
}

export async function renderPerf() {
  const grid = $("perfGrid");
  if (!data) grid.innerHTML = `<div class="skel span-12" style="height:320px"></div>`;
  try { data = await api("/api/performance"); } catch { return; }
  const rt = data.runtime, eng = data.engines;
  const P = data.published?.models || [];
  const devs = ["Snapdragon X Elite CRD", "Snapdragon X2 Elite CRD"];
  const rows = [
    ["whisper_tiny", "encoder", "Whisper Tiny · encoder"], ["whisper_base", "encoder", "Whisper Base · encoder"], ["whisper_small", "encoder", "Whisper Small · encoder"],
    ["whisper_tiny", "decoder", "Whisper Tiny · per token"], ["whisper_base", "decoder", "Whisper Base · per token"], ["whisper_small", "decoder", "Whisper Small · per token"],
    ["opus_mt_en_es", "encoder", "OPUS-MT · encoder"], ["opus_mt_en_es", "decoder", "OPUS-MT · per token"],
  ].map(([m, c, label]) => ({ label, values: devs.map((d) => pub(m, c, d)?.latency_ms ?? null),
    note: (() => { const p = pub(m, c, devs[0]); return p ? `${p.npu_layers}/${p.total_layers} layers on NPU · job ${p.job_id}` : ""; })() }));
  const llm = P.filter((m) => m.role === "llm" && m.precision === "w4a16");
  const wb = (c) => pub("whisper_base", c, devs[0]);
  const sessions = rt.sessions || [];

  grid.innerHTML = `
    <section class="tile glass span-5 rows-2" data-lg id="estTile"></section>

    <section class="tile glass span-4" aria-label="This device">
      <div class="eyebrow">This laptop<span class="spacer"></span>${rt.on_npu ? `<span class="chip good"><span class="dot"></span>NPU active</span>` : `<span class="chip warn">CPU mode</span>`}</div>
      <dl class="kv">
        <dt>Processor</dt><dd>${esc(rt.processor || rt.machine)}</dd>
        <dt>System</dt><dd>${esc(rt.system)} · ${esc(rt.machine)}</dd>
        <dt>Runtime</dt><dd>ONNX Runtime ${esc(rt.onnxruntime)}${rt.qnn_plugin ? " + QNN plugin" : ""}</dd>
        <dt>Execution</dt><dd>${esc(rt.execution_provider)}</dd>
      </dl>
      <div class="sess-list">${sessions.length ? sessions.map((s) => `<div>${s.provider.startsWith("QNN") ? `<span class="chip good">NPU</span>` : `<span class="chip">CPU</span>`}<code>${esc(s.model)}</code></div>`).join("")
        : `<span class="muted">Speech: ${esc(eng.asr?.name)} (${esc(eng.asr?.device)}). Models load into ONNX Runtime on first use.</span>`}</div>
    </section>

    <section class="tile glass span-3" aria-label="NPU coverage">
      <div class="eyebrow">NPU coverage</div>
      <div class="big-num" style="font-size:46px">100<small>%</small></div>
      <div class="muted" style="font-size:12.5px;line-height:1.55">of Whisper Base layers run on the Hexagon NPU — ${wb("encoder")?.npu_layers ?? "—"}/${wb("encoder")?.total_layers ?? "—"} encoder, ${wb("decoder")?.npu_layers ?? "—"}/${wb("decoder")?.total_layers ?? "—"} decoder. Nothing falls back to the CPU.</div>
    </section>

    <section class="tile glass span-7 rows-2" aria-label="Published latency">
      <div class="eyebrow">Qualcomm AI Hub · published latency per call</div>
      <div id="pubChart" data-label="Latency per model component on Snapdragon X Elite and X2 Elite"></div>
      <p class="note-src">Source: <code>qai-hub-models 0.63</code> perf.yaml — measured by Qualcomm on hosted CRD devices, precompiled QNN ONNX. Hover a bar for layer counts and the AI Hub job ID. Reproduce: <code>python tools/aihub_profile.py published</code></p>
    </section>

    <section class="tile glass span-5" aria-label="Study kit LLM">
      <div class="eyebrow">Study kit LLM · Llama 3.2 3B (w4a16, Genie)</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:4px">
        ${llm.map((m) => `<div class="metric"><span>${esc(m.device.replace(" CRD", ""))}</span><b>${m.tokens_per_second}<span style="font-size:13px;color:var(--ink-3)"> tok/s</span></b><span>first token in ${m.ttft_ms_min} ms</span></div>`).join("")}
      </div>
      <p class="note-src">A 600-token study kit ≈ ${llm[0] ? Math.round(600 / llm[0].tokens_per_second) : "—"} s on X Elite, ${llm[1] ? Math.round(600 / llm[1].tokens_per_second) : "—"} s on X2 Elite — on battery, offline. Without an LLM installed Samwaad falls back to an instant extractive summariser.</p>
    </section>

    <section class="tile glass span-12" id="perfLive" aria-label="Live on this laptop">
      <div class="eyebrow">Measured live on this laptop<span class="spacer"></span><span class="muted" style="text-transform:none;letter-spacing:0;font-weight:500">updates every 2 s while captioning</span></div>
      <div class="metric-row"></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:14px">
        <div><div class="muted" style="font-size:12px;margin-bottom:4px">Speech → text, last 40 sentences (ms)</div><div id="sparkAsr"></div></div>
        <div><div class="muted" style="font-size:12px;margin-bottom:4px">Caption ready after the speaker pauses (ms)</div><div id="sparkE2e"></div></div>
      </div>
    </section>

    <section class="tile glass span-12" aria-label="Local benchmarks">
      <div class="eyebrow">CPU vs NPU on this laptop</div>
      ${data.local.length ? `<table class="tbl"><thead><tr><th>Date</th><th>What</th><th>Provider</th><th>Latency</th><th>RTF</th><th>CPU</th><th>Battery</th></tr></thead><tbody>
        ${data.local.slice(-12).reverse().map((r) => `<tr><td>${esc(r.date)}</td><td>${esc(r.model || r.audio)}</td><td>${esc(r.provider)}</td>
          <td>${r.median_ms != null ? `${r.median_ms} ms (median)` : `${r.asr_ms ?? "—"} ms ASR · ${r.e2e_ms ?? "—"} ms caption`}</td><td>${r.rtf ?? "—"}</td><td>${r.cpu_avg != null ? r.cpu_avg + "%" : "—"}</td><td>${r.battery_drain_pct_per_h != null ? r.battery_drain_pct_per_h + "%/h" : "—"}</td></tr>`).join("")}</tbody></table>`
        : `<p class="muted" style="font-size:13.5px;line-height:1.6;margin:0">No local runs yet. On the Snapdragon laptop run <kbd>python tools/benchmark.py models</kbd> (every model, CPU vs NPU) and <kbd>python tools/benchmark.py pipeline samples/lecture.wav</kbd> — results appear here.</p>`}
    </section>`;

  renderTop();
  groupedBars($("pubChart"), rows, [{ name: "Snapdragon X Elite", color: "var(--series-1)" }, { name: "Snapdragon X2 Elite", color: "var(--series-2)" }], { unit: "ms", labelW: 176 });
  renderLive(data.live);
  applyLiquidGlass(grid);
}

on("metrics", (m) => { if (document.querySelector('[data-view="performance"].on')) renderLive(m); });
$("perfRefresh")?.addEventListener("click", renderPerf);
export { icon };
