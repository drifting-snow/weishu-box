# -*- coding: utf-8 -*-
"""Tests for derived operator burst-skill data (commit E).

Reads the committed data/operator_skills.json so a fresh clone without the
git-ignored skill_table can still run them.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "operator_skills.json")


class OperatorSkillDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DATA, encoding="utf-8") as fh:
            cls.doc = json.load(fh)
        cls.ops = cls.doc["operators"]

    def test_covers_all_metrics_operators(self):
        self.assertEqual(len(self.ops), self.doc["_meta"]["operator_count"])
        self.assertGreaterEqual(len(self.ops), 141)

    def test_burst_skill_well_formed(self):
        for name, o in self.ops.items():
            s = o["burst_skill"]
            if s is None:
                self.assertEqual(o["eligible_skill_count"], 0, name)
                continue
            # burst skills are exactly the additive ATK-up skills safe to multiply
            self.assertEqual(s["sp_type"], "INCREASE_WITH_TIME", name)
            self.assertGreater(s["charge_time"], 0, name)
            self.assertGreater(s["duration"], 0, name)
            self.assertIsInstance(s["multiplier"], (int, float), name)
            self.assertGreater(s["multiplier"], 1.0, name)
            self.assertEqual(s["mult_source"], "additive", name)
            self.assertGreaterEqual(s["initial_sp"], 0.0, name)

    def test_low_mult_total_skills_are_parked_not_burst(self):
        # 钙质化 (total, 0.2) is an arts/control skill, must never drive ATK*0.2
        saria = self.ops["塞雷娅"]
        self.assertIsNone(saria["burst_skill"])
        self.assertIn("skchr_demkni_3", saria["special_skill_ids"])
        # an additive ATK-up skill is still chosen normally
        self.assertEqual(self.ops["幽灵鲨"]["burst_skill"]["multiplier"], 2.0)

    def test_known_operators(self):
        cammou = self.ops["卡达"]["burst_skill"]
        self.assertEqual(cammou["name"], "同步索敌攻击")
        self.assertEqual(cammou["multiplier"], 1.58)
        self.assertEqual(cammou["charge_time"], 45.0)
        # instant/untimed skill operator carries no burst but records the id
        meteo = self.ops["陨星"]
        self.assertIsNone(meteo["burst_skill"])
        self.assertTrue(meteo["untimed_skill_ids"])

    def test_meta_records_model_limits(self):
        notes = " ".join(self.doc["_meta"]["needs_review"])
        self.assertIn("INCREASE_WITH_TIME", notes)
        # strict contract: only additive ATK-up skills (mult>1) become burst_skill
        self.assertGreaterEqual(self.doc["_meta"]["operators_with_burst_skill"], 75)
        self.assertLess(self.doc["_meta"]["operators_with_burst_skill"],
                        self.doc["_meta"]["operator_count"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
