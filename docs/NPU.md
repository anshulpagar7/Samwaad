# Getting every model onto the Snapdragon NPU

Samwaad opens every model through `samwaad/runtime.py::make_session`. On a Snapdragon X PC with
`onnxruntime-qnn` installed, that means the **QNN Execution Provider, HTP backend** — the Hexagon NPU.
`python -m samwaad status` / Settings → System check / the *On-device AI* page all show where each model landed.

## 0. Runtime

```powershell
pip install -r requirements.txt -r requirements-snapdragon.txt   # onnxruntime>=1.27 + onnxruntime-qnn>=2.6
python -m samwaad doctor
```
* `onnxruntime-qnn` 2.x is a **plugin EP**: Samwaad calls `ort.register_execution_provider_library("QNNExecutionProvider", onnxruntime_qnn.get_library_path())` once and binds sessions to the NPU ep-device with `add_provider_for_devices`.
* `onnxruntime-qnn` 1.x (QNN EP built in) is also supported — it's passed as a normal provider.
* Options used: `backend_path` = QnnHtp, `htp_performance_mode=burst`, `enable_htp_fp16_precision=1`, graph finalization O3.
* Use **ARM64 Python** (python.org "Windows installer (ARM64)"). x64 Python runs emulated and cannot load the QNN EP — `doctor` warns about this.

## 1. Speech recognition — Whisper (no AI Hub account needed)

Qualcomm publishes Whisper already compiled for Snapdragon X:
```powershell
python tools/fetch_models.py            # on Snapdragon this runs the command below automatically
qai-hub-models fetch whisper_base --runtime precompiled_qnn_onnx --precision float --chipset qualcomm-snapdragon-x-elite -o models/whisper_base
```
Use `--chipset qualcomm-snapdragon-x2-elite` on X2 machines (fetch_models detects this from the CPU name). `whisper_tiny` / `whisper_small` work too (`--whisper whisper_small`).

**I/O contract** implemented by `OnnxWhisperASR` (from `qai_hub_models.models.templates.hf_whisper`, v0.63):

| graph | inputs | outputs |
|---|---|---|
| encoder | `input_features` (1, 80, 3000) | `k_cache_cross_{i}` (H,1,d,1500), `v_cache_cross_{i}` (H,1,1500,d) |
| decoder | `input_ids` (1,1) int32, `attention_mask` (1,1,1,200) (−100 = masked), `k/v_cache_self_{i}_in`, `k/v_cache_cross_{i}`, `position_ids` (1,) int32 | `logits` (1,V,1,1), `k/v_cache_self_{i}_out` |

Greedy decoding with a forced `<|startoftranscript|><|en|><|transcribe|><|notimestamps|>` prompt, right-aligned
attention mask, timestamp/special tokens suppressed. dtypes are read from the graph, so fp16-I/O exports work unchanged.
`tests/test_npu_paths.py` runs this loop against ONNX graphs with exactly this signature (fp32 and fp16 I/O).
Check a real export with `python tools/inspect_onnx.py models/whisper_base/**/*.onnx`.

Published latency (Qualcomm AI Hub, X Elite): encoder 45.5 ms, decoder 3.8 ms/token, 100 % of layers on the NPU.

## 2. Translation — OPUS-MT on the NPU (free AI Hub token)

AI Hub ships Marian/OPUS-MT models (`opus_mt_en_es`, `opus_mt_en_zh` …) that run fully on the NPU. We reuse that exact
recipe (`templates.opus_mt`) for the Helsinki-NLP English→Indic models:

```powershell
pip install -r requirements-extras.txt        # qai-hub, qai-hub-models
qai-hub configure --api_token <token from workbench.aihub.qualcomm.com → Settings>
python tools/export_opus_mt.py hi mr dra --device "Snapdragon X Elite CRD"
```
| code | model | languages |
|---|---|---|
| hi | Helsinki-NLP/opus-mt-en-hi | Hindi |
| mr | Helsinki-NLP/opus-mt-en-mr | Marathi |
| ml | Helsinki-NLP/opus-mt-en-ml | Malayalam |
| dra | Helsinki-NLP/opus-mt-en-dra | Tamil, Telugu, Kannada (`>>tam<<`, `>>tel<<`, `>>kan<<`) |
| inc | Helsinki-NLP/opus-mt-en-inc | Bengali, Gujarati, Odia, Urdu (`>>ben<<` …) |

Exports land in `models/opus_mt/<model>/` and are picked up automatically (`translate.backend: hybrid`). Each export is
also profiled on AI Hub and appended to `benchmarks/aihub_results.md` with the job link.
If a language token isn't in a model's vocabulary, that language falls back to IndicTrans2 — never to the wrong language.

**Best quality**: Settings → Translation → *Best quality* routes every language to AI4Bharat IndicTrans2
(`pip install torch IndicTransToolkit`, `python tools/fetch_models.py --quality`). It runs on the CPU.

## 3. Study kit — Llama 3.2 3B via Genie

Export or fetch the Genie bundle for Llama 3.2 3B Instruct from AI Hub (`qai-hub-models` → `llama_v3_2_3b_instruct`, Genie
runtime), put it in `models/llama_v3_2_3b_instruct/`, then in `config.yaml`:
```yaml
llm:
  backend: genie
  genie_config: models/llama_v3_2_3b_instruct/genie_config.json
```
Published: 11.3 tok/s, first token 119 ms on X Elite (w4a16). Alternatively any local OpenAI-compatible server
(`backend: http`, e.g. Ollama for ARM64 or AnythingLLM). With no LLM, the study kit uses an instant offline extractive summariser.

## 4. Voice activity detection

Silero VAD v5 (2 MB) deliberately stays on the CPU: ~0.1 ms per 32 ms frame — NPU dispatch would cost more than the compute.

## 5. Proving it

* **Task Manager → Performance → NPU** shows the NPU graph moving while you speak.
* **On-device AI page**: which model is on which provider, AI Hub numbers, live latency / CPU / battery.
* `python tools/benchmark.py models` → CPU vs NPU median latency for every model; `pipeline` → end-to-end metrics.
