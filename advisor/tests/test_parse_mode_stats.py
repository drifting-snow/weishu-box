# -*- coding: utf-8 -*-
"""Stdlib unittest for tools/parse_mode_stats.py (exact fixed-level panels).

Run: python -m unittest discover -s tests -v
"""
import json
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DATA = os.path.join(ROOT, "data/operator_mode_stats.json")
MODE = os.path.join(ROOT, "data/mode_levels.json")


class ModeStatsOutputTest(unittest.TestCase):
    """Validate the committed built artifact (works without the 15MB cache)."""

    @classmethod
    def setUpClass(cls):
        with open(DATA, encoding="utf-8") as f:
            cls.doc = json.load(f)
        with open(MODE, encoding="utf-8") as f:
            cls.mode = json.load(f)
        cls.by_name = {r["name"]: r for r in cls.doc["operators"]}

    def test_all_141_operators_covered(self):
        self.assertEqual(self.doc["_meta"]["operator_count"], 141)
        self.assertEqual(len(self.doc["operators"]), 141)
        self.assertEqual(self.doc["_meta"]["missing"], [])

    def test_fixed_levels_follow_mode_table(self):
        tiers = self.mode["tiers"]
        for r in self.doc["operators"]:
            spec = tiers[str(r["shop_tier"])]
            for state, key in ((r["initial"], "initial"), (r["elite"], "elite")):
                want = spec[key]
                self.assertEqual(state["phase"], want["phase"], r["name"])
                self.assertEqual(state["level"], want["level"], r["name"])
                self.assertEqual(state["skill_rank"], want["skill_rank"], r["name"])
                self.assertEqual(state["module"], want["module"], r["name"])

    def test_exact_surtr_t6_panel(self):
        # E2 Lv1 atk key frame 544 + trust 100 = 644 (replaces old anchor 772)
        s = self.by_name["史尔特尔"]["initial"]
        self.assertEqual((s["phase"], s["level"]), (2, 1))
        self.assertEqual(s["atk"], 544)
        self.assertEqual(s["trust"]["atk"], 100)
        self.assertEqual(s["atk_with_trust"], 644)
        # elite E2 Lv60 atk 629 + trust 100 = 729
        e = self.by_name["史尔特尔"]["elite"]
        self.assertEqual((e["phase"], e["level"]), (2, 60))
        self.assertEqual(e["atk_with_trust"], 729)
        self.assertAlmostEqual(e["base_dps"], round(729 / e["baseAttackTime"], 2))

    def test_lixia_t1_elite1_phase(self):
        # tier-1 initial is elite-1 Lv55 (not elite-2), proving phase mapping
        i = self.by_name["烈夏"]["initial"]
        self.assertEqual((i["phase"], i["level"]), (1, 55))
        self.assertEqual(i["atk_with_trust"], 562)

    def test_trust_is_additive_and_dps_consistent(self):
        for r in self.doc["operators"]:
            for state in (r["initial"], r["elite"]):
                self.assertEqual(
                    state["atk_with_trust"],
                    state["atk"] + state["trust"]["atk"])
                self.assertEqual(
                    state["maxHp_with_trust"],
                    state["maxHp"] + state["trust"]["maxHp"])
                self.assertAlmostEqual(
                    state["base_dps"],
                    round(state["atk_with_trust"] / state["baseAttackTime"], 2))
                # exact fixed level must never exceed the phase max frame atk
                self.assertGreaterEqual(state["frame_hi"], state["level"])


class InterpolationMathTest(unittest.TestCase):
    """Unit-test the interpolation against synthetic key frames directly."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "parse_mode_stats",
            os.path.join(ROOT, "tools", "parse_mode_stats.py"))
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def _rec(self, lo, hi):
        def frame(level, atk):
            return {"level": level, "data": {
                "atk": atk, "maxHp": 1000, "def": 100, "magicResistance": 10,
                "cost": 20, "blockCnt": 1, "baseAttackTime": 1.0,
                "attackSpeed": 100.0, "respawnTime": 70, "hpRecoveryPerSec": 0.0}}
        return {"phases": [
            {"attributesKeyFrames": [frame(1, lo), frame(90, hi)]}],
            "favorKeyFrames": [
                {"level": 0, "data": {"atk": 0, "maxHp": 0, "def": 0}},
                {"level": 50, "data": {"atk": 50, "maxHp": 0, "def": 0}}]}

    def test_linear_midpoint_and_endpoints(self):
        rec = self._rec(100, 280)  # span 89 levels, +180 atk
        # endpoints
        lv1 = self.mod.interpolate(rec, 0, 1)
        lv90 = self.mod.interpolate(rec, 0, 90)
        self.assertEqual(lv1["atk"], 100)
        self.assertEqual(lv90["atk"], 280)
        # midpoint Lv45: 100 + 180 * 44/89 = 188.76 -> 189
        lv45 = self.mod.interpolate(rec, 0, 45)
        self.assertEqual(lv45["atk"], 189)

    def test_trust_bonus_uses_last_frame(self):
        rec = self._rec(100, 280)
        self.assertEqual(self.mod.trust_bonus(rec)["atk"], 50)
        panel = self.mod.fixed_panel(rec, {"phase": 0, "level": 1,
                                           "skill_rank": 4, "module": 0})
        self.assertEqual(panel["atk_with_trust"], 150)


if __name__ == "__main__":
    unittest.main()
