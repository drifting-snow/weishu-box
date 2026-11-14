# -*- coding: utf-8 -*-
"""Stdlib unittest for tools/parse_combat_metrics.py (stage-A combat metrics).

Run: python -m unittest discover -s tests -v
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DATA = os.path.join(ROOT, "data/operator_combat_metrics.json")


class CombatMetricsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DATA, encoding="utf-8") as f:
            cls.doc = json.load(f)
        cls.by_name = {r["name"]: r for r in cls.doc["operators"]}

    def test_all_141_covered_no_missing(self):
        self.assertEqual(self.doc["_meta"]["operator_count"], 141)
        self.assertEqual(len(self.doc["operators"]), 141)
        self.assertEqual(self.doc["_meta"]["missing"], [])

    def test_ehp_and_base_dps_for_every_operator(self):
        # the panel-level metrics must always exist in both states
        for r in self.doc["operators"]:
            for st in ("initial", "elite"):
                m = r[st]
                self.assertGreaterEqual(m["effective_hp"]["physical"], m["effective_hp"]["raw_hp"])
                self.assertGreater(m["effective_hp"]["arts"], 0)
                self.assertGreater(m["base_dps"], 0)
                # physical EHP formula sanity: hp/(1-def/(def+100))
                ehp = m["effective_hp"]
                expect = ehp["raw_hp"] / (1 - ehp["def"] / (ehp["def"] + 100.0))
                self.assertAlmostEqual(ehp["physical"], round(expect, 1), places=1)

    def test_additive_vs_total_multiplier_semantics(self):
        # verified against in-game skill text at Rank7
        surtr = self.by_name["史尔特尔"]["elite"]["skill_metrics"]
        by_skill = {s["name"]: s for s in surtr}
        # 黄昏: blackboard atk=2.4 additive -> 3.4x
        dusk = by_skill["黄昏"]
        self.assertEqual(dusk["mult_source"], "additive")
        self.assertEqual(dusk["multiplier"], 3.4)
        self.assertIsNotNone(dusk["aoe_dps"])  # targets=3, self-damage only a note
        # 烈焰魔剑: atk_scale=2.4 total -> 2.4x
        blade = by_skill["烈焰魔剑"]
        self.assertEqual(blade["mult_source"], "total")
        self.assertEqual(blade["multiplier"], 2.4)
        # 蓝毒 二重射击: atk_scale total 1.55
        blue = {s["name"]: s for s in self.by_name["蓝毒"]["elite"]["skill_metrics"]}
        self.assertEqual(blue["二重射击·自动"]["multiplier"], 1.55)
        self.assertEqual(blue["二重射击·自动"]["mult_source"], "total")
        # 卡达 攻击力强化β Rank7: atk=0.5 additive -> 1.5x (M3 would be 1.8)
        kada = {s["name"]: s for s in self.by_name["卡达"]["elite"]["skill_metrics"]}
        beta = kada["攻击力强化·β型"]
        self.assertEqual(beta["mult_source"], "additive")
        self.assertEqual(beta["multiplier"], 1.5)

    def test_skill_dps_math(self):
        # single_dps = atk_with_trust * multiplier * hit_count / interval
        m = self.by_name["史尔特尔"]["elite"]
        atk, interval = m["atk_with_trust"], m["attack_interval"]
        dusk = next(s for s in m["skill_metrics"] if s["name"] == "黄昏")
        expect_single = round(atk * dusk["multiplier"] / interval, 2)
        self.assertEqual(dusk["single_dps"], expect_single)
        self.assertEqual(dusk["aoe_dps"], round(expect_single * dusk["targets"], 2))

    def test_medic_hps_and_instant_heal_review(self):
        night = {s["name"]: s for s in self.by_name["夜莺"]["elite"]["skill_metrics"]}
        # 治疗强化γ atk=0.7 additive -> 1.7x steady HPS present
        hps_skill = night["治疗强化·γ型"]
        self.assertIsNotNone(hps_skill["heal_hps"])
        self.assertGreater(hps_skill["heal_hps"], 0)
        # 法术护盾 is an instant shield -> hard review, no steady HPS
        shield = night["法术护盾"]
        self.assertIsNone(shield["heal_hps"])
        self.assertTrue(shield["needs_review"])

    def test_notes_vs_hard_review_separation(self):
        # a skill with a number must not be hard-flagged; notes carry caveats
        for r in self.doc["operators"]:
            for st in ("initial", "elite"):
                for s in r[st]["skill_metrics"]:
                    has_num = s["single_dps"] is not None or s["heal_hps"] is not None
                    if has_num:
                        self.assertFalse(s["needs_review"], r["name"] + " " + str(s["name"]))
        # hard review count is reported and bounded (functional/no-multiplier skills)
        self.assertGreater(self.doc["_meta"]["hard_review_entries"], 0)

    def test_no_mastery_rank7_only(self):
        # every parsed skill entry is Rank7 (mode has no mastery)
        self.assertIn("Rank7", self.doc["_meta"]["rank_note"])
        for r in self.doc["operators"]:
            self.assertEqual(r["elite"]["skill_rank"], 7)


if __name__ == "__main__":
    unittest.main()
