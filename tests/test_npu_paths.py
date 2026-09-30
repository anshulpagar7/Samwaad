"""The NPU decoding loops, tested against tiny ONNX graphs that have exactly the I/O contract
of Qualcomm AI Hub's Whisper (templates.hf_whisper) and OPUS-MT (templates.opus_mt) exports.
Runs anywhere on the CPU EP; the same code runs unchanged on QNN."""
import sys
from pathlib import Path

import numpy as np
import pytest

onnx = pytest.importorskip("onnx")
from onnx import TensorProto, helper, numpy_helper  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _const(name, arr):
    return helper.make_node("Constant", [], [name], value=numpy_helper.from_array(arr, name + "_v"))


def _save(graph, path):
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.save(model, str(path))


# ------------------------------------------------------------------ Whisper
H, HD, L, D, V = 2, 4, 2, 8, 60
EOT, SOT, EN, TR, NOTS = 50, 51, 52, 53, 54


def build_whisper(folder: Path, io_dtype=TensorProto.FLOAT):
    np_io = np.float16 if io_dtype == TensorProto.FLOAT16 else np.float32
    (folder / "HfWhisperEncoder").mkdir(parents=True)
    (folder / "HfWhisperDecoder").mkdir(parents=True)
    # encoder: input_features -> constant cross caches
    nodes, outs = [], []
    for i in range(L):
        for kv, shape in (("k", (H, 1, HD, 1500)), ("v", (H, 1, 1500, HD))):
            n = f"{kv}_cache_cross_{i}"
            nodes.append(_const(n, np.full(shape, 0.1, dtype=np_io)))
            outs.append(helper.make_tensor_value_info(n, io_dtype, shape))
    g = helper.make_graph(nodes, "enc", [helper.make_tensor_value_info("input_features", io_dtype, (1, 80, 3000))], outs)
    _save(g, folder / "HfWhisperEncoder" / "model.onnx")

    # decoder: logits = table[position_ids]; self caches pass through (+0)
    table = np.full((D, V), -5.0, dtype=np.float32)
    table[3, 7] = 5.0                      # first text token after the 4-token prompt
    table[4, 9], table[4, 55] = 5.0, 9.0   # 55 is a special/timestamp token -> must be suppressed
    table[5, EOT] = 5.0
    inputs = [helper.make_tensor_value_info("input_ids", TensorProto.INT32, (1, 1)),
              helper.make_tensor_value_info("attention_mask", io_dtype, (1, 1, 1, D))]
    nodes = [_const("table", table),
             helper.make_node("Gather", ["table", "position_ids"], ["row"], axis=0),
             _const("shape4", np.array([1, V, 1, 1], dtype=np.int64)),
             helper.make_node("Reshape", ["row", "shape4"], ["logits"])]
    outputs = [helper.make_tensor_value_info("logits", TensorProto.FLOAT, (1, V, 1, 1))]
    for i in range(L):
        for kv, shape in (("k", (H, 1, HD, D - 1)), ("v", (H, 1, D - 1, HD))):
            inputs.append(helper.make_tensor_value_info(f"{kv}_cache_self_{i}_in", io_dtype, shape))
            nodes.append(helper.make_node("Identity", [f"{kv}_cache_self_{i}_in"], [f"{kv}_cache_self_{i}_out"]))
            outputs.append(helper.make_tensor_value_info(f"{kv}_cache_self_{i}_out", io_dtype, shape))
    for i in range(L):
        for kv, shape in (("k", (H, 1, HD, 1500)), ("v", (H, 1, 1500, HD))):
            inputs.append(helper.make_tensor_value_info(f"{kv}_cache_cross_{i}", io_dtype, shape))
    inputs.append(helper.make_tensor_value_info("position_ids", TensorProto.INT32, (1,)))
    _save(helper.make_graph(nodes, "dec", inputs, outputs), folder / "HfWhisperDecoder" / "model.onnx")


class FakeWhisperTok:
    vocab = {"<|startoftranscript|>": SOT, "<|endoftext|>": EOT, "<|en|>": EN, "<|transcribe|>": TR, "<|notimestamps|>": NOTS}
    words = {7: "Namaste", 9: "class"}
    unk_token_id = None

    def convert_tokens_to_ids(self, t):
        return self.vocab.get(t)

    def decode(self, ids, skip_special_tokens=True):
        return " ".join(self.words.get(i, "?") for i in ids)


@pytest.mark.parametrize("io", [TensorProto.FLOAT, TensorProto.FLOAT16])
def test_onnx_whisper_greedy_decode(tmp_path, io):
    from samwaad.asr import OnnxWhisperASR

    build_whisper(tmp_path / "whisper_base", io)
    asr = OnnxWhisperASR(str(tmp_path / "whisper_base"), {"device": "cpu"}, tokenizer=FakeWhisperTok())
    assert asr.layers == [0, 1] and asr.D == D and asr.n_mels == 80
    assert asr.prompt == [SOT, EN, TR, NOTS]
    res = asr.transcribe(np.zeros(16000, dtype=np.float32))
    assert res.text == "Namaste class" and res.tokens == 2
    assert res.encoder_ms > 0 and res.decoder_ms > 0 and res.backend == "onnx-qnn:cpu"


def test_build_asr_auto_prefers_npu_export(tmp_path, monkeypatch):
    from samwaad import asr as asr_mod

    build_whisper(tmp_path / "w")
    monkeypatch.setattr(asr_mod, "OnnxWhisperASR",
                        lambda folder, rt, tok, lang: ("npu-path", Path(folder).name))
    assert asr_mod.build_asr({"backend": "auto", "model": str(tmp_path / "w")}) == ("npu-path", "w")


# ------------------------------------------------------------------ OPUS-MT
LE, LD, MH, MHD, MV = 6, 5, 2, 3, 20
PAD, EOS = 1, 0


def build_marian(folder: Path):
    folder.mkdir(parents=True)
    enc_in = [helper.make_tensor_value_info("input_ids", TensorProto.INT32, (1, LE)),
              helper.make_tensor_value_info("encoder_attention_mask", TensorProto.INT32, (1, LE))]
    nodes, outs = [], []
    for kv in ("key", "value"):
        n = f"block_0_cross_{kv}_states"
        nodes.append(_const(n, np.zeros((1, MH, LE, MHD), np.float32)))
        outs.append(helper.make_tensor_value_info(n, TensorProto.FLOAT, (1, MH, LE, MHD)))
    _save(helper.make_graph(nodes, "enc", enc_in, outs), folder / "encoder.onnx")

    table = np.full((LD, MV), -1.0, np.float32)
    table[0, 5], table[1, 6], table[2, EOS] = 3.0, 3.0, 3.0
    dec_in = [helper.make_tensor_value_info("input_ids", TensorProto.INT32, (1, 1)),
              helper.make_tensor_value_info("encoder_attention_mask", TensorProto.INT32, (1, LE)),
              helper.make_tensor_value_info("position", TensorProto.INT32, (1,))]
    for kv in ("key", "value"):
        dec_in.append(helper.make_tensor_value_info(f"block_0_past_self_{kv}_states", TensorProto.FLOAT, (1, MH, LD - 1, MHD)))
        dec_in.append(helper.make_tensor_value_info(f"block_0_cross_{kv}_states", TensorProto.FLOAT, (1, MH, LE, MHD)))
    nodes = [_const("table", table), helper.make_node("Gather", ["table", "position"], ["row"], axis=0),
             _const("s3", np.array([1, 1, MV], np.int64)), helper.make_node("Reshape", ["row", "s3"], ["logits"])]
    outs = [helper.make_tensor_value_info("logits", TensorProto.FLOAT, (1, 1, MV))]
    for kv in ("key", "value"):
        n = f"block_0_present_self_{kv}_states"
        nodes.append(_const(n, np.ones((1, MH, 1, MHD), np.float32)))
        outs.append(helper.make_tensor_value_info(n, TensorProto.FLOAT, (1, MH, 1, MHD)))
    _save(helper.make_graph(nodes, "dec", dec_in, outs), folder / "decoder.onnx")


class FakeMarianTok:
    bos_token_id = None
    pad_token_id, eos_token_id = PAD, EOS
    words = {5: "नमस्ते", 6: "कक्षा"}

    def __call__(self, text, truncation=True, max_length=512):
        self.last = text
        return {"input_ids": [3, 4, EOS]}

    def get_vocab(self):
        return {">>tam<<": 17, ">>tel<<": 18}

    def decode(self, ids, skip_special_tokens=True):
        return " ".join(self.words.get(i, "?") for i in ids)


def test_onnx_marian_greedy_decode(tmp_path):
    from samwaad.translate import OnnxMarian

    build_marian(tmp_path / "opus_mt_en_hi")
    tok = FakeMarianTok()
    m = OnnxMarian(tmp_path / "opus_mt_en_hi", {"device": "cpu"}, tokenizer=tok)
    assert (m.Le, m.Ld, m.layers) == (LE, LD, [0])
    assert m.translate("Hello class") == "नमस्ते कक्षा"
    assert m.has_prefix(">>tam<<") and not m.has_prefix(">>ben<<")
    m.translate("Hello", ">>tam<<")
    assert tok.last == ">>tam<< Hello"


def test_hybrid_routing(monkeypatch, tmp_path):
    from samwaad import translate as T

    class FakeOpus:
        def __init__(self, folder, rt=None):
            self.device, self.name = "npu", folder.name

        def has_prefix(self, p):
            return p in (None, ">>tam<<")

        def translate(self, text, prefix=None):
            return f"{self.name}:{prefix}:{text}"

    for m in ("opus_mt_en_hi", "opus_mt_en_dra"):
        (tmp_path / m).mkdir()
    monkeypatch.setattr(T, "OnnxMarian", FakeOpus)
    h = T.HybridTranslator(npu_dir=str(tmp_path), quality_model=None)
    assert h.engine_for("hin_Deva") == "opus-mt:npu"
    assert h.engine_for("tam_Taml") == "opus-mt:npu"
    assert h.engine_for("ben_Beng") == "none"          # no NPU model, no IndicTrans2
    assert h.translate("hi", "tam_Taml")[0] == "opus_mt_en_dra:>>tam<<:hi"
    assert h.last_engine == "opus-mt:npu"

    class FakeQuality:
        def translate(self, text, tgt):
            return f"IT2:{tgt}", 1.0
    h.quality = FakeQuality()
    assert h.engine_for("ben_Beng") == "indictrans2:cpu"
    h.prefer = "quality"
    assert h.engine_for("hin_Deva") == "indictrans2:cpu"
    assert h.translate("x", "hin_Deva")[0] == "IT2:hin_Deva"
