"""`python -m samwaad doctor` — one screen that says whether this PC is ready, and how to fix it.

Also served at /api/doctor for the in-app System check (Settings → System).
"""
from __future__ import annotations

import importlib.util
import json
import platform
import shutil
import sys
import urllib.request
from pathlib import Path

from .config import ROOT, resource  # noqa: F401
from .runtime import describe, npu_available



def _check(name, ok, detail, fix="", level=None):
    return {"name": name, "status": level or ("ok" if ok else "warn"), "detail": detail, "fix": fix}


def run_checks(cfg: dict) -> list[dict]:
    rt = describe(cfg.get("runtime"))
    arch = platform.machine().upper()
    is_arm = arch in ("ARM64", "AARCH64")
    out = [
        _check("Processor", True, f"{rt['processor']} · {arch} · {rt['system']}"),
        _check("Python build", not (platform.system() == "Windows" and not is_arm and "ARM" in (platform.processor() or "").upper()),
               f"Python {rt['python']} ({platform.architecture()[0]}, {arch})",
               "On Snapdragon, install the ARM64 Python from python.org — x64 Python runs emulated and can't see the NPU."),
        _check("Snapdragon NPU (QNN)", npu_available(),
               f"onnxruntime {rt['onnxruntime']} · providers: {', '.join(rt['available'])}",
               "pip install onnxruntime-qnn   (Snapdragon X only). Samwaad runs on CPU until then.",
               level=None if npu_available() else ("warn" if is_arm else "info")),
    ]

    vad = Path(cfg["vad"]["model_path"])
    out.append(_check("Voice activity model", vad.exists(), "Silero VAD (CPU, 2 MB)" if vad.exists() else "missing — energy VAD in use",
                      "python tools/fetch_models.py"))

    wdir = Path(cfg["asr"].get("model", "models/whisper_base"))
    wdir = wdir if wdir.is_absolute() else ROOT / wdir
    has_w = wdir.exists() and any(wdir.rglob("*.onnx"))
    fw = importlib.util.find_spec("faster_whisper") is not None
    out.append(_check("Speech recognition", has_w or fw,
                      "Whisper (AI Hub export) → NPU" if has_w else ("faster-whisper → CPU" if fw else "no ASR engine installed"),
                      "python tools/fetch_models.py   (downloads Qualcomm AI Hub's pre-compiled NPU Whisper on Snapdragon)",
                      level=None if has_w else ("warn" if fw else "error")))

    odir = Path(cfg.get("translate", {}).get("npu_models") or ROOT / "models" / "opus_mt")
    opus = sorted(p.name for p in odir.iterdir() if p.is_dir()) if odir.exists() else []
    it2 = importlib.util.find_spec("IndicTransToolkit") is not None
    out.append(_check("Translation", bool(opus) or it2,
                      (f"NPU: {', '.join(opus)}" if opus else "NPU: none") + (" · IndicTrans2 (CPU) ready" if it2 else ""),
                      "python tools/export_opus_mt.py hi mr   and/or   pip install IndicTransToolkit",
                      level=None if (opus or it2) else "warn"))

    llm = cfg.get("llm", {})
    if llm.get("backend") == "http":
        ok, detail = False, llm.get("url")
        try:
            base = llm["url"].split("/v1/")[0]
            urllib.request.urlopen(base + "/v1/models", timeout=1.5).read(200)
            ok, detail = True, f"{llm.get('model')} via {base}"
        except Exception:
            detail = f"no local LLM server at {llm.get('url')} — study kit uses the offline extractive fallback"
        out.append(_check("Study-kit LLM", ok, detail, "Install Ollama (ARM64) → ollama pull llama3.2:3b, or use Genie with AI Hub Llama 3.2 3B"))
    elif llm.get("backend") == "genie":
        ok = shutil.which("genie-t2t-run") is not None and Path(llm.get("genie_config", "")).exists()
        out.append(_check("Study-kit LLM", ok, "Genie + AI Hub Llama 3.2 3B (NPU)" if ok else "genie-t2t-run or genie_config missing",
                          "See docs/NPU.md → LLM"))
    else:
        out.append(_check("Study-kit LLM", True, "extractive fallback (no LLM)", level="info"))

    try:
        import sounddevice as sd
        mics = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
        out.append(_check("Microphone", bool(mics), f"{len(mics)} input device(s)" if mics else "no input device found",
                          "Plug in / enable a microphone, or use Demo mode with a WAV file"))
    except Exception as e:
        out.append(_check("Microphone", False, f"audio backend unavailable ({e.__class__.__name__})", "pip install sounddevice"))

    store = Path(cfg["store"]["dir"])
    try:
        store.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(store).free / 2**30
        out.append(_check("Storage", free > 1, f"{free:.1f} GB free for lectures", "Free up disk space"))
    except Exception as e:
        out.append(_check("Storage", False, str(e), "Check folder permissions", level="error"))

    out.append(_check("Network", True, "Not required after setup — everything runs on this PC", level="info"))
    return out


def print_report(cfg: dict) -> int:
    icons = {"ok": "✅", "warn": "⚠️ ", "info": "ℹ️ ", "error": "❌"}
    checks = run_checks(cfg)
    print("\n  Samwaad · system check\n")
    for c in checks:
        print(f"  {icons[c['status']]} {c['name']:<22} {c['detail']}")
        if c["status"] in ("warn", "error") and c["fix"]:
            print(f"      ↳ {c['fix']}")
    bad = sum(c["status"] == "error" for c in checks)
    print("\n  " + ("Ready. Run: python -m samwaad serve" if not bad else f"{bad} blocking issue(s) above.") + "\n")
    return 1 if bad else 0


if __name__ == "__main__":  # pragma: no cover
    from .config import load_config
    sys.exit(print_report(load_config()))
