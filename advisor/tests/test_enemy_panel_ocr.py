# -*- coding: utf-8 -*-
"""Pure-logic tests for vision/enemy_panel_ocr.py (no OCR model / PIL)."""
import unittest

from vision.enemy_panel_ocr import (
    panel_boxes_to_enemy_names, MIN_NAME_HEIGHT_FRAC,
)

SIZE = (2560, 1440)
NAMES = ["源石虫", "寻险水手"]
MIN_H = MIN_NAME_HEIGHT_FRAC * SIZE[1]  # ~34.6 px at 1440p


def box(text, y0, h, x0=1750):
    return {"text": text, "score": 0.99, "x0": x0, "x1": x0 + 120,
            "y0": y0, "y1": y0 + h}


class PanelBoxesToNamesTest(unittest.TestCase):
    def test_keeps_names_top_to_bottom(self):
        boxes = [
            box("敌人", 165, 45),          # title: name-scale but not a catalog name
            box("源石虫", 245, 45),
            box("寻险水手", 475, 45),
            box("经过悬索桥或被传送时移动速度短暂提升", 540, 28),  # trait, small font
        ]
        self.assertEqual(
            panel_boxes_to_enemy_names(boxes, SIZE, NAMES),
            ["源石虫", "寻险水手"])

    def test_drops_small_font_trait_lines(self):
        self.assertLess(28, MIN_H)  # sanity: trait font is below the gate
        boxes = [box("寻险水手", 475, 28)]  # name text but trait-sized glyph
        self.assertEqual(panel_boxes_to_enemy_names(boxes, SIZE, NAMES), [])

    def test_full_names_snap_conservatively(self):
        # Real panel OCR reads whole names (~0.99 confidence); these must hit.
        boxes = [
            box("源石虫", 245, 45),
            box("寻险水手", 475, 45),
        ]
        self.assertEqual(
            panel_boxes_to_enemy_names(boxes, SIZE, NAMES),
            ["源石虫", "寻险水手"])

    def test_ambiguous_truncation_refused_not_mis_snapped(self):
        # Conservative matching refuses crowded/short truncations rather than
        # confidently snapping to the wrong near name (e.g. '石虫' has many
        # 源石虫 variants; '险水手' ties 历险水手/寻险水手).
        boxes = [
            box("石虫", 245, 45),     # ambiguous -> dropped
            box("险水手", 475, 45),   # tied candidates -> dropped
            box("寻险水手", 600, 45),  # full name still resolves
        ]
        self.assertEqual(
            panel_boxes_to_enemy_names(boxes, SIZE, NAMES), ["寻险水手"])

    def test_dedupes_split_name_preserving_order(self):
        boxes = [
            box("寻险水手", 475, 45),
            box("寻险水手", 478, 45),   # duplicate / split detection
            box("源石虫", 245, 45),
        ]
        # sorted by y0 then de-duped: 源石虫 (245) before 寻险水手 (475)
        self.assertEqual(
            panel_boxes_to_enemy_names(boxes, SIZE, NAMES),
            ["源石虫", "寻险水手"])

    def test_unknown_text_dropped(self):
        boxes = [box("神秘Boss", 245, 45), box("源石虫", 400, 45)]
        self.assertEqual(
            panel_boxes_to_enemy_names(boxes, SIZE, NAMES), ["源石虫"])

    def test_empty(self):
        self.assertEqual(panel_boxes_to_enemy_names([], SIZE, NAMES), [])


if __name__ == "__main__":
    unittest.main()
