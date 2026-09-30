"""The live pipeline: audio -> VAD segments -> Whisper -> translation -> store + UI events.

Two worker threads so a slow translation never delays the next caption:
  capture thread  : reads audio blocks, runs VAD, queues finished segments, streams audio level
  inference thread: ASR + translation per segment, emits caption/translation/stage events
A third, light thread samples CPU/memory/battery every 2 s while a lecture is running.

Events (JSON over the WebSocket):
  started · level {rms, speech, bands[16]} · stage {stage, state, ms, device} · caption · translation
  metrics · stopped · error
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

from .asr import build_asr
from .audio import FileSource, MicSource
from .metrics import Metrics
from .runtime import describe
from .store import Line, SessionStore
from .translate import build_translator
from .vad import Segmenter, build_vad

log = logging.getLogger(__name__)

LEVEL_EVERY_S = 0.06
METRICS_EVERY_S = 2.0
N_BANDS = 16
Event = dict
Listener = Callable[[Event], None]


def spectrum_bands(block: np.ndarray, sr: int = 16000, n: int = N_BANDS) -> list[float]:
    """16 log-spaced loudness bands (80 Hz – 8 kHz), 0..1 — drives the audio ring in the UI."""
    if len(block) < 64:
        return [0.0] * n
    win = np.hanning(len(block)).astype(np.float32)
    mag = np.abs(np.fft.rfft(block * win))
    freqs = np.fft.rfftfreq(len(block), 1 / sr)
    edges = np.geomspace(80, sr / 2, n + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = mag[(freqs >= lo) & (freqs < hi)]
        v = float(m.mean()) if len(m) else 0.0
        out.append(round(min(1.0, max(0.0, (np.log10(v + 1e-6) + 2.2) / 2.6)), 3))
    return out


class Engine:
    """Holds the loaded models (expensive) and runs capture sessions (cheap)."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.asr = build_asr(cfg["asr"], cfg.get("runtime"))
        self.translator = build_translator(cfg.get("translate", {}), cfg.get("runtime"))
        self.runtime = describe(cfg.get("runtime"))  # after model loading, so it lists every session's EP
        log.info("Runtime: %s", {k: v for k, v in self.runtime.items() if k != "sessions"})
        self.target = cfg.get("translate", {}).get("target")
        self.metrics = Metrics()
        self._listeners: list[Listener] = []
        self.session: SessionStore | None = None
        self._source = None
        self._threads: list[threading.Thread] = []
        self._segments: queue.Queue = queue.Queue()
        self._capturing = False
        self.owner: str | None = None  # account that started the current session
        self.started_at: float | None = None

    @property
    def running(self) -> bool:
        """True while capturing OR still finishing the last sentences."""
        return any(t.is_alive() for t in self._threads)

    # ---------------------------------------------------------------- info
    def engines(self) -> dict:
        tr = self.translator
        return {
            "asr": {"name": getattr(self.asr, "name", "?"), "device": getattr(self.asr, "device", "cpu")},
            "translate": {"name": getattr(tr, "name", "?"),
                          "per_language": tr.engines() if hasattr(tr, "engines") else {},
                          "prefer": getattr(tr, "prefer", None)},
        }

    # ---------------------------------------------------------------- events
    def subscribe(self, fn: Listener):
        self._listeners.append(fn)

    def _emit(self, ev: Event):
        for fn in list(self._listeners):
            try:
                fn(ev)
            except Exception:  # a broken UI client must never kill the pipeline
                log.exception("listener failed")

    def set_target(self, target: str | None):
        self.target = target or None
        self._emit({"type": "target", "target": self.target})

    def set_prefer(self, prefer: str):
        if hasattr(self.translator, "prefer") and prefer in ("npu", "quality"):
            self.translator.prefer = prefer

    # ---------------------------------------------------------------- lifecycle
    def start(self, source: str = "mic", wav: str | None = None, title: str | None = None,
              realtime: bool = True, user: str = "local") -> SessionStore:
        if self.running:
            raise RuntimeError("already running")
        a = self.cfg["audio"]
        if source == "file":
            self._source = FileSource(wav, a["sample_rate"], a["block_ms"], realtime=realtime)
        else:
            self._source = MicSource(a["sample_rate"], a["block_ms"], a.get("device"))
        vad = build_vad(self.cfg["vad"], a["sample_rate"], self.cfg.get("runtime"))
        self._segmenter = Segmenter(vad, a["sample_rate"], **{k: v for k, v in self.cfg["vad"].items()
                                                               if k not in ("backend", "model_path")})
        self.session = SessionStore(str(Path(self.cfg["store"]["dir"]) / user), title)
        self.owner = user
        self.metrics.reset()
        self.started_at = time.time()
        self._segments = queue.Queue()
        self._capturing = True
        self._done = threading.Event()
        self._order = threading.Lock()  # keeps "stopped" the very last event of a session
        self._threads = [
            threading.Thread(target=self._capture_loop, name="capture", daemon=True),
            threading.Thread(target=self._infer_loop, name="infer", daemon=True),
            threading.Thread(target=self._metrics_loop, name="metrics", daemon=True),
        ]
        # Announce before the workers start so UIs always see "started" first.
        self._emit({"type": "started", "session": self.session.id, "title": self.session.title,
                    "source": source, "engines": self.engines(), "vad": type(vad).__name__})
        for t in self._threads:
            t.start()
        return self.session

    def stop(self):
        if self._source:
            self._source.stop()
        self._capturing = False

    def wait(self, timeout: float | None = None):
        for t in self._threads:
            t.join(timeout)

    # ---------------------------------------------------------------- workers
    def _capture_loop(self):
        last_level = 0.0
        sr = self.cfg["audio"]["sample_rate"]
        try:
            for block in self._source.blocks():
                if not self._capturing:
                    break
                for seg in self._segmenter.feed(block):
                    seg.queued_at = time.perf_counter()
                    self._segments.put(seg)
                    self._emit({"type": "stage", "stage": "vad", "state": "done",
                                "ms": round((seg.end_s - seg.start_s) * 1000), "device": "cpu"})
                now = time.monotonic()
                if now - last_level >= LEVEL_EVERY_S:  # drives the orb + audio ring
                    last_level = now
                    rms = float(np.sqrt(np.mean(np.square(block))) if len(block) else 0.0)
                    self._emit({"type": "level", "rms": round(min(1.0, rms * 8), 3),
                                "speech": round(self._segmenter.last_prob, 2),
                                "bands": spectrum_bands(block, sr)})
            last = self._segmenter.flush()
            if last is not None:
                last.queued_at = time.perf_counter()
                self._segments.put(last)
        except Exception as e:
            log.exception("capture failed")
            self._emit({"type": "error", "where": "audio", "message": str(e)})
        finally:
            self._capturing = False
            self._segments.put(None)  # sentinel

    def _infer_loop(self):
        idx = 0
        asr_dev = getattr(self.asr, "device", "cpu")
        while True:
            seg = self._segments.get()
            if seg is None:
                break
            try:
                self._emit({"type": "stage", "stage": "asr", "state": "start", "device": asr_dev})
                res = self.asr.transcribe(seg.audio)
                self._emit({"type": "stage", "stage": "asr", "state": "done", "ms": round(res.latency_ms, 1),
                            "device": asr_dev, "tokens": res.tokens})
                if not res.text or _is_hallucination(res.text):
                    continue
                e2e = (time.perf_counter() - getattr(seg, "queued_at", time.perf_counter())) * 1000
                line = Line(idx, round(seg.start_s, 2), round(seg.end_s, 2), res.text,
                            asr_ms=round(res.latency_ms, 1), asr_backend=res.backend, e2e_ms=round(e2e, 1))
                self._emit({"type": "caption", "line": line.__dict__})
                if self.target:
                    self._emit({"type": "stage", "stage": "mt", "state": "start", "device": _dev(self.translator, self.target)})
                    tr, ms = self.translator.translate(res.text, self.target)
                    engine = getattr(self.translator, "last_engine", "")
                    line.translation, line.target, line.mt_ms, line.mt_engine = tr, self.target, round(ms, 1), engine
                    self._emit({"type": "stage", "stage": "mt", "state": "done", "ms": line.mt_ms,
                                "device": engine.split(":")[-1] if engine else "cpu", "engine": engine})
                    self._emit({"type": "translation", "idx": idx, "text": tr, "target": self.target,
                                "mt_ms": line.mt_ms, "engine": engine})
                self.metrics.add_sentence(seg.end_s - seg.start_s, res.latency_ms, res.encoder_ms, res.decoder_ms,
                                          res.tokens, line.mt_ms, e2e)
                self.session.add(line)
                self._emit({"type": "stage", "stage": "store", "state": "done", "device": "disk"})
                idx += 1
            except Exception as e:
                log.exception("inference failed")
                self._emit({"type": "error", "where": "inference", "message": str(e)})
        self.session.export_markdown()
        with self._order:
            self._done.set()
            self._emit({"type": "stopped", "session": self.session.id, "stats": self.session.stats(),
                        "metrics": self.metrics.snapshot()})

    def _metrics_loop(self):
        while not self._done.is_set():
            self.metrics.sample()
            with self._order:
                if self._done.is_set():
                    break
                self._emit({"type": "metrics", **self.metrics.snapshot()})
            self._done.wait(METRICS_EVERY_S)


def _dev(translator, target) -> str:
    f = getattr(translator, "engine_for", None)
    return f(target).split(":")[-1] if f else "cpu"


# Whisper famously "hears" these in silence/noise. Drop them instead of captioning garbage.
_HALLUCINATIONS = {"thank you.", "thanks for watching!", "thank you for watching.", "you", ".", "bye.",
                   "thanks for watching.", "subtitles by the amara.org community"}


def _is_hallucination(text: str) -> bool:
    return text.strip().lower() in _HALLUCINATIONS
