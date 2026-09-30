"""ONNX Runtime session factory — the single CPU <-> NPU switch for the whole app.

Every model in Samwaad is created through `make_session`, which puts it on the Snapdragon
Hexagon NPU through the QNN Execution Provider (HTP backend) when available:

* onnxruntime-qnn 2.x  — plugin EP for stock onnxruntime ≥1.27: we register the library once
                          and bind the session to the NPU ep-device.
* onnxruntime-qnn 1.x  — QNNExecutionProvider is built in; we pass it as a provider.
* anything else         — CPU (dev laptops, CI), with a clear badge in the UI.

runtime.device: auto (NPU if present) | npu | cpu
"""
from __future__ import annotations

import logging
import platform
import threading

import onnxruntime as ort

log = logging.getLogger(__name__)

QNN = "QNNExecutionProvider"
CPU = "CPUExecutionProvider"
_lock = threading.Lock()
_plugin: dict = {"checked": False, "ok": False, "htp": None, "error": None}
_session_log: list[dict] = []  # which model landed on which EP — shown on the Performance page


def _register_plugin() -> bool:
    """Register the onnxruntime-qnn 2.x plugin EP once per process (no-op if not installed)."""
    with _lock:
        if _plugin["checked"]:
            return _plugin["ok"]
        _plugin["checked"] = True
        try:
            import onnxruntime_qnn as qnn_ep  # type: ignore
        except ImportError:
            return False
        try:
            if hasattr(ort, "register_execution_provider_library"):
                ort.register_execution_provider_library(QNN, qnn_ep.get_library_path())
                _plugin["htp"] = qnn_ep.get_qnn_htp_path()
                _plugin["ok"] = any(d.ep_name == QNN for d in ort.get_ep_devices())
        except Exception as e:  # already registered, or no NPU device on this machine
            _plugin["error"] = str(e)
            log.warning("QNN plugin registration failed: %s", e)
        return _plugin["ok"]


def available_providers() -> list[str]:
    provs = list(ort.get_available_providers())
    if QNN not in provs and _register_plugin():
        provs.insert(0, QNN)
    return provs


def npu_available() -> bool:
    return QNN in available_providers()


def wants_npu(runtime_cfg: dict | None) -> bool:
    device = str((runtime_cfg or {}).get("device", "auto")).lower()
    if device == "cpu":
        return False
    if device == "npu" and not npu_available():
        msg = (f"runtime.device=npu but the QNN Execution Provider isn't available (have {ort.get_available_providers()}). "
               "On a Snapdragon X PC: pip install onnxruntime-qnn")
        if not (runtime_cfg or {}).get("fallback_to_cpu", True):
            raise RuntimeError(msg)
        log.warning(msg + " — falling back to CPU.")
        return False
    return npu_available()


def _is_precompiled(model_path: str) -> bool:
    """AI Hub 'precompiled_qnn_onnx' = an EPContext .onnx wrapper next to a QNN context .bin."""
    from pathlib import Path
    return any(Path(model_path).parent.glob("*.bin"))


def _qnn_options(runtime_cfg: dict, model_path: str = "") -> dict:
    opts = {"htp_performance_mode": runtime_cfg.get("htp_performance_mode", "burst"),
            "htp_graph_finalization_optimization_mode": "3"}
    if _plugin["ok"] and _plugin["htp"]:
        opts["backend_path"] = _plugin["htp"]
    else:
        opts["backend_path"] = runtime_cfg.get("qnn_backend", "QnnHtp.dll")
    if runtime_cfg.get("htp_fp16", True) and not _is_precompiled(model_path):
        opts["enable_htp_fp16_precision"] = "1"  # fp32 graphs run in fp16 on the HTP
    return opts


def make_session(model_path: str, runtime_cfg: dict | None = None) -> ort.InferenceSession:
    runtime_cfg = runtime_cfg or {}
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess = None
    if wants_npu(runtime_cfg):
        opts = _qnn_options(runtime_cfg, model_path)
        try:
            if QNN in ort.get_available_providers():             # onnxruntime-qnn 1.x
                sess = ort.InferenceSession(model_path, sess_options=so, providers=[(QNN, opts), CPU])
            else:                                                # onnxruntime-qnn 2.x plugin
                devices = [d for d in ort.get_ep_devices() if d.ep_name == QNN]
                so.add_provider_for_devices(devices, opts)
                sess = ort.InferenceSession(model_path, sess_options=so)
        except Exception as e:
            if not runtime_cfg.get("fallback_to_cpu", True):
                raise
            log.warning("QNN couldn't load %s (%s) — using CPU for this model.", model_path, e)
            so = ort.SessionOptions()
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    if sess is None:
        sess = ort.InferenceSession(model_path, sess_options=so, providers=[CPU])
    ep = sess.get_providers()[0]
    _session_log.append({"model": model_path.replace("\\", "/").split("/models/")[-1], "provider": ep})
    log.info("Loaded %s on %s", model_path, ep)
    return sess


def session_log() -> list[dict]:
    return list(_session_log)


def describe(runtime_cfg: dict | None = None) -> dict:
    """Status blob for the UI badge, `samwaad status` and the Performance page."""
    on_npu = wants_npu(runtime_cfg)
    return {
        "machine": platform.machine(),
        "system": f"{platform.system()} {platform.release()}",
        "processor": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "onnxruntime": ort.__version__,
        "execution_provider": QNN if on_npu else CPU,
        "on_npu": on_npu,
        "qnn_plugin": _plugin["ok"],
        "available": available_providers(),
        "sessions": session_log(),
    }
