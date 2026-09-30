"""Compile OPUS-MT English -> Indian-language translators for the Snapdragon NPU on Qualcomm AI Hub.

AI Hub publishes Marian/OPUS-MT models (opus_mt_en_es, opus_mt_en_zh …) that run 100 % on the
NPU (≈3–4 ms per encoder/decoder call on Snapdragon X Elite). This script reuses exactly that
recipe — `qai_hub_models.models.templates.opus_mt` — for the Helsinki-NLP English→Indic models:

  hi   Helsinki-NLP/opus-mt-en-hi    Hindi
  mr   Helsinki-NLP/opus-mt-en-mr    Marathi
  ml   Helsinki-NLP/opus-mt-en-ml    Malayalam
  dra  Helsinki-NLP/opus-mt-en-dra   Tamil · Telugu · Kannada (target token >>tam<< etc.)
  inc  Helsinki-NLP/opus-mt-en-inc   Bengali · Gujarati · Odia · Urdu … (>>ben<< etc.)

Needs: pip install -r requirements-aihub.txt  and  qai-hub configure --api_token <token>
Works from any x86 laptop — compilation and profiling happen on AI Hub's hosted Snapdragon devices.

  python tools/export_opus_mt.py hi mr dra --device "Snapdragon X Elite CRD"
Output: models/opus_mt/opus_mt_en_<xx>/{encoder,decoder}/… + samwaad_meta.json, and a profile row per
component in benchmarks/aihub_results.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

PAIRS = {"hi": "opus-mt-en-hi", "mr": "opus-mt-en-mr", "ml": "opus-mt-en-ml", "dra": "opus-mt-en-dra", "inc": "opus-mt-en-inc"}


def export_pair(code: str, device_name: str, runtime: str, profile: bool):
    import qai_hub as hub
    from qai_hub_models.models.templates.opus_mt.model import OpusMT, OpusMTDecoder, OpusMTEncoder

    from aihub_profile import append_rows, summarize

    hf_id = f"Helsinki-NLP/{PAIRS[code]}"
    out_dir = ROOT / "models" / "opus_mt" / PAIRS[code].replace("-", "_")
    out_dir.mkdir(parents=True, exist_ok=True)
    enc_m, dec_m = OpusMT.get_opus_model(hf_id)
    device = hub.Device(device_name)
    rows = []
    for name, comp in (("encoder", OpusMTEncoder(enc_m)), ("decoder", OpusMTDecoder(dec_m))):
        spec = comp.get_input_spec()
        traced = comp.convert_to_torchscript(spec)
        options = f"--target_runtime {runtime} --output_names {','.join(comp.get_output_names())}"
        print(f"→ compiling {hf_id} {name} for {device_name} ({runtime})")
        job = hub.submit_compile_job(model=traced, device=device, input_specs=spec, options=options,
                                     name=f"samwaad-{PAIRS[code]}-{name}")
        target = job.get_target_model()
        if target is None:
            sys.exit(f"Compile failed: {job.url}")
        dst = out_dir / name
        dst.mkdir(exist_ok=True)
        saved = Path(target.download(str(dst / "model")))
        if saved.suffix == ".zip" or zipfile.is_zipfile(saved):
            with zipfile.ZipFile(saved) as z:
                z.extractall(dst)
            saved.unlink()
        print(f"  saved → {dst}")
        if profile:
            pj = hub.submit_profile_job(model=target, device=device, name=f"samwaad-{PAIRS[code]}-{name}")
            lat, mem, units = summarize(pj.download_profile())
            print(f"  profiled: {lat} ms · {units} · {pj.url}")
            rows.append({"model": f"{PAIRS[code]} {name}", "device": device_name, "runtime": runtime, "unit": units,
                         "latency_ms": lat, "mem_mb": mem, "job": f"[{pj.job_id}]({pj.url})"})
    (out_dir / "samwaad_meta.json").write_text(json.dumps({"hf_id": hf_id, "runtime": runtime, "device": device_name}),
                                               encoding="utf-8")
    if rows:
        append_rows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pairs", nargs="+", choices=sorted(PAIRS))
    ap.add_argument("--device", default="Snapdragon X Elite CRD")
    ap.add_argument("--runtime", default="precompiled_qnn_onnx", help="precompiled_qnn_onnx (default) | onnx")
    ap.add_argument("--no-profile", action="store_true")
    a = ap.parse_args()
    for code in a.pairs:
        export_pair(code, a.device, a.runtime, not a.no_profile)
    print("\nDone. Samwaad picks these up automatically (translate.backend: hybrid).")


if __name__ == "__main__":
    main()
