# -*- coding: utf-8 -*-
"""Tests for derived enemy skill-burst data (commit G, arts trunk in commit I).

Reads the committed data/enemy_skills.json so a fresh clone without the
git-ignored enemy_database can still run them.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "enemy_skills.json")

# Blackboard keys that still hard-block single-hit driving. ep_damage_ratio is
# intentionally absent: it is the elemental side-share, parked separately while
# the phys/arts main hit stays drivable.
BLOCKING = ("stun", "dot_damage", "damage_resistance",
            "enemy_key", "branch_id", "chain.atk_scale")


class EnemySkillDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DATA, encoding="utf-8") as fh:
            cls.doc = json.load(fh)
        cls.enemies = cls.doc["enemies"]

    def test_jushou_qualified_as_periodic_physical_aoe(self):
        rec = self.enemies.get("enemy_2124_dyjsfg")
        self.assertIsNotNone(rec, "矩兽 must stay a drivable AoE enemy")
        self.assertEqual(rec["enemy_name"], "矩兽")
        self.assertEqual(len(rec["bursts"]), 1)
        b = rec["bursts"][0]
        self.assertEqual(b["kind"], "periodic_aoe")
        self.assertEqual(b["damage_family"], "phys")
        self.assertNotIn("elemental_ratio_parked", b)
        self.assertEqual(b["cooldown"], 2.0)
        self.assertEqual(b["atk_scale"], 2.0)
        self.assertEqual(b["range_radius"], 1.6)

    def test_fin_discharge_is_arts_with_elemental_parked(self):
        rec = self.enemies.get("enemy_9037_aceel")
        self.assertIsNotNone(rec, "假想敌：鳍 Discharge arts main hit must be drivable")
        b = rec["bursts"][0]
        self.assertEqual(b["damage_family"], "arts")
        self.assertEqual(b["atk_scale"], 1.25)
        self.assertEqual(b["range_radius"], 1.5)
        # the nerve/elemental share is preserved on the record but not driven
        self.assertEqual(b["elemental_ratio_parked"], 0.4)

    def test_every_drivable_burst_is_well_formed_single_family(self):
        for eid, rec in self.enemies.items():
            for b in rec["bursts"]:
                self.assertEqual(b["kind"], "periodic_aoe", eid)
                self.assertIn(b["damage_family"], ("phys", "arts"), eid)
                self.assertGreater(b["cooldown"], 0.0, eid)       # periodic
                self.assertGreater(b["atk_scale"], 0.0, eid)
                self.assertGreater(b["range_radius"], 0.0, eid)   # AoE reach
                self.assertGreater(rec["base_atk"], 0.0, eid)

    def test_mixed_mechanic_skills_are_parked_not_driven(self):
        parked = self.doc["_meta"]["parked"]
        self.assertGreater(len(parked), 0)
        parked_ids = {p["enemy_id"] for p in parked}
        # 鳍 still appears in parked, but only for the elemental side-share
        fin_rows = [p for p in parked if p["enemy_id"] == "enemy_9037_aceel"]
        self.assertTrue(any("elemental" in p["reason"] for p in fin_rows))
        # every parked row explains why
        for p in parked:
            self.assertTrue(p["reason"], p)
        # 矩兽's drivable CombatAoe is never parked as a mixed mechanic
        self.assertNotIn("enemy_2124_dyjsfg",
                         {p["enemy_id"] for p in parked if "mixed" in p["reason"]})

    def test_meta_records_scope_limits(self):
        notes = " ".join(self.doc["_meta"]["needs_review"])
        self.assertIn("phys", notes)
        self.assertIn("arts", notes)
        self.assertEqual(self.doc["_meta"]["enemy_count_with_burst"],
                         len(self.enemies))
        self.assertGreaterEqual(self.doc["_meta"]["parked_skill_count"], 30)
        # at least one physical and one arts burst are now covered
        families = {b["damage_family"] for rec in self.enemies.values()
                    for b in rec["bursts"]}
        self.assertEqual(families, {"phys", "arts"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
