# -*- coding: utf-8 -*-
"""Operator detail-panel + equipment OCR (shell-owned; runs inside sidecar).

ROIs calibrated on 2560×1440 selected-panel frames (2026-11-12/14 review):
  docs/weishu-equip-ocr-shots-20261114.md in the Project store.

Does not live in weishu-advisor — kernel stays untouched; this module imports
vision.match_text / BandOCREngine only when the sidecar process has the
kernel on PYTHONPATH.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

# Full-frame fractions (x0,y0,x1,y1) @ 2560×1440, 100% UI.
NAME_FRAC = (0.005, 0.235, 0.175, 0.345)
ELITE_FRAC = (0.005, 0.310, 0.080, 0.380)
EQUIP_NAME_FRAC = (0.055, 0.715, 0.280, 0.775)
EQUIP_BLOCK_FRAC = (0.010, 0.710, 0.300, 0.900)

# Badge centre → chibi click (design §8.2), scaled by height/1440.
CLICK_DX_AT_1440 = 32
CLICK_DY_AT_1440 = 122
# Hard click bounds = board ∪ bench (same as board_badge ROIs).
CLICK_ROIS = (
    (0.27, 0.20, 0.75, 0.58),
    (0.27, 0.55, 0.80, 0.72),
)

_ROMAN = {
    "Ⅰ": 1, "Ⅱ": 2, "Ⅲ": 3, "Ⅳ": 4, "Ⅴ": 5, "Ⅵ": 6,
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6,
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
}


def _box_px(width: int, height: int, frac: Tuple[float, float, float, float]):
    x0, y0, x1, y1 = frac
    return (
        int(x0 * width),
        int(y0 * height),
        int(x1 * width),
        int(y1 * height),
    )


def click_offset_px(height: int) -> Tuple[int, int]:
    scale = float(height) / 1440.0
    return int(round(CLICK_DX_AT_1440 * scale)), int(round(CLICK_DY_AT_1440 * scale))


def click_point_from_badge(
    cx: int, cy: int, width: int, height: int
) -> Tuple[int, int]:
    dx, dy = click_offset_px(height)
    return int(cx) + dx, int(cy) + dy


def click_in_allowed_roi(x: int, y: int, width: int, height: int) -> bool:
    if width <= 0 or height <= 0:
        return False
    fx, fy = x / float(width), y / float(height)
    for x0, y0, x1, y1 in CLICK_ROIS:
        if x0 <= fx <= x1 and y0 <= fy <= y1:
            return True
    return False


def _ocr_crop_texts(img, frac, ocr_engine) -> List[str]:
    box = _box_px(img.width, img.height, frac)
    crop = img.crop(box)
    raw = ocr_engine.detect(crop) or []
    texts: List[str] = []
    for b in raw:
        t = str(b.get("text") or "").strip()
        if t:
            texts.append(t)
    return texts


def _parse_elite_tier(texts: Sequence[str]) -> Optional[int]:
    blob = "".join(texts).upper().replace(" ", "")
    # Prefer multi-char Romans first (VI before V, III before I, …).
    for token in ("Ⅵ", "Ⅴ", "Ⅳ", "Ⅲ", "Ⅱ", "Ⅰ", "VI", "IV", "III", "II", "V", "I"):
        if token in blob or token.upper() in blob:
            return _ROMAN.get(token) or _ROMAN.get(token.upper())
    for ch in blob:
        if ch in _ROMAN:
            return _ROMAN[ch]
    return None


def recognize_panel_unit(
    img,
    *,
    operator_names: Sequence[str],
    item_names: Sequence[str],
    ocr_engine,
    correction: Optional[dict] = None,
) -> dict:
    """OCR left detail panel → operator name + optional equipment names.

    Returns dict with name (or None), elite/tier hints, equipment list,
    raw OCR snippets, and panel_open flag.
    """
    from vision.match_text import match_one

    name_texts = _ocr_crop_texts(img, NAME_FRAC, ocr_engine)
    elite_texts = _ocr_crop_texts(img, ELITE_FRAC, ocr_engine)
    equip_texts = _ocr_crop_texts(img, EQUIP_NAME_FRAC, ocr_engine)

    name = None
    for t in name_texts:
        hit = match_one(t, list(operator_names), correction, conservative=True)
        if hit:
            name = hit
            break
    # Fallback: join fragments (OCR sometimes splits 2–3 chars).
    if name is None and name_texts:
        joined = "".join(name_texts)
        hit = match_one(joined, list(operator_names), correction, conservative=True)
        if hit:
            name = hit

    equipment: List[str] = []
    equip_raw: List[str] = []
    for t in equip_texts:
        equip_raw.append(t)
        hit = match_one(t, list(item_names), correction, conservative=True)
        if hit and hit not in equipment:
            equipment.append(hit)
    if not equipment and equip_texts:
        joined = "".join(equip_texts)
        hit = match_one(joined, list(item_names), correction, conservative=True)
        if hit:
            equipment.append(hit)

    tier = _parse_elite_tier(elite_texts)
    return {
        "name": name,
        "equipment": equipment,
        "elite": bool(tier and tier >= 2),
        "tier_hint": tier,
        "panel_open": bool(name),
        "raw": {
            "name_texts": name_texts,
            "elite_texts": elite_texts,
            "equip_texts": equip_raw,
        },
    }
