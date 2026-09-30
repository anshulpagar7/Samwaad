"""English -> Indian-language translation.

Two engines, routed per language by `HybridTranslator`:

- OPUS-MT on the NPU  : Helsinki-NLP Marian models (en-hi, en-mr, en-ml, and the multi-target
                        en-dra / en-inc models), compiled by Qualcomm AI Hub with the same
                        `templates.opus_mt` recipe AI Hub uses for its published opus_mt_* models
                        (see tools/export_opus_mt.py). Small, static-shaped, NPU-friendly.
- IndicTrans2 (CPU)   : AI4Bharat's distilled 200M model — best quality, all 22 scheduled
                        languages. Used when a language has no NPU model, or when the user picks
                        "Best quality" in Settings.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np

from .config import ROOT, resource  # noqa: E402

log = logging.getLogger(__name__)

LANGUAGES = {
    "hin_Deva": "Hindi", "mar_Deva": "Marathi", "tam_Taml": "Tamil", "tel_Telu": "Telugu",
    "ben_Beng": "Bengali", "guj_Gujr": "Gujarati", "kan_Knda": "Kannada",
    "mal_Mlym": "Malayalam", "pan_Guru": "Punjabi", "ory_Orya": "Odia", "urd_Arab": "Urdu",
}
NATIVE = {
    "hin_Deva": "हिन्दी", "mar_Deva": "मराठी", "tam_Taml": "தமிழ்", "tel_Telu": "తెలుగు", "ben_Beng": "বাংলা",
    "guj_Gujr": "ગુજરાતી", "kan_Knda": "ಕನ್ನಡ", "mal_Mlym": "മലയാളം", "pan_Guru": "ਪੰਜਾਬੀ", "ory_Orya": "ଓଡ଼ିଆ",
    "urd_Arab": "اردو",
}

# target -> (OPUS-MT model id, target-language token for multi-target models)
OPUS_ROUTES = {
    "hin_Deva": ("opus_mt_en_hi", None), "mar_Deva": ("opus_mt_en_mr", None),
    "mal_Mlym": ("opus_mt_en_ml", None),
    "tam_Taml": ("opus_mt_en_dra", ">>tam<<"), "tel_Telu": ("opus_mt_en_dra", ">>tel<<"),
    "kan_Knda": ("opus_mt_en_dra", ">>kan<<"),
    "ben_Beng": ("opus_mt_en_inc", ">>ben<<"), "guj_Gujr": ("opus_mt_en_inc", ">>guj<<"),
    "ory_Orya": ("opus_mt_en_inc", ">>ori<<"), "urd_Arab": ("opus_mt_en_inc", ">>urd<<"),
}
OPUS_HF = {m: f"Helsinki-NLP/{m.replace('_', '-')}" for m, _ in OPUS_ROUTES.values()}


class NoTranslate:
    name = "none"
    target = None
    last_engine = "none"

    def translate(self, text: str, target: str | None = None) -> tuple[str, float]:
        return "", 0.0

    def engines(self) -> dict:
        return {}


class MockTranslate:
    name = "mock"
    last_engine = "mock:cpu"

    def __init__(self, target="hin_Deva", **_):
        self.target = target

    def translate(self, text: str, target: str | None = None) -> tuple[str, float]:
        return f"[{target or self.target}] {text}", 0.5

    def engines(self) -> dict:
        return {k: "mock:cpu" for k in LANGUAGES}


class ScriptTranslate:
    """Looks translations up in samples/demo_script.json (UI demos without models)."""
    name = "script"
    last_engine = "script:cpu"

    def __init__(self, script: str, target="hin_Deva", **_):
        self.table = {l["en"]: l for l in json.loads(Path(script).read_text(encoding="utf-8"))["lines"]}
        self.target = target

    def translate(self, text: str, target: str | None = None) -> tuple[str, float]:
        row, tgt = self.table.get(text, {}), target or self.target
        return row.get(tgt) or f"(demo script has Hindi, Marathi and Tamil — {LANGUAGES.get(tgt, tgt)} needs the real models)", 0.0

    def engines(self) -> dict:
        return {k: "script:cpu" for k in LANGUAGES}


class IndicTrans2:
    name = "indictrans2"
    device = "cpu"

    def __init__(self, model="ai4bharat/indictrans2-en-indic-dist-200M", target="hin_Deva", **_):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        try:
            from IndicTransToolkit.processor import IndicProcessor
        except ImportError:  # older/newer toolkit layouts
            from IndicTransToolkit import IndicProcessor

        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model, trust_remote_code=True)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model, trust_remote_code=True).eval()
        self.ip = IndicProcessor(inference=True)
        self.target = target
        self.last_engine = "indictrans2:cpu"

    def translate(self, text: str, target: str | None = None) -> tuple[str, float]:
        tgt = target or self.target
        if not text.strip():
            return "", 0.0
        t0 = time.perf_counter()
        batch = self.ip.preprocess_batch([text], src_lang="eng_Latn", tgt_lang=tgt)
        inputs = self.tok(batch, truncation=True, padding="longest", return_tensors="pt")
        with self.torch.inference_mode():
            gen = self.model.generate(**inputs, use_cache=True, min_length=0, max_length=256, num_beams=1)
        decoded = self.tok.batch_decode(gen, skip_special_tokens=True, clean_up_tokenization_spaces=True)
        out = self.ip.postprocess_batch(decoded, lang=tgt)[0]
        return out, (time.perf_counter() - t0) * 1000


class OnnxMarian:
    """One OPUS-MT model exported by tools/export_opus_mt.py (AI Hub `templates.opus_mt` I/O):

      encoder  input_ids (1, Le) int32, encoder_attention_mask (1, Le) int32
               -> block_{i}_cross_key_states, block_{i}_cross_value_states
      decoder  input_ids (1,1) int32, encoder_attention_mask (1, Le), position (1,) int32,
               block_{i}_past_self_{key,value}_states (1, H, Ld-1, hd), block_{i}_cross_{key,value}_states
               -> logits, block_{i}_present_self_{key,value}_states
    """

    def __init__(self, folder: Path, runtime_cfg: dict | None = None, tokenizer=None):
        from .onnx_io import Feeder, find_component
        from .runtime import make_session

        meta_path = folder / "samwaad_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        self.hf_id = meta.get("hf_id") or OPUS_HF.get(folder.name, "")
        self.enc = make_session(str(find_component(folder, "encoder")), runtime_cfg)
        self.dec = make_session(str(find_component(folder, "decoder")), runtime_cfg)
        self.ef, self.df = Feeder(self.enc), Feeder(self.dec)
        self.device = "npu" if self.dec.get_providers()[0] == "QNNExecutionProvider" else "cpu"
        self.Le = self.ef.shape("input_ids")[1]
        self.layers = sorted({int(n.split("_")[1]) for n in self.df.inputs if n.endswith("_past_self_key_states")})
        self.Ld = self.df.shape(f"block_{self.layers[0]}_past_self_key_states")[2] + 1
        if tokenizer is None:
            from transformers import AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained(self.hf_id)
        self.tok = tokenizer
        self.bos = self.tok.bos_token_id if getattr(self.tok, "bos_token_id", None) is not None else self.tok.pad_token_id
        self.eos, self.pad = self.tok.eos_token_id, self.tok.pad_token_id

    def has_prefix(self, prefix: str | None) -> bool:
        if not prefix:
            return True
        vocab = self.tok.get_vocab() if hasattr(self.tok, "get_vocab") else {}
        return prefix in vocab

    def translate(self, text: str, prefix: str | None = None) -> str:
        src = f"{prefix} {text}" if prefix else text
        ids = list(self.tok(src, truncation=True, max_length=self.Le)["input_ids"])[: self.Le]
        mask = [1] * len(ids) + [0] * (self.Le - len(ids))
        ids = ids + [self.pad] * (self.Le - len(ids))
        input_ids = self.ef.cast("input_ids", np.array([ids]))
        enc_mask = self.ef.cast("encoder_attention_mask", np.array([mask]))
        enc_out = dict(zip(self.ef.outputs, self.enc.run(None, {"input_ids": input_ids, "encoder_attention_mask": enc_mask})))

        feed = {"encoder_attention_mask": self.df.cast("encoder_attention_mask", enc_mask)}
        for i in self.layers:
            for kv in ("key", "value"):
                feed[f"block_{i}_past_self_{kv}_states"] = self.df.zeros(f"block_{i}_past_self_{kv}_states")
                cname = f"block_{i}_cross_{kv}_states"
                feed[cname] = self.df.cast(cname, enc_out[cname])
        tok_dtype, pos_dtype = self.df.dtype("input_ids"), self.df.dtype("position")
        token, out = self.bos, []
        for step in range(self.Ld - 1):
            feed["input_ids"] = np.array([[token]], dtype=tok_dtype)
            feed["position"] = np.array([step], dtype=pos_dtype)
            res = dict(zip(self.df.outputs, self.dec.run(None, feed)))
            token = int(res["logits"].reshape(-1).argmax())
            if token == self.eos:
                break
            out.append(token)
            for i in self.layers:
                for kv in ("key", "value"):
                    past = feed[f"block_{i}_past_self_{kv}_states"]
                    present = res[f"block_{i}_present_self_{kv}_states"]
                    if present.shape == past.shape:          # graph returns the whole updated cache
                        feed[f"block_{i}_past_self_{kv}_states"] = present
                    else:                                    # graph returns just this step's slice
                        past[:, :, step:step + 1, :] = present.reshape(past.shape[0], past.shape[1], -1, past.shape[3])[:, :, -1:, :]
        return self.tok.decode(out, skip_special_tokens=True).strip()


class HybridTranslator:
    """Routes each target language to the fastest engine available on this machine."""

    name = "hybrid"

    def __init__(self, npu_dir: str | None = None, quality_model: str | None = None, prefer: str = "npu",
                 runtime_cfg: dict | None = None, target: str = "hin_Deva", load_quality: bool = True):
        self.target, self.prefer = target, prefer
        self.last_engine = "none"
        self.opus: dict[str, OnnxMarian] = {}
        folder = Path(npu_dir) if npu_dir else ROOT / "models" / "opus_mt"
        if folder.exists():
            for sub in sorted(p for p in folder.iterdir() if p.is_dir()):
                try:
                    self.opus[sub.name] = OnnxMarian(sub, runtime_cfg)
                    log.info("OPUS-MT %s loaded on %s", sub.name, self.opus[sub.name].device)
                except Exception as e:
                    log.warning("Skipping OPUS-MT %s: %s", sub.name, e)
        self.quality = None
        if load_quality and quality_model:
            try:
                self.quality = IndicTrans2(quality_model, target)
            except Exception as e:
                log.warning("IndicTrans2 unavailable (%s); NPU models only.", e)

    def _npu_for(self, target: str):
        model_id, prefix = OPUS_ROUTES.get(target, (None, None))
        m = self.opus.get(model_id)
        return (m, prefix) if m and m.has_prefix(prefix) else (None, None)

    def engine_for(self, target: str) -> str:
        m, _ = self._npu_for(target)
        if m and (self.prefer == "npu" or not self.quality):
            return f"opus-mt:{m.device}"
        if self.quality:
            return "indictrans2:cpu"
        return f"opus-mt:{m.device}" if m else "none"

    def engines(self) -> dict:
        return {t: self.engine_for(t) for t in LANGUAGES}

    def translate(self, text: str, target: str | None = None) -> tuple[str, float]:
        tgt = target or self.target
        if not text.strip():
            return "", 0.0
        t0 = time.perf_counter()
        engine = self.engine_for(tgt)
        if engine.startswith("opus-mt"):
            m, prefix = self._npu_for(tgt)
            out = m.translate(text, prefix)
        elif engine.startswith("indictrans2"):
            out, _ = self.quality.translate(text, tgt)
        else:
            out = ""
        self.last_engine = engine
        return out, (time.perf_counter() - t0) * 1000


def build_translator(tr_cfg: dict, runtime_cfg: dict | None = None):
    backend = tr_cfg.get("backend", "hybrid")
    target = tr_cfg.get("target", "hin_Deva")
    if backend == "none":
        return NoTranslate()
    if backend == "mock":
        return MockTranslate(target)
    if backend == "script":
        return ScriptTranslate(tr_cfg.get("script") or str(resource("samples/demo_script.json")), target)
    if backend in ("hybrid", "indictrans2", "opus-onnx"):
        t = HybridTranslator(
            npu_dir=tr_cfg.get("npu_models") if backend != "indictrans2" else "/nonexistent",
            quality_model=(tr_cfg.get("quality_model") or tr_cfg.get("model")) if backend != "opus-onnx" else None,
            prefer=tr_cfg.get("prefer", "npu"), runtime_cfg=runtime_cfg, target=target,
        )
        if not t.opus and not t.quality:
            log.error("No translation engine could be loaded — captions will run without translation.")
            return NoTranslate()
        return t
    raise ValueError(f"Unknown translate.backend {backend!r}")
