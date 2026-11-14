# -*- coding: utf-8 -*-
"""Stdlib tests for the all-bond stack feasibility factor.
Run: python -m unittest tests.test_stack_feasibility -v"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, ROOT)

from advisor import stack_feasibility as sf


class FeasibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = sf.feasibility_report()
        with open(os.path.join(DATA, "bonds.json"), encoding="utf-8") as f:
            bonds = json.load(f)
        cls.all_bonds = {b["name"] for b in bonds["core"] + bonds["attached"]}

    def test_every_bond_with_stackers_gets_a_factor(self):
        # every bond that has a named stack source is covered (23 bonds)
        self.assertGreaterEqual(len(self.report), 20)
        for bond, r in self.report.items():
            self.assertIn(bond, self.all_bonds)
            self.assertTrue(0.0 < r["factor"] <= 1.0, bond)
            self.assertIn(r["grade"], ("高", "中", "低"))

    def test_sub_scores_in_range(self):
        for bond, r in self.report.items():
            for key, v in r["sub_scores"].items():
                self.assertTrue(0.0 <= v <= 1.0, (bond, key, v))

    def test_timing_score_curve(self):
        self.assertEqual(sf._timing_score(1), 1.0)
        self.assertAlmostEqual(sf._timing_score(6), 1.0 / 6.0, places=2)
        self.assertEqual(sf._timing_score(None), 0.0)

    def test_passive_is_easiest_means(self):
        # a held-operator passive must outrank every combat trigger
        self.assertEqual(sf.MEANS_EASE["passive_or_other"],
                         max(sf.MEANS_EASE.values()))
        self.assertGreater(sf.MEANS_EASE["op_acquire"],
                           sf.MEANS_EASE["on_kill"])
        self.assertGreater(sf.MEANS_EASE["on_kill"],
                           sf.MEANS_EASE["on_affliction"])

    def test_dynamic_only_rate_is_neutral(self):
        # no fixed amount -> rate defaults to neutral 0.5, never 0 or 1
        self.assertEqual(sf._rate_score([{"amount": None, "shape": "dynamic_var"}]), 0.5)

    def test_high_round_cap_outranks_low_cap(self):
        # throughput is cap-dominant: a 24/round combat engine beats a 4/round one
        fast = [{"amount": 2, "shape": "named_plus_n",
                 "cap_scope": "per_round", "cap": 24}]
        slow = [{"amount": 2, "shape": "named_plus_n",
                 "cap_scope": "per_round", "cap": 4}]
        self.assertGreater(sf._rate_score(fast), sf._rate_score(slow))
        self.assertGreaterEqual(sf._rate_score(fast), 0.75)

    def test_uncapped_passive_falls_back_to_amount(self):
        # no per-round cap -> fixed amount acts as the throughput proxy
        r = sf._rate_score([{"amount": 6, "shape": "named_plus_n",
                             "cap_scope": None, "cap": None}])
        self.assertGreater(r, 0.5)

    def test_rate_is_weighted_above_means(self):
        # the rework makes rate the dominant continuous sub-score
        self.assertGreater(sf.W_RATE, sf.W_MEANS)
        self.assertEqual(
            round(sf.W_TIMING + sf.W_BREADTH + sf.W_MEANS + sf.W_RATE, 6), 1.0)

    def test_late_named_stackers_have_low_timing(self):
        # 远见/奇迹 named stackers only appear at tier 4 -> timing <= 0.5
        for bond in ("远见", "奇迹"):
            self.assertLessEqual(self.report[bond]["sub_scores"]["timing"], 0.5)

    def test_cap_boosters_never_count_as_stacker(self):
        # Mon3tr/凛御银灰 cap boosters must not inflate any bond's stacker list
        for bond, r in self.report.items():
            self.assertNotIn("Mon3tr", r["stackers"])

    def test_report_is_deterministic(self):
        again = sf.feasibility_report()
        self.assertEqual(
            {b: r["factor"] for b, r in again.items()},
            {b: r["factor"] for b, r in self.report.items()})

    def test_written_file_matches_computed(self):
        path, _ = sf.write_report()
        with open(path, encoding="utf-8") as f:
            disk = json.load(f)["bonds"]
        for bond, r in self.report.items():
            self.assertEqual(disk[bond]["factor"], r["factor"], bond)

    def test_unknown_bond_factor_is_neutral(self):
        self.assertEqual(sf.feasibility_factor("不存在的羁绊", self.report), 0.5)

    def test_report_splits_continuous_and_startup(self):
        for bond, r in self.report.items():
            self.assertIn("continuous_factor", r)
            self.assertIn("startup_score", r)
            self.assertIn("continuous_stacker_count", r)
            self.assertIn("injector_count", r)
            self.assertTrue(0.0 <= r["continuous_factor"] <= 1.0)
            self.assertTrue(0.0 <= r["startup_score"] <= 1.0)

    def test_bond_with_only_injections_cannot_grow_large_stack(self):
        # 灵巧 has injection operators but zero continuous stackers: its
        # continuous growth must collapse even though startup is healthy.
        lingqiao = self.report["灵巧"]
        self.assertEqual(lingqiao["continuous_stacker_count"], 0)
        self.assertGreater(lingqiao["injector_count"], 0)
        self.assertGreater(lingqiao["startup_score"], lingqiao["continuous_factor"])
        self.assertLess(lingqiao["factor"], 0.55)  # grade 低

    def test_touren_startup_stronger_than_its_continuous_engine(self):
        # 锡人 gives an early injection; only 可露希尔 sustains growth, so
        # startup must outscore continuous for 投资人.
        tr = self.report["投资人"]
        self.assertGreater(tr["startup_score"], tr["continuous_factor"])
        self.assertEqual(tr["injector_count"], 1)  # 锡人

    def test_injection_does_not_inflate_continuous_stacker_count(self):
        # 锡人 must not be counted among 投资人 continuous stackers
        self.assertNotIn("锡人", self.report["投资人"]["stackers"])
        self.assertIn("锡人", self.report["投资人"]["injectors"])

    def test_factor_is_weighted_blend(self):
        # factor = 0.85*continuous + 0.15*startup
        for bond, r in self.report.items():
            expected = round(0.85 * r["continuous_factor"] + 0.15 * r["startup_score"], 3)
            self.assertAlmostEqual(r["factor"], expected, places=2, msg=bond)


if __name__ == "__main__":
    unittest.main(verbosity=2)
