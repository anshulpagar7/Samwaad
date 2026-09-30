"""Download everything Samwaad needs, once — afterwards the app runs with Wi-Fi off.

  python tools/fetch_models.py              # auto: NPU assets on Snapdragon, CPU models elsewhere
  python tools/fetch_models.py --npu        # force-download the Snapdragon NPU Whisper assets
  python tools/fetch_models.py --quality    # also IndicTrans2 (best-quality translation, ~0.9 GB)
  python tools/fetch_models.py --cpu        # also faster-whisper (CPU fallback / benchmark baseline)

NPU speech recognition comes pre-compiled from Qualcomm AI Hub's model zoo
(`qai-hub-models fetch whisper_base --runtime precompiled_qnn_onnx`) — no AI Hub account needed.
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SILERO_URL = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"


def snapdragon_chipset() -> str | None:
    """'qualcomm-snapdragon-x2-elite' / 'qualcomm-snapdragon-x-elite' on Snapdragon PCs, else None."""
    if platform.machine().upper() not in ("ARM64", "AARCH64"):
        return None
    name = platform.processor()
    if sys.platform == "win32":
        try:
            name = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"],
                                  capture_output=True, text=True, timeout=10).stdout
        except Exception:
            pass
    name = (name or "").upper()
    if "SNAPDRAGON" not in name and "QUALCOMM" not in name and "ORYON" not in name:
        return None
    return "qualcomm-snapdragon-x2-elite" if "X2" in name else "qualcomm-snapdragon-x-elite"


def step(msg):
    print(f"\n▸ {msg}")


def fetch_whisper_npu(model_id: str, chipset: str | None):
    out = ROOT / "models" / model_id
    if out.exists() and any(out.rglob("*.onnx")):
        print(f"  already present: {out.relative_to(ROOT)}")
        return
    cli = shutil.which("qai-hub-models")
    if not cli:
        subprocess.run([sys.executable, "-m", "pip", "install", "qai_hub_models_cli"], check=True)
        cli = shutil.which("qai-hub-models") or "qai-hub-models"
    cmd = [cli, "fetch", model_id, "--runtime", "precompiled_qnn_onnx", "--precision", "float", "-o", str(out)]
    if chipset:
        cmd += ["--chipset", chipset]
    print("  $", " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0 and chipset:  # retry without the chipset filter (universal asset)
        subprocess.run(cmd[:-2], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--npu", action="store_true", help="download NPU Whisper even if this isn't a Snapdragon PC")
    ap.add_argument("--chipset", default=None, help="override chipset, e.g. qualcomm-snapdragon-x-elite")
    ap.add_argument("--whisper", default="whisper_base", help="whisper_tiny | whisper_base | whisper_small")
    ap.add_argument("--cpu", action="store_true", help="also download faster-whisper (CPU)")
    ap.add_argument("--quality", action="store_true", help="also download IndicTrans2 (CPU, best quality)")
    args = ap.parse_args()

    from samwaad.config import load_config
    cfg = load_config()
    chipset = args.chipset or snapdragon_chipset()
    print(f"Samwaad model setup · {platform.machine()} · " + (f"Snapdragon ({chipset})" if chipset else "no Snapdragon NPU detected"))

    step("Voice activity detection (Silero VAD, 2 MB)")
    vad_path = Path(cfg["vad"]["model_path"])
    if not vad_path.exists():
        vad_path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(SILERO_URL, vad_path)
    print("  ✓", vad_path.relative_to(ROOT))

    step("Tokenizers (Whisper + OPUS-MT)")
    try:
        from transformers import AutoTokenizer, WhisperTokenizer
        WhisperTokenizer.from_pretrained(cfg["asr"].get("tokenizer", "openai/whisper-base"))
        for hf in ("Helsinki-NLP/opus-mt-en-hi", "Helsinki-NLP/opus-mt-en-mr", "Helsinki-NLP/opus-mt-en-dra",
                   "Helsinki-NLP/opus-mt-en-ml", "Helsinki-NLP/opus-mt-en-inc"):
            AutoTokenizer.from_pretrained(hf)
        print("  ✓ cached")
    except Exception as e:
        print(f"  ! tokenizers not cached ({e}) — pip install transformers sentencepiece")

    if chipset or args.npu:
        step(f"Speech recognition for the NPU — {args.whisper}, pre-compiled by Qualcomm AI Hub")
        fetch_whisper_npu(args.whisper, chipset)

    if args.cpu or not (chipset or args.npu):
        step(f"Speech recognition for CPU — faster-whisper {cfg['asr'].get('cpu_model', 'base')}")
        from faster_whisper import WhisperModel
        WhisperModel(cfg["asr"].get("cpu_model", "base"), device="cpu", compute_type="int8")
        print("  ✓")

    if args.quality:
        step("IndicTrans2 (best-quality translation, CPU)")
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        name = cfg["translate"]["quality_model"]
        AutoTokenizer.from_pretrained(name, trust_remote_code=True)
        AutoModelForSeq2SeqLM.from_pretrained(name, trust_remote_code=True)
        print("  ✓")

    opus = ROOT / "models" / "opus_mt"
    if not (opus.exists() and any(opus.iterdir())):
        print("\nℹ NPU translation: run  python tools/export_opus_mt.py hi mr dra  (needs a free AI Hub token)")
    print("\nAll set — you can turn Wi-Fi off now. Check everything with:  python -m samwaad doctor")


if __name__ == "__main__":
    main()
