"""Microphone / WAV-file audio sources. Both yield float32 mono 16 kHz blocks."""
from __future__ import annotations

import queue
import threading
import time
import wave
from typing import Iterator

import numpy as np


def list_devices() -> str:
    import sounddevice as sd

    return str(sd.query_devices())


class MicSource:
    """Captures the default (or chosen) input device. Use a loopback / "Stereo Mix"
    device to caption system audio (Zoom, YouTube, recorded lectures)."""

    def __init__(self, sample_rate=16000, block_ms=32, device=None):
        self.sr = sample_rate
        self.block = int(sample_rate * block_ms / 1000)
        self.device = device
        self.q: queue.Queue[np.ndarray] = queue.Queue(maxsize=500)
        self._stop = threading.Event()

    def _cb(self, indata, frames, t, status):
        try:
            self.q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass  # drop audio rather than stall the realtime callback

    def blocks(self) -> Iterator[np.ndarray]:
        import sounddevice as sd

        with sd.InputStream(samplerate=self.sr, channels=1, dtype="float32",
                            blocksize=self.block, device=self.device, callback=self._cb):
            while not self._stop.is_set():
                try:
                    yield self.q.get(timeout=0.2)
                except queue.Empty:
                    continue

    def stop(self):
        self._stop.set()


def read_wav(path: str, target_sr: int = 16000) -> np.ndarray:
    with wave.open(path, "rb") as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}[width]
    x = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if width == 1:
        x = (x - 128) / 128
    else:
        x /= float(np.iinfo(dtype).max)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != target_sr:  # linear resample — fine for speech
        n = int(len(x) * target_sr / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    return x


def write_wav(path: str, audio: np.ndarray, sr: int = 16000):
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


class FileSource:
    """Replays a WAV as if it were live — great for demos and repeatable benchmarks."""

    def __init__(self, path: str, sample_rate=16000, block_ms=32, realtime=True):
        self.audio = read_wav(path, sample_rate)
        self.sr = sample_rate
        self.block = int(sample_rate * block_ms / 1000)
        self.realtime = realtime
        self._stop = threading.Event()

    def blocks(self) -> Iterator[np.ndarray]:
        dt = self.block / self.sr
        for i in range(0, len(self.audio), self.block):
            if self._stop.is_set():
                return
            yield self.audio[i:i + self.block]
            if self.realtime:
                time.sleep(dt)
        # trailing silence so the last sentence gets flushed
        yield np.zeros(self.sr, dtype=np.float32)

    def stop(self):
        self._stop.set()
