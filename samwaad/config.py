"""Config loading: YAML file + dotted CLI overrides (e.g. runtime.device=npu)."""
from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import yaml

# Source checkout: the repo root. Packaged Samwaad.exe: the install folder (models/, sessions/ live there);
# read-only bundled files (config, samples, published benchmarks) fall back to PyInstaller's _internal dir.
FROZEN = getattr(sys, "frozen", False)
ROOT = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent.parent
BUNDLE = Path(getattr(sys, "_MEIPASS", ROOT))


def resource(rel: str | Path) -> Path:
    """A file that may live next to the app (user-editable) or inside the bundle."""
    p = ROOT / rel
    return p if p.exists() else BUNDLE / rel


DEFAULT_CONFIG = resource("config.yaml")


def _coerce(value: str) -> Any:
    low = value.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none"):
        return None
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value


def apply_overrides(cfg: dict, overrides: list[str] | None) -> dict:
    cfg = copy.deepcopy(cfg)
    for item in overrides or []:
        if "=" not in item:
            raise ValueError(f"Override must look like section.key=value, got {item!r}")
        dotted, raw = item.split("=", 1)
        node = cfg
        *parents, leaf = dotted.split(".")
        for p in parents:
            node = node.setdefault(p, {})
        node[leaf] = _coerce(raw)
    return cfg


def load_config(path: str | Path | None = None, overrides: list[str] | None = None) -> dict:
    path = Path(path) if path else DEFAULT_CONFIG
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg = apply_overrides(cfg, overrides)
    # Resolve relative paths against the repo root so the app works from any cwd.
    for section, key in (("vad", "model_path"), ("store", "dir"), ("auth", "dir"), ("llm", "genie_config"),
                         ("asr", "model"), ("translate", "npu_models")):
        if section == "asr" and cfg.get("asr", {}).get("backend") == "faster-whisper":
            continue  # there asr.model is a model size like "base", not a path
        val = cfg.get(section, {}).get(key)
        if val and not Path(val).is_absolute():
            cfg[section][key] = str(ROOT / val)
    return cfg
