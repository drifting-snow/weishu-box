# -*- coding: utf-8 -*-
"""Stdlib unittest for tools/parse_damage_profiles.py (stage-B integration).

Run: python -m unittest discover -s tests -v
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DATA = os.path.join(ROOT, "data/operator_damage_profiles.json")
OVR = os.path.join(ROOT, "data/damage_type_overrides.json")
VALID_TYPES = {"physical", "arts", "true", "heal"}


class DamageProfileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DATA, encoding="utf-8") as f:
            cls.doc = json.load(f)
        with open(OVR, encoding="utf-8") as f:
            cls.ovr = json.load(f)
        cls.by_name = {r["name"]: r for r in cls.doc["operators"]}

    def test_all_141_covered_no_missing(self):
        self.assertEqual(self.doc["_meta"]["operator_count"], 141)
        self.assertEqual(len(self.doc["operators"]), 141)
        self.assertEqual(self.doc["_meta"]["missing"], [])

    def test_every_skill_has_resolved_type(self):
        # no unresolved None after the override table adjudicates mixed skills
        for r in self.doc["operators"]:
            for st in ("initial", "elite"):
                self.assertIn(r[st]["baseline_damage_type"], VALID_TYPES)
                for s in r[st]["skill_profiles"]:
                    self.assertIn(s["damage_type"], VALID_TYPES,
                                  "%s %s" % (r["name"], s["name"]))
                    self.assertEqual(s["type_review"], [])

    def test_standard_tiers_recorded(self):
        meta = self.doc["_meta"]
        self.assertEqual(meta["def_tiers"], [0, 100, 200, 300, 400, 500, 600, 800, 1000])
        self.assertEqual(meta["res_tiers"], [0, 10, 20, 30, 40, 50, 60, 70, 90])

    def test_override_adjudications(self):
        expected = {o["skill_id"]: o["damage_type"] for o in self.ovr["overrides"]}
        found = {}
        for r in self.doc["operators"]:
            for st in ("initial", "elite"):
                for s in r[st]["skill_profiles"]:
                    if s["skill_id"] in expected:
                        found[s["skill_id"]] = (s["damage_type"], s["type_source"])
        for sid, dtype in expected.items():
            self.assertIn(sid, found)
            self.assertEqual(found[sid][0], dtype)
            self.assertEqual(found[sid][1], "override")
        # concrete spot checks
        weedy = next(s for s in self.by_name["温蒂"]["elite"]["skill_profiles"]
                     if s["skill_id"] == "skchr_weedy_3")
        self.assertEqual(weedy["damage_type"], "arts")

    def test_heal_and_shield_have_no_matrix(self):
        # healing skills and the absorb-shield never fabricate a damage matrix
        night = {s["name"]: s for s in self.by_name["夜莺"]["elite"]["skill_profiles"]}
        self.assertEqual(night["治疗强化·γ型"]["damage_type"], "heal")
        self.assertNotIn("damage_matrix", night["治疗强化·γ型"])
        self.assertNotIn("damage_matrix", night["法术护盾"])  # shield, no offense

    def test_physical_matrix_has_break_lines_and_monotonic(self):
        blue = next(s for s in self.by_name["蓝毒"]["elite"]["skill_profiles"]
                    if "damage_matrix" in s)
        m = blue["damage_matrix"]
        self.assertEqual(m["axis"], "defense")
        self.assertIn("break_lines", m)
        vals = [m["per_action_damage"][str(d)] for d in self.doc["_meta"]["def_tiers"]]
        # higher DEF never increases damage; floor keeps it positive
        for a, b in zip(vals, vals[1:]):
            self.assertGreaterEqual(a, b)
        self.assertGreater(vals[-1], 0)

    def test_arts_matrix_half_damage_and_cap(self):
        surtr = next(s for s in self.by_name["史尔特尔"]["elite"]["skill_profiles"]
                     if s["name"] == "黄昏")
        m = surtr["damage_matrix"]
        self.assertEqual(m["axis"], "resistance")
        self.assertEqual(m["half_damage_resistance"], 50)
        d0 = m["per_action_damage"]["0"]
        d50 = m["per_action_damage"]["50"]
        self.assertAlmostEqual(d50, d0 * 0.5, places=2)
        # RES 90 -> 10% damage
        self.assertAlmostEqual(m["per_action_damage"]["90"], d0 * 0.1, places=2)

    def test_surtr_is_arts_family(self):
        e = self.by_name["史尔特尔"]["elite"]
        self.assertEqual(e["baseline_damage_type"], "arts")
        for s in e["skill_profiles"]:
            self.assertEqual(s["damage_type"], "arts")


if __name__ == "__main__":
    unittest.main()
