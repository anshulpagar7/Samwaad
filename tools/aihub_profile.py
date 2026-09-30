"""Qualcomm AI Hub helpers: published numbers, compile/profile on hosted Snapdragon X devices.

No Snapdragon laptop needed for any of this — AI Hub runs jobs on its own device farm.

  # Qualcomm's own published profiles for the models Samwaad uses (no account needed)
  python tools/aihub_profile.py published

  # Compile + profile Whisper for Snapdragon X (needs `qai-hub configure --api_token …`)
  python tools/aihub_profile.py whisper --model-id whisper_base

  # Any ONNX you exported yourself, with fixed input shapes
  python tools/aihub_profile.py onnx path/to/model.onnx --input input_ids:1x64:int32

  # List the Snapdragon compute devices AI Hub offers
  python tools/aihub_profile.py devices

Profile rows are appended to benchmarks/aihub_results.md.
(Ready-made Whisper NPU assets can also simply be downloaded — see tools/fetch_models.py --npu.)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "benchmarks" / "aihub_results.md"
PUBLISHED = ROOT / "benchmarks" / "aihub_published.json"
DEFAULT_DEVICE = "Snapdragon X Elite CRD"


def append_rows(rows: list[dict]):
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    new = not RESULTS.exists()
    with open(RESULTS, "a", encoding="utf-8") as f:
        if new:
            f.write("# Qualcomm AI Hub profiling results (our own jobs)\n\n")
            f.write("| Date | Model | Device | Runtime | Compute unit | Latency (ms) | Peak memory (MB) | Job |\n")
            f.write("|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r.get('date', dt.date.today().isoformat())} | {r['model']} | {r['device']} | {r['runtime']} | "
                    f"{r['unit']} | {r['latency_ms']} | {r['mem_mb']} | {r['job']} |\n")
    print(f"→ appended {len(rows)} row(s) to {RESULTS.relative_to(ROOT)}")


def summarize(profile: dict) -> tuple[float, float, str]:
    ex = profile.get("execution_summary", {})
    lat = ex.get("estimated_inference_time", 0) / 1000.0  # µs -> ms
    mem = ex.get("estimated_inference_peak_memory", 0) / 1e6  # bytes -> MB
    units: dict[str, int] = {}
    for layer in profile.get("execution_detail", []):
        u = layer.get("compute_unit", "?")
        units[u] = units.get(u, 0) + 1
    total = sum(units.values()) or 1
    unit_str = ", ".join(f"{k} {v * 100 // total}%" for k, v in sorted(units.items(), key=lambda x: -x[1]))
    return round(lat, 2), round(mem, 1), unit_str or "?"


def cmd_published(_):
    data = json.loads(PUBLISHED.read_text(encoding="utf-8"))
    print(f"\n{data['source']}\n")
    print(f"{'model':<26}{'part':<9}{'device':<26}{'runtime':<22}{'latency':>10}  NPU layers")
    for m in data["models"]:
        if m["role"] == "llm":
            lat = f"{m['tokens_per_second']} tok/s"
            layers = f"TTFT {m['ttft_ms_min']} ms"
        else:
            lat = f"{m['latency_ms']:.1f} ms"
            layers = f"{m['npu_layers']}/{m['total_layers']}"
        print(f"{m['label'][:25]:<26}{m['component']:<9}{m['device'][:25]:<26}{m['runtime']:<22}{lat:>10}  {layers}")


def cmd_devices(_):
    import qai_hub as hub
    for d in hub.get_devices():
        if "Snapdragon X" in d.name:
            print(f"- {d.name}  ({d.os})")


def cmd_whisper(args):
    """The model zoo's own export recipe: trace → compile → profile → download encoder+decoder."""
    cli = shutil.which("qai-hub-models")
    base = [cli, "export", args.model_id] if cli else [sys.executable, "-m", f"qai_hub_models.models.{args.model_id}.export"]
    cmd = base + ["--device", args.device, "--target-runtime", args.runtime,
                  "--output-dir", str(ROOT / "models" / args.model_id)]
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"\n✓ Compiled Whisper in models/{args.model_id}/ — Samwaad picks it up automatically (asr.backend: auto).")


def cmd_onnx(args):
    import qai_hub as hub

    specs = {}
    for spec in args.input or []:
        name, shape, dtype = spec.split(":")
        specs[name] = (tuple(int(x) for x in shape.split("x")), dtype)
    device = hub.Device(args.device)
    compile_job = hub.submit_compile_job(model=args.path, device=device, input_specs=specs or None,
                                         options=f"--target_runtime {args.runtime}", name=Path(args.path).stem)
    print("compile job:", compile_job.url)
    target = compile_job.get_target_model()
    if target is None:
        sys.exit("Compile failed — open the job URL above for the unsupported op / shape.")
    out = ROOT / "models" / "aihub" / Path(args.path).stem
    out.mkdir(parents=True, exist_ok=True)
    print("compiled model →", target.download(str(out / "model")))
    profile_job = hub.submit_profile_job(model=target, device=device, name=Path(args.path).stem)
    print("profile job:", profile_job.url)
    lat, mem, units = summarize(profile_job.download_profile())
    print(f"latency {lat} ms · peak mem {mem} MB · units {units}")
    append_rows([{"model": Path(args.path).name, "device": args.device, "runtime": args.runtime, "unit": units,
                  "latency_ms": lat, "mem_mb": mem, "job": f"[{profile_job.job_id}]({profile_job.url})"}])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default=DEFAULT_DEVICE)
    ap.add_argument("--runtime", default="precompiled_qnn_onnx", help="precompiled_qnn_onnx | onnx | qnn_context_binary")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("published").set_defaults(fn=cmd_published)
    sub.add_parser("devices").set_defaults(fn=cmd_devices)
    w = sub.add_parser("whisper")
    w.add_argument("--model-id", default="whisper_base", help="whisper_tiny | whisper_base | whisper_small")
    w.set_defaults(fn=cmd_whisper)
    o = sub.add_parser("onnx")
    o.add_argument("path")
    o.add_argument("--input", action="append", help="name:1x64:int32")
    o.set_defaults(fn=cmd_onnx)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
