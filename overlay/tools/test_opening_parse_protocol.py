# -*- coding: utf-8 -*-
"""Unit tests: difficulty-select 规程等级 pick (no OCR model)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shell"))

from opening_parse import (  # noqa: E402
    detect_screen,
    parse_opening_detections,
    pick_procedure_level,
)


def _box(text: str, cx: float, cy: float, score: float = 0.99) -> dict:
    return {"text": text, "cx": cx, "cy": cy, "score": score, "x0": 0, "x1": 1, "y0": 0, "y1": 1}


class ProtocolLevelParseTests(unittest.TestCase):
    def test_detect_difficulty_select(self):
        texts = ["请选择模拟难度", "规程等级13", "开始模拟", "认证获取效率", "模拟强度"]
        self.assertEqual(detect_screen(texts), "difficulty_select")

    def test_pick_prefers_bottom_bar_over_list(self):
        boxes = [
            _box("规程等级15", 0.80, 0.12),
            _box("规程等级14", 0.80, 0.28),
            _box("规程等级13", 0.80, 0.43),
            _box("规程等级12", 0.80, 0.58),
            _box("规程等级13", 0.08, 0.92),  # bottom summary
            _box("开始模拟", 0.90, 0.92),
            _box("认证获取效率", 0.20, 0.93),
        ]
        self.assertEqual(pick_procedure_level(boxes, "difficulty_select"), 13)

    def test_pick_frequency_when_no_bottom(self):
        boxes = [
            _box("规程等级15", 0.80, 0.12),
            _box("规程等级13", 0.80, 0.43),
            _box("规程等级13", 0.75, 0.44),  # selected row duplicated
        ]
        self.assertEqual(pick_procedure_level(boxes, "difficulty_select"), 13)

    def test_parse_opening_maps_procedure_level(self):
        raw = [
            {"text": "请选择模拟难度", "x0": 100, "x1": 200, "y0": 20, "y1": 40, "score": 1},
            {"text": "规程等级15", "x0": 900, "x1": 1100, "y0": 80, "y1": 120, "score": 1},
            {"text": "规程等级13", "x0": 900, "x1": 1100, "y0": 300, "y1": 340, "score": 1},
            {"text": "规程等级13", "x0": 40, "x1": 260, "y0": 1300, "y1": 1360, "score": 1},
            {"text": "开始模拟", "x0": 2000, "x1": 2300, "y0": 1280, "y1": 1380, "score": 1},
            {"text": "认证获取效率", "x0": 300, "x1": 500, "y0": 1320, "y1": 1380, "score": 1},
        ]
        parsed = parse_opening_detections(
            raw, img_w=2560, img_h=1440, bond_names=[], operator_names=[]
        )
        self.assertEqual(parsed["screen"], "difficulty_select")
        self.assertEqual(parsed["procedure_level"], 13)

    def test_contract_badge_still_works(self):
        raw = [
            {"text": "1/3确认本局信息", "x0": 1000, "x1": 1400, "y0": 20, "y1": 50, "score": 1},
            {"text": "规程等级13", "x0": 80, "x1": 280, "y0": 30, "y1": 70, "score": 1},
            {"text": "核心盟约", "x0": 100, "x1": 200, "y0": 200, "y1": 240, "score": 1},
        ]
        parsed = parse_opening_detections(
            raw, img_w=2560, img_h=1440, bond_names=[], operator_names=[]
        )
        self.assertEqual(parsed["screen"], "contract")
        self.assertEqual(parsed["procedure_level"], 13)


if __name__ == "__main__":
    unittest.main()
