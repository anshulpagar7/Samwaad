"""Small helpers shared by the ONNX Runtime backends (Whisper, OPUS-MT, benchmarks).

AI Hub exports can come with float32 or float16 I/O (`--quantize_io`), and int32 or int64
token inputs, depending on the model and QAIRT version. These helpers read what the
session actually expects so the same decoding code works for all of them.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

ORT_DTYPES = {
    "tensor(float)": np.float32, "tensor(float16)": np.float16, "tensor(double)": np.float64,
    "tensor(int64)": np.int64, "tensor(int32)": np.int32, "tensor(int16)": np.int16,
    "tensor(int8)": np.int8, "tensor(uint8)": np.uint8, "tensor(uint16)": np.uint16, "tensor(bool)": np.bool_,
}


def np_dtype(ort_type: str):
    return ORT_DTYPES.get(ort_type, np.float32)


def static_shape(shape, default: int = 1) -> tuple[int, ...]:
    """ONNX shapes may contain symbolic dims ('batch') — replace them with `default`."""
    return tuple(d if isinstance(d, int) and d > 0 else default for d in shape)


class Feeder:
    """Knows each input's dtype/shape and casts numpy arrays to match."""

    def __init__(self, session):
        self.inputs = {i.name: i for i in session.get_inputs()}
        self.outputs = [o.name for o in session.get_outputs()]

    def dtype(self, name: str):
        return np_dtype(self.inputs[name].type)

    def shape(self, name: str) -> tuple[int, ...]:
        return static_shape(self.inputs[name].shape)

    def zeros(self, name: str) -> np.ndarray:
        return np.zeros(self.shape(name), dtype=self.dtype(name))

    def cast(self, name: str, arr) -> np.ndarray:
        return np.asarray(arr).astype(self.dtype(name), copy=False)

    def has(self, name: str) -> bool:
        return name in self.inputs


def find_component(folder: str | Path, keyword: str) -> Path:
    """Locate e.g. the encoder .onnx inside an AI Hub export folder (searched recursively,
    because precompiled_qnn_onnx exports unpack to <component>/model.onnx + model.bin)."""
    folder = Path(folder)
    hits = sorted(p for p in folder.rglob("*.onnx") if keyword in str(p.relative_to(folder)).lower())
    if not hits:
        raise FileNotFoundError(f"No *{keyword}*.onnx under {folder}. See docs/NPU.md for the export command.")
    return hits[0]
