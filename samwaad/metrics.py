"""Live performance + power telemetry for the Performance page and the benchmark tool.

Everything here is measured on the user's own machine, nothing is estimated:
  * per-stage latency (ASR encoder/decoder, translation) and end-to-end "speaker paused ->
    caption on screen" latency, as rolling windows
  * real-time factor (processing time / audio time)
  * process CPU %, memory, and battery level/drain while a lecture is running (psutil)
"""
from __future__ import annotations

import statistics
import threading
import time
from collections import deque

try:
    import psutil  # optional — the app runs without it, just without CPU/battery numbers
except ImportError:  # pragma: no cover
    psutil = None


def _summ(xs) -> dict:
    xs = list(xs)
    if not xs:
        return {"n": 0, "avg": 0, "p50": 0, "p90": 0, "last": 0}
    s = sorted(xs)
    return {"n": len(s), "avg": round(statistics.fmean(s), 1), "p50": round(s[len(s) // 2], 1),
            "p90": round(s[min(len(s) - 1, int(len(s) * 0.9))], 1), "last": round(xs[-1], 1)}


class Metrics:
    WINDOW = 120

    def __init__(self):
        self._lock = threading.Lock()
        self.proc = psutil.Process() if psutil else None
        if self.proc:
            self.proc.cpu_percent(None)  # prime the counter
        self.reset()

    def reset(self):
        with self._lock:
            self.series = {k: deque(maxlen=self.WINDOW) for k in ("asr_ms", "enc_ms", "dec_ms", "tok_ms", "mt_ms", "e2e_ms")}
            self.audio_s = 0.0
            self.busy_s = 0.0
            self.samples = deque(maxlen=900)  # (t, cpu%, rss_mb, battery%)
            self.t0 = time.time()
            self.battery0 = self.battery()

    # ---------------------------------------------------------------- recording
    def add_sentence(self, audio_s: float, asr_ms: float, enc_ms: float, dec_ms: float, tokens: int,
                     mt_ms: float, e2e_ms: float):
        with self._lock:
            self.audio_s += audio_s
            self.busy_s += (asr_ms + mt_ms) / 1000
            for k, v in (("asr_ms", asr_ms), ("mt_ms", mt_ms), ("e2e_ms", e2e_ms)):
                if v:
                    self.series[k].append(v)
            if enc_ms:
                self.series["enc_ms"].append(enc_ms)
            if dec_ms and tokens:
                self.series["dec_ms"].append(dec_ms)
                self.series["tok_ms"].append(dec_ms / tokens)

    def sample(self):
        """Called every ~2 s by the engine's sampler thread."""
        cpu = rss = None
        if self.proc:
            try:
                cpu = self.proc.cpu_percent(None) / (psutil.cpu_count() or 1)
                rss = self.proc.memory_info().rss / 2**20
            except Exception:
                pass
        b = self.battery()
        with self._lock:
            self.samples.append((round(time.time() - self.t0, 1), None if cpu is None else round(cpu, 1),
                                 None if rss is None else round(rss), None if b is None else b["percent"]))

    @staticmethod
    def battery() -> dict | None:
        if not psutil or not hasattr(psutil, "sensors_battery"):
            return None
        try:
            b = psutil.sensors_battery()
        except Exception:
            return None
        return None if b is None else {"percent": round(b.percent, 1), "plugged": bool(b.power_plugged)}

    # ---------------------------------------------------------------- reporting
    def snapshot(self) -> dict:
        with self._lock:
            elapsed_h = max(1e-6, (time.time() - self.t0) / 3600)
            b_now, b0 = self.battery(), self.battery0
            drain = None
            if b_now and b0 and not b_now["plugged"] and elapsed_h > 0.05:
                drain = round((b0["percent"] - b_now["percent"]) / elapsed_h, 1)  # % per hour
            cpu_vals = [s[1] for s in self.samples if s[1] is not None]
            return {
                "stages": {k: _summ(v) for k, v in self.series.items()},
                "history": {k: [round(x, 1) for x in list(v)[-40:]] for k, v in self.series.items()},
                "rtf": round(self.busy_s / self.audio_s, 3) if self.audio_s else None,
                "audio_s": round(self.audio_s, 1),
                "cpu_avg": round(statistics.fmean(cpu_vals), 1) if cpu_vals else None,
                "cpu_series": cpu_vals[-60:],
                "rss_mb": self.samples[-1][2] if self.samples else None,
                "battery": b_now,
                "battery_drain_pct_per_h": drain,
                "since_s": round(time.time() - self.t0),
            }
