# -*- coding: utf-8 -*-
"""Stdlib unittest for advisor/regulation_hp.py (act3 leader HP curve).

Self-owned module: must not import advisor.scaling (the retired act1/2 layer).
The numeric anchors come from the public PRTS user-measured regulation leader
HP table; the point of these tests is that the exact closed form reproduces
every measured point with zero error.
Run: python -m unittest tests.test_regulation_hp
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from advisor import regulation_hp as rh  # noqa: E402


class RegulationHpCurveTest(unittest.TestCase):
    # Measured PRTS points (leader: level-1 base HP, and L8/L14/L20 actuals).
    MEASURED = {
        # jia xiang di : zhou
        "zhou":  (283680, 945600, 2364000, 3940000, 226944),
        # jia xiang di : chong
        "chong": (162000, 540000, 1350000, 2250000, 129600),
    }

    def test_module_does_not_touch_legacy_scaling(self):
        path = os.path.join(ROOT, "advisor", "regulation_hp.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("import scaling", src)
        self.assertNotIn("from advisor.scaling", src)

    def test_table_spans_levels_1_to_20(self):
        table = rh.multiplier_table()
        self.assertEqual(sorted(table), list(range(1, 21)))

    def test_exact_anchor_fractions(self):
        self.assertAlmostEqual(rh.regulation_hp_multiplier(1), 1.0, places=9)
        self.assertAlmostEqual(rh.regulation_hp_multiplier(8), 10 / 3, places=9)
        self.assertAlmostEqual(rh.regulation_hp_multiplier(14), 25 / 3, places=9)
        self.assertAlmostEqual(rh.regulation_hp_multiplier(20), 125 / 9, places=9)

    def test_segment_step_pattern(self):
        t = rh.multiplier_table()
        # L2..L8 step of 1/3
        self.assertAlmostEqual(t[2] - t[1], 1 / 3, places=9)
        self.assertAlmostEqual(t[8] - t[7], 1 / 3, places=9)
        # L9..L14 step of 5/6
        self.assertAlmostEqual(t[9] - t[8], 5 / 6, places=9)
        self.assertAlmostEqual(t[14] - t[13], 5 / 6, places=9)
        # L15..L20 step of 25/27
        self.assertAlmostEqual(t[15] - t[14], 25 / 27, places=9)
        self.assertAlmostEqual(t[20] - t[19], 25 / 27, places=9)

    def test_reconstructs_every_measured_point_exactly(self):
        for base, hp8, hp14, hp20, quick in self.MEASURED.values():
            self.assertEqual(rh.regulation_hp(base, 1), float(base))
            self.assertEqual(rh.regulation_hp(base, 8), float(hp8))
            self.assertEqual(rh.regulation_hp(base, 14), float(hp14))
            self.assertEqual(rh.regulation_hp(base, 20), float(hp20))
            # quick simulation = 0.8 * L1 base
            self.assertEqual(rh.quick_sim_hp(base), float(quick))

    def test_difficulty_modes_anchor_to_same_curve(self):
        self.assertEqual(rh.difficulty_hp_multiplier("standard"),
                         rh.regulation_hp_multiplier(1))
        self.assertEqual(rh.difficulty_hp_multiplier("hard"),
                         rh.regulation_hp_multiplier(8))
        self.assertEqual(rh.difficulty_hp_multiplier("desperate"),
                         rh.regulation_hp_multiplier(14))
        self.assertEqual(rh.difficulty_hp_multiplier("ultimate"),
                         rh.regulation_hp_multiplier(20))

    def test_monotonic_non_decreasing(self):
        t = rh.multiplier_table()
        vals = [t[lv] for lv in range(1, 21)]
        for a, b in zip(vals, vals[1:]):
            self.assertGreater(b, a)

    def test_unknown_level_is_neutral_not_an_error(self):
        self.assertTrue(rh.is_supported_level(20))
        self.assertFalse(rh.is_supported_level(21))
        self.assertFalse(rh.is_supported_level("x"))
        self.assertEqual(rh.regulation_hp_multiplier(99), 1.0)
        self.assertEqual(rh.regulation_hp(1000, 99), 1000.0)
        self.assertEqual(rh.difficulty_hp_multiplier("nonexistent"), 1.0)


if __name__ == "__main__":
    unittest.main()
