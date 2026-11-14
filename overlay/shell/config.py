# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KERNEL = Path(os.environ.get("WEISHU_KERNEL_PATH", str(ROOT.parent / "advisor")))

DEFAULTS = {
    "kernel_path": str(DEFAULT_KERNEL),
    "kernel_python": str(DEFAULT_KERNEL / ".venv" / "Scripts" / "python.exe"),
    "opacity": 0.82,
    "ocr_interval_sec": 2.0,
    # Auto OCR loop: min gap after a cycle ends before next arm fires.
    "auto_ocr_gap_sec": 0.5,
    "auto_ocr_interval_sec": 4.5,
    "auto_ocr_backoff_sec": 8.0,
    "click_through_default": True,
    "hotkey_toggle": "ctrl+shift+w",
    "hotkey_analyze": "ctrl+shift+a",
    "window": {"width": 460, "height": 820, "x": None, "y": None},
    "defaults": {
        "round": 1,
        "gold": 10,
        "dispatch_level": 1,
        "target_bond": "",
        "difficulty": "standard",
    },
}


def load_config() -> dict:
    cfg = deepcopy(DEFAULTS)
    path = ROOT / "config.json"
    if path.is_file():
        with open(path, encoding="utf-8-sig") as f:
            user = json.load(f)
        _deep_update(cfg, user)
    # Resolve relative kernel paths against overlay root (config.json often
    # uses "../advisor" for monorepo layout).
    for key in ("kernel_path", "kernel_python"):
        raw = Path(str(cfg.get(key) or ""))
        if not raw.is_absolute():
            raw = (ROOT / raw).resolve()
            cfg[key] = str(raw)
    # Fall back if venv python missing
    kpy = Path(cfg["kernel_python"])
    if not kpy.is_file():
        cfg["kernel_python"] = os.environ.get("WEISHU_KERNEL_PYTHON") or "python"
    return cfg


def _deep_update(base: dict, overlay: dict) -> None:
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
