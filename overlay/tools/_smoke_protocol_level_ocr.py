# -*- coding: utf-8 -*-
"""Smoke: OCR difficulty-select 规程等级 from ref shot."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageOps
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ADVISOR = ROOT.parent / "weishu-advisor"
sys.path.insert(0, str(ADVISOR))
sys.path.insert(0, str(ROOT / "shell"))

from vision.shop_band_ocr import BandOCREngine  # noqa: E402


def main() -> int:
    shot = ROOT / "session" / "ref_difficulty_select_13.png"
    img = Image.open(shot).convert("RGB")
    w, h = img.size
    eng = BandOCREngine()
    small = img.resize((w // 2, h // 2))
    raw = eng.detect(small)
    print("half count", len(raw))
    for b in raw:
        t = str(b.get("text") or "")
        keys = ("规程", "等级", "模拟", "认证", "强度", "开始", "145", "12", "13", "14", "11")
        if any(k in t for k in keys) or t.isdigit():
            print(
                "HIT",
                repr(t),
                "xy",
                round(float(b.get("x0") or 0), 1),
                round(float(b.get("y0") or 0), 1),
                "sc",
                round(float(b.get("score") or 0), 2),
            )

    crop = img.crop((40, 1260, 1100, 1435))
    print("crop", crop.size)
    for b in eng.detect(crop):
        print(" crop", repr(b.get("text")), round(float(b.get("score") or 0), 2))

    arr = np.asarray(crop)
    r = arr[:, :, 0].astype(int)
    g = arr[:, :, 1].astype(int)
    bl = arr[:, :, 2].astype(int)
    mask = (r > 140) & ((r - g) > 40) & ((r - bl) > 40)
    red = np.zeros_like(arr)
    red[mask] = 255
    inv = ImageOps.invert(Image.fromarray(red).convert("L")).convert("RGB")
    inv = inv.resize((inv.width * 2, inv.height * 2))
    print("red-pre:")
    for b in eng.detect(inv):
        print(" ", repr(b.get("text")), round(float(b.get("score") or 0), 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
