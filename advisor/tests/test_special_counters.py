# -*- coding: utf-8 -*-
"""Tests for the per-name special-counter extension (advisor/special_counters).

Pure logic is tested with an in-memory doc so it does not depend on the built
JSON; a final test validates the committed data file's shape.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from advisor import special_counters as sc  # noqa: E402

FAKE_DOC = {
    "special_cases": [
        {"name": "冰爆源石虫·α", "counter_tag": "silence",
         "primary_mechanic": "on_death_cold_explosion",
         "ability_label": "死亡爆炸+寒冷", "counter_label": "沉默阻止爆炸",
         "generic_covered": False},
        {"name": "“喷爆罐”", "counter_tag": "silence",
         "primary_mechanic": "on_death_cold_explosion",
         "ability_label": "死亡爆炸+寒冷", "counter_label": "沉默阻止爆炸",
         "generic_covered": False},
        {"name": "变异岩蛛", "counter_tag": "silence",
         "primary_mechanic": "on_death_split",
         "ability_label": "死亡分裂", "counter_label": "沉默阻止分裂",
         "generic_covered": False},
        # generically covered -> must never trigger
        {"name": "深池侦察兵", "counter_tag": "silence",
         "primary_mechanic": "refraction_essence",
         "ability_label": "折射",
         "counter_label": "通用分类已覆盖", "generic_covered": True},
    ]
}


class SpecialCounterDemandTest(unittest.TestCase):
    def test_empty_picture_no_demand(self):
        self.assertEqual(sc.special_counter_demands([], FAKE_DOC), [])
        self.assertEqual(sc.special_counter_demands(None, FAKE_DOC), [])

    def test_unknown_names_no_demand(self):
        self.assertEqual(
            sc.special_counter_demands(["路人甲", "源石虫"], FAKE_DOC), [])

    def test_named_enemy_raises_silence_demand(self):
        out = sc.special_counter_demands(["冰爆源石虫·α"], FAKE_DOC)
        self.assertEqual(len(out), 1)
        d = out[0]
        self.assertEqual(d["counter_tag"], "silence")
        self.assertEqual(d["enemies"], ["冰爆源石虫·α"])
        self.assertIn("冰爆源石虫·α", d["reasons"][0])

    def test_multiple_enemies_dedup_into_one_demand(self):
        out = sc.special_counter_demands(
            ["冰爆源石虫·α", "“喷爆罐”", "冰爆源石虫·α"], FAKE_DOC)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["enemies"],
                         ["冰爆源石虫·α", "“喷爆罐”"])
        self.assertEqual(len(out[0]["reasons"]), 2)

    def test_generic_covered_entry_never_triggers(self):
        self.assertEqual(
            sc.special_counter_demands(["深池侦察兵"], FAKE_DOC), [])

    def test_split_family_also_demands_silence(self):
        out = sc.special_counter_demands(["变异岩蛛"], FAKE_DOC)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["mechanic"], "on_death_split")

    def test_has_special_counter_predicate(self):
        self.assertTrue(
            sc.has_special_counter(["冰爆源石虫·α"], "silence", FAKE_DOC))
        self.assertFalse(
            sc.has_special_counter(["冰爆源石虫·α"], "anti_air", FAKE_DOC))
        self.assertFalse(
            sc.has_special_counter(["假想敌：镜波"], "silence", FAKE_DOC))


class CommittedLibraryTest(unittest.TestCase):
    def test_built_library_full_silence_curation(self):
        path = os.path.join(os.path.dirname(__file__), "..", "data",
                            "enemy_special_cases.json")
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        cases = doc["special_cases"]
        # every official SILENCE enemy is curated, split into active vs covered
        self.assertEqual(doc["_meta"]["case_count"], 61)
        active = [c for c in cases if not c["generic_covered"]]
        covered = [c for c in cases if c["generic_covered"]]
        self.assertEqual(len(active), 47)
        self.assertEqual(len(covered), 14)
        self.assertEqual(doc["_meta"]["needs_review"], [])
        for c in cases:
            self.assertEqual(c["counter_tag"], "silence")
            self.assertEqual(
                c["evidence"]["official_textformat"], "SILENCE")
            self.assertTrue(c["evidence"]["official_ability_text"])
            self.assertTrue(c["enemy_ids"])
        # the generic_covered tier is exactly the refraction family
        self.assertTrue(
            all(c["primary_mechanic"] == "refraction_essence" for c in covered))
        # active families resolve through the reader; covered ones do not
        self.assertTrue(
            sc.has_special_counter(["冰爆源石虫·α"], "silence", doc))
        self.assertTrue(
            sc.has_special_counter(["变异岩蛛"], "silence", doc))
        self.assertFalse(
            sc.has_special_counter(["深池侦察兵"], "silence", doc))


if __name__ == "__main__":
    unittest.main(verbosity=2)
