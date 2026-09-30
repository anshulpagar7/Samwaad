"""Local benchmarks for the CPU-vs-NPU story — run these on the Snapdragon laptop.

  # Raw model latency, CPU vs NPU, for every model Samwaad ships (or any .onnx you pass)
  python tools/benchmark.py models
  python tools/benchmark.py model models/whisper_base/…/model.onnx --runs 30

  # End-to-end on a recorded lecture: latency per sentence, real-time factor, CPU load, battery
  python tools/benchmark.py pipeline samples/lecture.wav -o runtime.device=cpu
  python tools/benchmark.py pipeline samples/lecture.wav -o runtime.device=npu

Results go to benchmarks/local_results.json (shown on the in-app Performance page)
and benchmarks/local_results.md (for the README / submission).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
JSON_OUT = ROOT / "benchmarks" / "local_results.json"
MD_OUT = ROOT / "benchmarks" / "local_results.md"


def _record(row: dict, header: str, md_row: str):
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = json.loads(JSON_OUT.read_text(encoding="utf-8")) if JSON_OUT.exists() else []
    rows.append(row)
    JSON_OUT.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    text = MD_OUT.read_text(encoding="utf-8") if MD_OUT.exists() else "# Local benchmark results\n"
    if header not in text:
        text += "\n" + header
    MD_OUT.write_text(text + md_row + "\n", encoding="utf-8")
    print("→", JSON_OUT.relative_to(ROOT))


def bench_model(path: str, runs: int):
    from samwaad.onnx_io import Feeder
    from samwaad.runtime import CPU, QNN, available_providers, make_session

    devices = ["cpu"] + (["npu"] if QNN in available_providers() else [])
    results = {}
    for dev in devices:
        sess = make_session(path, {"device": dev})
        f = Feeder(sess)
        feeds = {n: (np.random.rand(*f.shape(n)) * (1 if "float" in f.inputs[n].type else 3)).astype(f.dtype(n))
                 for n in f.inputs}
        for _ in range(3):
            sess.run(None, feeds)  # warm-up (QNN finalizes the graph on first run)
        times = []
        for _ in range(runs):
            t0 = time.perf_counter()
            sess.run(None, feeds)
            times.append((time.perf_counter() - t0) * 1000)
        ep = sess.get_providers()[0]
        med, p90 = statistics.median(times), float(np.percentile(times, 90))
        results[dev] = med
        print(f"{dev:>3} [{ep}]  median {med:.2f} ms · p90 {p90:.2f} ms")
        name = str(Path(path).relative_to(ROOT)) if Path(path).is_relative_to(ROOT) else Path(path).name
        _record({"kind": "model", "date": dt.date.today().isoformat(), "model": name, "machine": platform.machine(),
                 "provider": ep, "median_ms": round(med, 2), "p90_ms": round(p90, 2), "runs": runs},
                "| Date | Model | Machine | Provider | Median ms | p90 ms | Runs |\n|---|---|---|---|---|---|---|\n",
                f"| {dt.date.today()} | {name} | {platform.machine()} | {ep} | {med:.2f} | {p90:.2f} | {runs} |")
    if len(results) == 2:
        print(f"   NPU speed-up: {results['cpu'] / results['npu']:.1f}×")


def bench_models(runs: int):
    found = sorted(p for p in (ROOT / "models").rglob("*.onnx"))
    if not found:
        sys.exit("No .onnx models under models/ — run tools/fetch_models.py first.")
    for p in found:
        print(f"\n{p.relative_to(ROOT)}")
        try:
            bench_model(str(p), runs)
        except Exception as e:
            print(f"   skipped: {e}")


def bench_pipeline(wav: str, overrides: list[str]):
    from samwaad.config import load_config
    from samwaad.pipeline import Engine

    cfg = load_config(overrides=overrides + [f"store.dir={ROOT / 'benchmarks' / '_runs'}"])
    eng = Engine(cfg)
    done = {}
    eng.subscribe(lambda ev: done.update(ev) if ev["type"] == "stopped" else None)
    t0 = time.perf_counter()
    eng.start("file", wav, title=f"benchmark {Path(wav).name}", realtime=True, user="bench")
    eng.wait()
    wall = time.perf_counter() - t0
    s, m = done.get("stats", {}), done.get("metrics", {})
    st = m.get("stages", {})
    row = {"kind": "pipeline", "date": dt.date.today().isoformat(), "audio": Path(wav).name, "machine": platform.machine(),
           "provider": eng.runtime["execution_provider"], "asr": eng.asr.name, "asr_device": getattr(eng.asr, "device", "cpu"),
           "sentences": s.get("lines"), "audio_s": s.get("audio_s"), "asr_ms": st.get("asr_ms", {}).get("avg"),
           "tok_ms": st.get("tok_ms", {}).get("avg"), "mt_ms": st.get("mt_ms", {}).get("avg"), "e2e_ms": st.get("e2e_ms", {}).get("avg"),
           "rtf": m.get("rtf"), "cpu_avg": m.get("cpu_avg"), "battery_drain_pct_per_h": m.get("battery_drain_pct_per_h"),
           "wall_s": round(wall, 1)}
    print(json.dumps(row, indent=1))
    _record(row,
            "| Date | Audio | Machine | Provider | ASR | ASR ms/sentence | ms/token | MT ms | Caption latency ms | RTF | CPU % | Battery %/h |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|\n",
            f"| {row['date']} | {row['audio']} | {row['machine']} | {row['provider']} | {row['asr']} | {row['asr_ms']} | "
            f"{row['tok_ms']} | {row['mt_ms']} | {row['e2e_ms']} | {row['rtf']} | {row['cpu_avg']} | {row['battery_drain_pct_per_h']} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("model")
    m.add_argument("path")
    m.add_argument("--runs", type=int, default=30)
    ms = sub.add_parser("models")
    ms.add_argument("--runs", type=int, default=20)
    p = sub.add_parser("pipeline")
    p.add_argument("wav")
    p.add_argument("-o", "--override", action="append", default=[])
    a = ap.parse_args()
    if a.cmd == "model":
        bench_model(a.path, a.runs)
    elif a.cmd == "models":
        bench_models(a.runs)
    else:
        bench_pipeline(a.wav, a.override)


if __name__ == "__main__":
    main()
