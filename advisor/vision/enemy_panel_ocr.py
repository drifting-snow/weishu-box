# -*- coding: utf-8 -*-
"""Enemy magnifier-panel OCR (read-only vision layer).

The in-game magnifier panel lists the next wave's enemies as a vertical stack:
each row has a portrait, a large enemy NAME, and (sometimes) a smaller
qualitative trait line underneath. This module OCRs ONLY the names; tactical
category resolution is deliberately left to advisor/enemy_catalog.py so the
vision layer never encodes game rules.

Two filters keep trait sentences and the panel title out of the result:
  1. font-size gate -- measured on a real 2560x1440 client, enemy names are
     ~0.031 of screen height while trait lines are ~0.019; anything below the
     name-height threshold is dropped before matching;
  2. dictionary snap -- only text that fuzzy-matches a known catalog enemy
     name survives, so the static "敌人" title and any residual trait text
     fail to match and are discarded.

Pure mapping lives in panel_boxes_to_enemy_names (unit-tested with fake boxes,
no OCR model); EnemyPanelRecognizer wraps the optional RapidOCR dependency.
"""
from typing import List, Optional, Tuple

from .match_text import match_one
from .shop_band_ocr import BandOCREngine

# Panel dark-box measured on a real client: bbox frac ~(0.584,0.104)-(0.919,0.471).
# Padded slightly so name glyphs (fx0 ~= 0.67) are never clipped at the edge.
PANEL_FRAC = (0.575, 0.095, 0.360, 0.400)  # (x, y, w, h) of full screenshot
# Enemy names measure h/H ~= 0.031; trait lines ~= 0.019. Keep only name-scale.
MIN_NAME_HEIGHT_FRAC = 0.024


def _panel_pixel_box(width: int, height: int):
    x, y, w, h = PANEL_FRAC
    return (int(x * width), int(y * height),
            int((x + w) * width), int((y + h) * height))


def panel_boxes_to_enemy_names(boxes: List[dict], image_size: Tuple[int, int],
                               catalog_names: List[str],
                               correction: Optional[dict] = None) -> List[str]:
    """Pure: map raw OCR boxes inside the panel to ordered catalog names.

    ``boxes`` items need text/x0/x1/y0/y1 in FULL-image pixel coordinates.
    Returns canonical enemy names top-to-bottom, de-duplicated while preserving
    first-seen order. Anything that does not snap to a catalog name is dropped
    (title, trait sentences, UI chrome).
    """
    width, height = image_size
    min_h = MIN_NAME_HEIGHT_FRAC * height
    rows = []
    for b in boxes:
        glyph_h = b["y1"] - b["y0"]
        if glyph_h < min_h:
            continue  # trait line / small caption, not an enemy name
        canonical = match_one(b["text"], catalog_names, correction,
                              conservative=True)
        if canonical is None:
            continue
        rows.append((b["y0"], canonical))
    # Top-to-bottom reading order; de-duplicate (a name split across boxes).
    rows.sort(key=lambda r: r[0])
    ordered = []
    for _, name in rows:
        if name not in ordered:
            ordered.append(name)
    return ordered


class EnemyPanelRecognizer:
    """OCR the magnifier panel into a list of canonical enemy names."""

    def __init__(self, catalog_names: List[str], ocr_engine=None,
                 correction: Optional[dict] = None):
        self.catalog_names = list(catalog_names)
        self.ocr = ocr_engine
        self.correction = correction

    def _engine(self):
        if self.ocr is None:
            self.ocr = BandOCREngine()
        return self.ocr

    def recognize_names(self, img) -> List[str]:
        box = _panel_pixel_box(img.width, img.height)
        panel = img.crop(box)
        off_x, off_y = box[0], box[1]
        raw = self._engine().detect(panel)
        # Re-base OCR coordinates back into full-image space for the height gate.
        for b in raw:
            b["x0"] += off_x
            b["x1"] += off_x
            b["y0"] += off_y
            b["y1"] += off_y
        return panel_boxes_to_enemy_names(
            raw, (img.width, img.height), self.catalog_names, self.correction)
