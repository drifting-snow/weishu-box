# -*- coding: utf-8 -*-
"""Tests for vision/resource_ocr.py pure helpers. No OCR model needed: OCR
outputs are faked as box dicts and tier pips are synthesized numpy images.
"""
import unittest

import numpy as np

from vision.resource_ocr import (
    Resources, parse_int, anchor_tile_center, count_tier_pips, _frac_box,
    PIP_BRIGHT,
)


def box(text, x0, x1, y0=0, y1=10, score=0.99):
    return {"text": text, "x0": x0, "x1": x1, "y0": y0, "y1": y1,
            "score": score}


class ParseIntTest(unittest.TestCase):
    def test_single_digit(self):
        self.assertEqual(parse_int([box("6", 0, 20)]), 6)

    def test_multi_digit_token(self):
        self.assertEqual(parse_int([box("25", 0, 40)]), 25)

    def test_split_digits_concatenated_left_to_right(self):
        # OCR can split 20 into separate '2' and '0' tokens
        self.assertEqual(parse_int([box("0", 30, 45), box("2", 0, 15)]), 20)

    def test_ignores_letter_noise(self):
        self.assertEqual(parse_int([box("6", 0, 20), box("EVEL", 30, 90)]), 6)

    def test_no_digits_returns_none(self):
        self.assertIsNone(parse_int([box("LEVEL", 0, 90)]))
        self.assertIsNone(parse_int([]))


class AnchorTileCenterTest(unittest.TestCase):
    def test_level_token_center(self):
        # full-frame coords already rebased; center of 300..450 is 375
        self.assertEqual(anchor_tile_center([box("LEVEL", 300, 450)]), 375)

    def test_ocr_typo_levei_still_matches(self):
        self.assertEqual(anchor_tile_center([box("LEVEI", 700, 848)]), 774)

    def test_case_and_space_insensitive(self):
        self.assertEqual(anchor_tile_center([box(" level ", 100, 200)]), 150)

    def test_missing_returns_none(self):
        self.assertIsNone(anchor_tile_center([box("升级", 0, 50), box("5", 60, 80)]))


class CountTierPipsTest(unittest.TestCase):
    def _image(self, width, bright_columns):
        # dark background, bright (>threshold) columns listed as (start, end)
        arr = np.full((100, width), 40, dtype=np.uint8)
        for start, end in bright_columns:
            arr[:, start:end] = 230
        return arr

    def test_one_pip(self):
        img = self._image(140, [(20, 38)])  # one 18px-wide bar
        self.assertEqual(count_tier_pips(img), 1)

    def test_two_pips(self):
        img = self._image(140, [(15, 34), (60, 81)])  # two wide bars
        self.assertEqual(count_tier_pips(img), 2)

    def test_thin_frame_line_is_ignored(self):
        # one real pip (18px) plus a 3px bright frame line; only the pip counts
        img = self._image(140, [(20, 38), (133, 136)])
        self.assertEqual(count_tier_pips(img), 1)

    def test_no_pip_on_dark_image(self):
        img = self._image(140, [])
        self.assertEqual(count_tier_pips(img), 0)

    def test_partial_height_bar_still_counts(self):
        # a tilted pip does not fill every row, but stays above the 25% gate
        arr = np.full((100, 60), 40, dtype=np.uint8)
        arr[20:80, 10:28] = 230  # 60% of rows bright over an 18px bar
        self.assertEqual(count_tier_pips(arr), 1)


class FracBoxTest(unittest.TestCase):
    def test_scales_with_resolution(self):
        frac = (0.5, 0.25, 0.1, 0.1)
        self.assertEqual(_frac_box(frac, 2560, 1440),
                         (1280, 360, 1536, 504))

    def test_known_roi_lands_on_calibrated_pixels(self):
        # gold ROI fraction was seeded from the 2560x1440 calibration
        left, top, right, bottom = _frac_box(
            (2330 / 2560, 1018 / 1440, 100 / 2560, 74 / 1440), 2560, 1440)
        self.assertAlmostEqual(left, 2330, delta=1)
        self.assertAlmostEqual(top, 1018, delta=1)


class ResourcesDataclassTest(unittest.TestCase):
    def test_defaults_and_dict(self):
        r = Resources()
        d = r.as_dict()
        self.assertIsNone(d["gold"])
        self.assertEqual(d["warnings"], [])

    def test_populated_dict(self):
        r = Resources(round=4, enemy_count=20, gold=6,
                      upgrade_cost=6, dispatch_level=2, warnings=[])
        d = r.as_dict()
        self.assertEqual(d["dispatch_level"], 2)
        self.assertEqual(d["enemy_count"], 20)


if __name__ == "__main__":
    unittest.main()
