"""Speech-to-text backends.

- onnx-qnn       : Whisper encoder + decoder exported by Qualcomm AI Hub
                   (`qai-hub-models export whisper_base --target-runtime precompiled_qnn_onnx`),
                   run through ONNX Runtime. With runtime.device=npu the graphs execute on the
                   Snapdragon Hexagon NPU via the QNN Execution Provider. This is the product path.
- faster-whisper : CPU backend (CTranslate2 int8) for development on non-Snapdragon laptops and
                   the CPU side of the CPU-vs-NPU benchmark.
- script / mock  : deterministic stand-ins for UI demos and tests.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import ROOT, resource  # noqa: E402

log = logging.getLogger(__name__)


@dataclass
class ASRResult:
    text: str
    latency_ms: float
    backend: str
    tokens: int = 0          # decoded tokens (for per-token latency stats)
    encoder_ms: float = 0.0  # split of the latency, when the backend can measure it
    decoder_ms: float = 0.0


class MockASR:
    name = "mock"
    device = "cpu"

    def __init__(self, *_, **__):
        self.n = 0

    def transcribe(self, audio: np.ndarray) -> ASRResult:
        self.n += 1
        secs = len(audio) / 16000
        return ASRResult(f"Sentence {self.n} lasting {secs:.1f} seconds.", 1.0, self.name)


class ScriptASR:
    """Plays back a scripted transcript (samples/demo_script.json) one line per speech segment.
    For UI demos and screenshots on machines without the models installed."""
    name = "script"
    device = "cpu"

    def __init__(self, script: str, **_):
        self.lines = [l["en"] for l in json.loads(Path(script).read_text(encoding="utf-8"))["lines"]]
        self.n = 0

    def transcribe(self, audio: np.ndarray) -> ASRResult:
        text = self.lines[self.n % len(self.lines)]
        self.n += 1
        return ASRResult(text, 0.0, self.name)


class MissingASR:
    """Placeholder so the app still opens when no speech model is installed yet; every transcription
    attempt surfaces a clear, actionable error in the UI instead of the server failing to start."""
    name = "missing"
    device = "none"

    def __init__(self, reason: str):
        self.reason = reason

    def transcribe(self, audio: np.ndarray) -> ASRResult:
        raise RuntimeError(self.reason)


class FasterWhisperASR:
    name = "faster-whisper"
    device = "cpu"

    def __init__(self, model="base.en", language="en", beam_size=1, **_):
        from faster_whisper import WhisperModel

        self.model = WhisperModel(model, device="cpu", compute_type="int8")
        self.language = language
        self.beam = beam_size

    def transcribe(self, audio: np.ndarray) -> ASRResult:
        t0 = time.perf_counter()
        segs, _ = self.model.transcribe(audio, language=self.language, beam_size=self.beam,
                                        vad_filter=False, condition_on_previous_text=False)
        text = " ".join(s.text.strip() for s in segs).strip()
        return ASRResult(text, (time.perf_counter() - t0) * 1000, self.name)


# ---------------------------------------------------------------- Whisper log-mel (numpy)
# Verified identical to transformers.WhisperFeatureExtractor (max abs diff ~1e-6).
N_FFT, HOP, CHUNK = 400, 160, 30 * 16000


def _mel_filters(sr=16000, n_fft=N_FFT, n_mels=80) -> np.ndarray:
    """Slaney-style mel filterbank, identical to librosa.filters.mel (Whisper's front-end)."""
    def hz_to_mel(f):
        f = np.asanyarray(f, dtype=np.float64)
        lin = f / (200.0 / 3)
        log_part = 15.0 + np.log(np.maximum(f, 1e-10) / 1000.0) / (np.log(6.4) / 27.0)
        return np.where(f >= 1000.0, log_part, lin)

    def mel_to_hz(m):
        m = np.asanyarray(m, dtype=np.float64)
        lin = m * (200.0 / 3)
        log_part = 1000.0 * np.exp((np.log(6.4) / 27.0) * (m - 15.0))
        return np.where(m >= 15.0, log_part, lin)

    fft_freqs = np.linspace(0, sr / 2, n_fft // 2 + 1)
    mel_pts = mel_to_hz(np.linspace(hz_to_mel(0), hz_to_mel(sr / 2), n_mels + 2))
    fdiff = np.diff(mel_pts)
    ramps = mel_pts[:, None] - fft_freqs[None, :]
    lower = -ramps[:-2] / fdiff[:-1, None]
    upper = ramps[2:] / fdiff[1:, None]
    weights = np.maximum(0, np.minimum(lower, upper))
    weights *= (2.0 / (mel_pts[2:n_mels + 2] - mel_pts[:n_mels]))[:, None]
    return weights.astype(np.float32)


_MEL: dict[int, np.ndarray] = {}
_WINDOW = np.hanning(N_FFT + 1)[:-1].astype(np.float32)


def log_mel(audio: np.ndarray, n_mels: int = 80) -> np.ndarray:
    """Whisper's front-end: pad/trim to 30 s -> STFT -> mel -> log10, clamp, scale -> (1, n_mels, 3000)."""
    if n_mels not in _MEL:
        _MEL[n_mels] = _mel_filters(n_mels=n_mels)
    x = np.zeros(CHUNK, dtype=np.float32)
    x[:min(len(audio), CHUNK)] = audio[:CHUNK]
    x = np.pad(x, (N_FFT // 2, N_FFT // 2), mode="reflect")
    n_frames = 1 + (len(x) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    spec = np.abs(np.fft.rfft(x[idx] * _WINDOW, axis=1)) ** 2  # (frames, 201)
    spec = spec[:-1].T  # Whisper drops the last frame -> (201, 3000)
    mel = _MEL[n_mels] @ spec
    logm = np.log10(np.maximum(mel, 1e-10))
    logm = np.maximum(logm, logm.max() - 8.0)
    return ((logm + 4.0) / 4.0).astype(np.float32)[None]


# ---------------------------------------------------------------- Whisper on the NPU
class OnnxWhisperASR:
    """Greedy Whisper decoding over Qualcomm AI Hub's split encoder/decoder graphs.

    I/O contract of `qai_hub_models.models.templates.hf_whisper` (qai-hub-models 0.6x):
      encoder  input_features (1, n_mels, 3000)            -> k_cache_cross_{i}, v_cache_cross_{i}
      decoder  input_ids (1,1) int32, attention_mask (1,1,1,D) float32 (-100 = masked),
               k/v_cache_self_{i}_in (zeros first), k/v_cache_cross_{i}, position_ids (1,) int32
               -> logits (1, vocab, 1, 1), k/v_cache_self_{i}_out
    D (the fixed decode length, 200) is read from the graph, as are dtypes, so fp16-I/O
    exports work unchanged. Graphs are static-shaped — exactly what the HTP wants.
    """

    name = "onnx-qnn"
    MASK_NEG = -100.0

    def __init__(self, model: str, runtime_cfg: dict | None = None, tokenizer: str | object = "openai/whisper-base",
                 language: str = "en", **_):
        from .onnx_io import Feeder, find_component
        from .runtime import make_session

        folder = Path(model) if Path(model).is_absolute() else ROOT / model
        self.enc = make_session(str(find_component(folder, "encoder")), runtime_cfg)
        self.dec = make_session(str(find_component(folder, "decoder")), runtime_cfg)
        self.ef, self.df = Feeder(self.enc), Feeder(self.dec)
        self.device = "npu" if self.dec.get_providers()[0] == "QNNExecutionProvider" else "cpu"

        self.enc_in = next(iter(self.ef.inputs))
        self.n_mels = self.ef.shape(self.enc_in)[1] if len(self.ef.shape(self.enc_in)) == 3 else 80
        self.layers = sorted({int(m.group(1)) for n in self.df.inputs
                              if (m := re.fullmatch(r"k_cache_self_(\d+)_in", n))})
        if not self.layers:
            raise ValueError(f"Unexpected decoder inputs {list(self.df.inputs)} — is this an AI Hub Whisper export?")
        self.D = self.df.shape("attention_mask")[-1]

        if isinstance(tokenizer, str):
            from transformers import WhisperTokenizer
            tokenizer = WhisperTokenizer.from_pretrained(tokenizer)
        self.tok = tokenizer
        ids = self.tok.convert_tokens_to_ids
        self.sot, self.eot = ids("<|startoftranscript|>"), ids("<|endoftext|>")
        lang, task, no_ts = ids(f"<|{language}|>"), ids("<|transcribe|>"), ids("<|notimestamps|>")
        unk = getattr(self.tok, "unk_token_id", None)
        multilingual = lang not in (None, unk)
        # Force language + task so it never "translates" or drifts languages mid-lecture.
        self.prompt = [self.sot, lang, task, no_ts] if multilingual else [self.sot, no_ts]
        self._suppress = None

    def _cross_feed(self, enc_out: list[np.ndarray]) -> dict[str, np.ndarray]:
        named = dict(zip(self.ef.outputs, enc_out))
        feed = {}
        for i in self.layers:
            for kv in ("k", "v"):
                name = f"{kv}_cache_cross_{i}"
                arr = named.get(name)
                if arr is None:  # outputs renamed -> fall back to positional (k0, v0, k1, v1, ...)
                    arr = enc_out[2 * self.layers.index(i) + (kv == "v")]
                feed[name] = self.df.cast(name, arr)
        return feed

    def transcribe(self, audio: np.ndarray) -> ASRResult:
        t0 = time.perf_counter()
        feats = log_mel(audio, self.n_mels)
        cross = self._cross_feed(self.enc.run(None, {self.enc_in: self.ef.cast(self.enc_in, feats)}))
        t_enc = time.perf_counter()

        self_cache = {f"{kv}_cache_self_{i}_in": self.df.zeros(f"{kv}_cache_self_{i}_in")
                      for i in self.layers for kv in ("k", "v")}
        mask = np.full((1, 1, 1, self.D), self.MASK_NEG, dtype=self.df.dtype("attention_mask"))
        ids_dtype, pos_dtype = self.df.dtype("input_ids"), self.df.dtype("position_ids")
        seq, out = list(self.prompt), []

        for n in range(self.D - 1):
            mask[..., self.D - n - 1] = 0.0  # un-mask one more cache slot per step (right-aligned cache)
            outs = self.dec.run(None, {
                "input_ids": np.array([[seq[n]]], dtype=ids_dtype),
                "attention_mask": mask,
                "position_ids": np.array([n], dtype=pos_dtype),
                **self_cache, **cross,
            })
            named = dict(zip(self.df.outputs, outs))
            for i in self.layers:
                for kv in ("k", "v"):
                    self_cache[f"{kv}_cache_self_{i}_in"] = named[f"{kv}_cache_self_{i}_out"]
            if n < len(self.prompt) - 1:
                continue  # still feeding the forced prompt
            logits = named.get("logits", outs[0]).reshape(-1).astype(np.float32)
            if self._suppress is None or len(self._suppress) != len(logits):
                self._suppress = np.arange(len(logits)) > self.eot  # timestamps + special tokens
            logits[self._suppress] = -np.inf
            nxt = int(logits.argmax())
            if nxt == self.eot:
                break
            seq.append(nxt)
            out.append(nxt)
        t1 = time.perf_counter()
        text = self.tok.decode(out, skip_special_tokens=True).strip()
        return ASRResult(text, (t1 - t0) * 1000, f"{self.name}:{self.device}", tokens=len(out),
                         encoder_ms=(t_enc - t0) * 1000, decoder_ms=(t1 - t_enc) * 1000)


def build_asr(asr_cfg: dict, runtime_cfg: dict | None = None):
    backend = asr_cfg.get("backend", "faster-whisper")
    if backend == "mock":
        return MockASR()
    if backend == "script":
        return ScriptASR(asr_cfg.get("script") or str(resource("samples/demo_script.json")))
    lang = asr_cfg.get("language", "en")
    cpu_model = asr_cfg.get("cpu_model", "base")
    if backend == "faster-whisper":
        model = asr_cfg.get("model", cpu_model)
        return FasterWhisperASR(model if not Path(str(model)).is_absolute() else cpu_model, lang, asr_cfg.get("beam_size", 1))
    if backend in ("onnx-qnn", "auto"):
        folder = Path(asr_cfg.get("model", "models/whisper_base"))
        folder = folder if folder.is_absolute() else ROOT / folder
        has_export = folder.exists() and any(folder.rglob("*.onnx"))
        if backend == "onnx-qnn" or has_export:
            return OnnxWhisperASR(str(folder), runtime_cfg, asr_cfg.get("tokenizer", "openai/whisper-base"), lang)
        log.info("No AI Hub Whisper export in %s — using faster-whisper (%s) on CPU.", folder, cpu_model)
        try:
            return FasterWhisperASR(cpu_model, lang, asr_cfg.get("beam_size", 1))
        except Exception as e:  # not installed / model not downloaded — keep the app usable
            log.error("No speech model available (%s).", e)
            return MissingASR("No speech model installed yet — run  python tools/fetch_models.py  "
                              "(or start with --demo to try the app).")
    raise ValueError(f"Unknown asr.backend {backend!r}")
