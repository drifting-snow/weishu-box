# -*- coding: utf-8 -*-
"""Offline test for the OCR shop pipeline using a scripted fake OCR engine.

No real OCR model is required: the fake engine returns queued strings in the
exact call order the recognizer makes (gold, then per-slot price+name), which
lets us verify ROI cropping, preprocessing, digit correction, dictionary
fuzzy matching and GameState assembly deterministically.
"""
import os
import sys
import unittest

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from advisor.data import Dataset
from advisor.model import GameState
from vision.shop_ocr import OcrShopRecognizer


class ScriptedOCR:
    """Returns queued readings; is_number handling is already done by caller."""
    name = "scripted"

    def __init__(self, readings):
        self._q = list(readings)
        self.calls = 0

    def read(self, img):
        out = self._q[self.calls] if self.calls < len(self._q) else ""
        self.calls += 1
        return out


class OcrPipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()

    def _build(self, readings):
        img = Image.new("RGB", (1920, 1080), (30, 30, 40))
        rec = OcrShopRecognizer(self.ds, ocr_engine=ScriptedOCR(readings),
                                ui_scale="100%")
        return rec.recognize(img)

    def test_digit_correction_and_dictionary_snap(self):
        # call order: gold, then for each of 6 slots: price, name
        # use a real operator name from the dataset so dictionary match succeeds
        op_name = self.ds.operators[0]["name"]
        item_name = self.ds.items[0]["name"]
        readings = [
            "9",                 # gold
            "3", op_name,        # slot 0 operator, correct price
            "1", item_name,      # slot 1 item
            "O", "不存在的干员xyz",   # slot 2: digit O->0 correction, unknown name
            "", "",              # slot 3 empty
            "", "",              # slot 4 empty
            "", "",              # slot 5 empty
        ]
        st: GameState = self._build(readings)
        self.assertEqual(st.gold, 9)
        kinds = [c.kind for c in st.shop]
        self.assertEqual(kinds[0], "operator")
        self.assertEqual(st.shop[0].name, op_name)
        self.assertEqual(st.shop[0].price, 3)
        self.assertEqual(kinds[1], "item")
        self.assertEqual(st.shop[1].name, item_name)
        # O corrected to 0, but name unknown -> card stays unknown with price kept
        self.assertEqual(st.shop[2].kind, "unknown")
        self.assertEqual(st.shop[2].price, 0)
        self.assertIn("ocr_text", st.shop[2].raw)
        # empties are unknown too
        self.assertEqual(st.shop[3].kind, "unknown")

    def test_fuzzy_correction_map(self):
        # a deliberately mistyped reading close to a real name should still snap
        # via the explicit correction map (铜 -> 锏) if a dictionary entry exists
        target = next((o["name"] for o in self.ds.operators if "锏" in o["name"]), None)
        if not target:
            self.skipTest("dataset has no 锏 operator to test correction map")
        mistyped = target.replace("锏", "铜")
        readings = ["5", "3", mistyped] + ["", ""] * 5
        st = self._build(readings)
        self.assertEqual(st.shop[0].kind, "operator")
        self.assertEqual(st.shop[0].name, target)


if __name__ == "__main__":
    unittest.main(verbosity=2)
