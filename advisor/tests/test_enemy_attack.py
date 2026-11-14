# -*- coding: utf-8 -*-
"""Tests for derived enemy attack data (commit C).

Reads the committed data/enemy_attack.json so a fresh clone without the
git-ignored unpacked table can still run them.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "enemy_attack.json")
WAVES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "act3_waves.json")


class EnemyAttackDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DATA, encoding="utf-8") as fh:
            cls.doc = json.load(fh)
        cls.enemies = cls.doc["enemies"]
        with open(WAVES, encoding="utf-8") as fh:
            cls.waves = json.load(fh)

    def test_covers_every_act3_spawn_id(self):
        spawn_ids = {sp["enemy_id"] for lvl in self.waves["level_stems"].values()
                     for sp in lvl.get("spawns", [])}
        self.assertEqual(set(self.enemies), spawn_ids)  # exact 1:1 coverage
        self.assertEqual(self.doc["_meta"]["enemy_count"], len(spawn_ids))

    def test_fields_well_formed(self):
        for eid, e in self.enemies.items():
            self.assertIsInstance(e["atk"], (int, float), eid)
            self.assertGreater(e["base_attack_time"], 0, eid)
            self.assertIn(e["apply_way"], ("MELEE", "RANGED", "ALL", "NONE"), eid)
            self.assertIn(e["motion"], ("WALK", "FLY"), eid)
            self.assertIn(e["damage_family_assumed"], ("phys",), eid)

    def test_deals_damage_matches_atk_and_apply_way(self):
        for eid, e in self.enemies.items():
            expected = e["atk"] > 0 and e["apply_way"] != "NONE"
            self.assertEqual(e["deals_damage"], expected, eid)

    def test_known_enemies(self):
        slime = self.enemies["enemy_1007_slime"]
        self.assertTrue(slime["deals_damage"])
        self.assertEqual(slime["apply_way"], "MELEE")
        self.assertEqual(slime["atk"], 130.0)
        # non-attacking flyer and the high-atk but passive beast
        self.assertFalse(self.enemies["enemy_1005_yokai"]["deals_damage"])
        self.assertFalse(self.enemies["enemy_2124_dyjsfg"]["deals_damage"])

    def test_meta_records_the_damage_family_assumption(self):
        notes = " ".join(self.doc["_meta"]["needs_review"])
        self.assertIn("physical", notes.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
