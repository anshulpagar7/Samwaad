"""Voice activity detection + sentence segmentation.

Frames of 512 samples (32 ms @16 kHz) go in; complete speech segments come out.
A segment ends after `min_silence_ms` of silence or when it hits `max_segment_s`
so captions keep flowing during long monologues.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

FRAME = 512


class EnergyVAD:
    """Model-free fallback: adaptive RMS threshold. Good enough for a quiet room."""

    def __init__(self, sample_rate: int = 16000, **_):
        self.sr = sample_rate
        self.noise = 1e-3

    def __call__(self, frame: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)) + 1e-9)
        ratio = rms / (self.noise + 1e-9)
        if ratio < 2.0:  # looks like background -> slowly track the noise floor
            self.noise = 0.95 * self.noise + 0.05 * rms
        # Map ratio to a pseudo-probability: 1x noise -> 0, >=4x noise -> 1
        return float(np.clip((ratio - 1.0) / 3.0, 0.0, 1.0))

    def reset(self):
        self.noise = 1e-3


class SileroVAD:
    """Silero VAD v5 ONNX (≈2 MB). Tiny enough that CPU is the right place for it."""

    CONTEXT = 64

    def __init__(self, model_path: str, sample_rate: int = 16000, runtime_cfg: dict | None = None):
        from .runtime import make_session

        # VAD is ~0.1 ms/frame; keep it on CPU and save the NPU for Whisper/translation.
        self.sess = make_session(model_path, {"device": "cpu"})
        self.sr = np.array(sample_rate, dtype=np.int64)
        self.reset()

    def reset(self):
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, self.CONTEXT), dtype=np.float32)

    def __call__(self, frame: np.ndarray) -> float:
        x = frame.astype(np.float32).reshape(1, -1)
        x = np.concatenate([self.context, x], axis=1)
        out, self.state = self.sess.run(None, {"input": x, "state": self.state, "sr": self.sr})
        self.context = x[:, -self.CONTEXT:]
        return float(out.squeeze())


def build_vad(vad_cfg: dict, sample_rate: int, runtime_cfg: dict | None = None):
    if vad_cfg.get("backend", "silero") == "silero":
        path = vad_cfg.get("model_path", "")
        if path and Path(path).exists():
            return SileroVAD(path, sample_rate, runtime_cfg)
        log.warning("Silero model not found at %s — using energy VAD. Run `python tools/fetch_models.py`.", path)
    return EnergyVAD(sample_rate)


@dataclass
class Segment:
    audio: np.ndarray  # float32 mono 16 kHz
    start_s: float
    end_s: float


class Segmenter:
    def __init__(self, vad, sample_rate=16000, threshold=0.5, min_speech_ms=300,
                 min_silence_ms=500, max_segment_s=12, pad_ms=150, **_):
        self.vad = vad
        self.sr = sample_rate
        self.threshold = threshold
        fms = FRAME / sample_rate * 1000
        self.min_speech = max(1, int(min_speech_ms / fms))
        self.min_silence = max(1, int(min_silence_ms / fms))
        self.max_frames = int(max_segment_s * 1000 / fms)
        self.pad = int(pad_ms / fms)
        self._buf = np.zeros(0, dtype=np.float32)
        self._t = 0  # frames seen
        self._reset_segment()
        self._history: list[np.ndarray] = []  # pre-roll frames
        self.last_prob = 0.0

    def _reset_segment(self):
        self._frames: list[np.ndarray] = []
        self._speech = 0
        self._silence = 0
        self._start = None

    def feed(self, samples: np.ndarray) -> list[Segment]:
        """Push any number of samples; returns zero or more finished segments."""
        self._buf = np.concatenate([self._buf, samples.astype(np.float32).ravel()])
        done: list[Segment] = []
        while len(self._buf) >= FRAME:
            frame, self._buf = self._buf[:FRAME], self._buf[FRAME:]
            seg = self._step(frame)
            if seg is not None:
                done.append(seg)
        return done

    def _step(self, frame: np.ndarray) -> Segment | None:
        prob = self.vad(frame)
        self.last_prob = prob
        self._t += 1
        speaking = prob >= self.threshold
        if self._start is None:
            self._history.append(frame)
            self._history = self._history[-(self.pad + 1):]
            if speaking:
                self._start = self._t - len(self._history)
                self._frames = list(self._history)
                self._speech = 1
                self._silence = 0
            return None
        self._frames.append(frame)
        if speaking:
            self._speech += 1
            self._silence = 0
        else:
            self._silence += 1
        if self._silence >= self.min_silence or len(self._frames) >= self.max_frames:
            return self._emit()
        return None

    def _emit(self) -> Segment | None:
        frames, speech, start = self._frames, self._speech, self._start
        # Trim trailing silence but keep a little padding.
        trim = max(0, self._silence - self.pad)
        if trim:
            frames = frames[:-trim]
        self._reset_segment()
        self._history = []
        if speech < self.min_speech:
            return None
        audio = np.concatenate(frames)
        start_s = start * FRAME / self.sr
        return Segment(audio, start_s, start_s + len(audio) / self.sr)

    def flush(self) -> Segment | None:
        if self._start is None:
            return None
        self._silence = 0
        return self._emit()
