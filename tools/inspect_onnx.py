"""Print an ONNX model's inputs/outputs (names, shapes, dtypes).

  python tools/inspect_onnx.py models/whisper_base_en/*.onnx

Use it on day 1 to confirm the AI Hub Whisper I/O names match samwaad/asr.py's OnnxWhisperASR.
"""
import sys

import onnxruntime as ort

for path in sys.argv[1:]:
    s = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    print(f"\n== {path}")
    for kind, items in (("in ", s.get_inputs()), ("out", s.get_outputs())):
        for i in items:
            print(f"  {kind}  {i.name:<24} {str(i.shape):<28} {i.type}")
