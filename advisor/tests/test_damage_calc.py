# -*- coding: utf-8 -*-
"""Stdlib unittest for advisor/damage_calc.py (stage-B settlement).

Run: python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from advisor import damage_calc as dc  # noqa: E402
from advisor.damage_type import PHYSICAL, ARTS, TRUE, HEAL  # noqa: E402


class PhysicalTest(unittest.TestCase):
    def test_basic_mitigation(self):
        # ATK 1000 vs DEF 400 -> 600 raw
        self.assertEqual(dc.physical_hit(1000, 400), 600)

    def test_five_percent_floor(self):
        # heavy armor: raw would be negative, floor = 5% of ATK
        self.assertEqual(dc.physical_hit(1000, 1200), 50)
        self.assertEqual(dc.physical_hit(1000, 950), 50)   # exactly the bind point

    def test_floor_never_negative(self):
        self.assertGreater(dc.physical_hit(100, 10000), 0)

    def test_break_lines(self):
        lines = dc.physical_break_lines(1000)
        self.assertEqual(lines["half_damage_def"], 500)
        self.assertEqual(lines["min_damage_def"], 950)
        self.assertEqual(lines["min_damage_value"], 50)


class ArtsTest(unittest.TestCase):
    def test_basic_resistance(self):
        self.assertEqual(dc.arts_hit(1000, 0), 1000)
        self.assertEqual(dc.arts_hit(1000, 50), 500)   # half-damage line
        self.assertAlmostEqual(dc.arts_hit(1000, 20), 800)

    def test_resistance_cap(self):
        # RES capped at 95 -> never fully nullified
        self.assertAlmostEqual(dc.arts_hit(1000, 95), 50)
        self.assertAlmostEqual(dc.arts_hit(1000, 120), 50)

    def test_negative_resistance_clamped(self):
        self.assertEqual(dc.arts_hit(1000, -30), 1000)

    def test_half_resistance_constant(self):
        self.assertEqual(dc.arts_half_resistance(), 50)


class TrueDamageTest(unittest.TestCase):
    def test_ignores_def_res(self):
        self.assertEqual(dc.true_hit(1000), 1000.0)

    def test_dispatch(self):
        self.assertEqual(dc.hit_damage(1000, TRUE, defense=9999, resistance=90), 1000.0)
        self.assertIsNone(dc.hit_damage(1000, HEAL))
        self.assertIsNone(dc.hit_damage(1000, None))


class DispatchTest(unittest.TestCase):
    def test_physical_and_arts_dispatch(self):
        self.assertEqual(dc.hit_damage(1000, PHYSICAL, defense=400), 600)
        self.assertEqual(dc.hit_damage(1000, ARTS, resistance=50), 500)


class DamageMatrixTest(unittest.TestCase):
    def test_physical_matrix_axes_and_floor(self):
        m = dc.damage_matrix(1000, PHYSICAL)
        self.assertEqual(m["axis"], "defense")
        self.assertEqual(m["tiers"], list(dc.DEF_TIERS))
        self.assertEqual(m["per_action_damage"]["0"], 1000)
        self.assertEqual(m["per_action_damage"]["400"], 600)
        # DEF 1000 -> floored at 50
        self.assertEqual(m["per_action_damage"]["1000"], 50)
        self.assertIn("break_lines", m)

    def test_arts_matrix(self):
        m = dc.damage_matrix(1000, ARTS)
        self.assertEqual(m["axis"], "resistance")
        self.assertEqual(m["per_action_damage"]["0"], 1000)
        self.assertEqual(m["per_action_damage"]["50"], 500)
        self.assertEqual(m["per_action_damage"]["90"], 100)

    def test_hit_count_and_targets_multiply(self):
        base = dc.damage_matrix(1000, PHYSICAL)["per_action_damage"]["0"]
        multi = dc.damage_matrix(1000, PHYSICAL, hit_count=2, targets=3)
        self.assertEqual(multi["per_action_damage"]["0"], base * 6)

    def test_true_matrix_single_value(self):
        m = dc.damage_matrix(1000, TRUE)
        self.assertEqual(m["axis"], "none")
        self.assertEqual(m["per_action_damage"]["0"], 1000)


if __name__ == "__main__":
    unittest.main()
