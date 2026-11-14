# -*- coding: utf-8 -*-
"""Stdlib unittest for tools/parse_items.py structured equipment effects.

Run: python -m unittest discover -s tests -v
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DATA = os.path.join(ROOT, "data", "items_structured.json")


class ParseItemsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DATA, encoding="utf-8") as f:
            cls.doc = json.load(f)
        cls.by_name = {x["name"]: x for x in cls.doc["items"]}

    def test_all_70_items_parsed(self):
        self.assertEqual(self.doc["_meta"]["total"], 70)
        self.assertEqual(len(self.doc["items"]), 70)

    def test_clean_numeric_stat(self):
        shield = self.by_name["坚守盾牌"]
        self.assertEqual(shield["stat_mods"]["def_pct"], 20)
        self.assertFalse(shield["needs_review"])
        solvent = self.by_name["源石溶剂"]
        self.assertEqual(solvent["stat_mods"]["atk_pct"], 40)
        self.assertIn({"kind": "hp_drain_flat", "value": 60}, solvent["drawbacks"])

    def test_negative_stats_and_no_aspd_double_count(self):
        # 可靠怀表: aspd -25% and sp cost -20%; the -25% must not also be read
        # as a flat -25 aspd (the lookahead bug fixed in parse_items).
        watch = self.by_name["可靠怀表"]
        self.assertEqual(watch["stat_mods"]["aspd_pct"], -25)
        self.assertEqual(watch["stat_mods"]["sp_cost_pct"], -20)
        self.assertNotIn("aspd_flat", watch["stat_mods"])
        blade = self.by_name["阿戈尔重刃"]
        self.assertEqual(blade["stat_mods"]["atk_pct"], 40)
        self.assertEqual(blade["stat_mods"]["aspd_flat"], -10)

    def test_consumable_and_stack_grant(self):
        coin = self.by_name["盟约之币"]
        self.assertTrue(coin["consumable"])
        badge = self.by_name["随身身份牌"]
        self.assertTrue(badge["consumable"])
        self.assertEqual(badge["stack_gain"]["amount"], 3)
        self.assertFalse(badge["stack_gain"]["requires_active"])

    def test_non_consumable_active_required_stack(self):
        letter = self.by_name["卫戍推荐信"]
        self.assertFalse(letter["consumable"])
        self.assertEqual(letter["stack_gain"]["amount"], 1)
        self.assertTrue(letter["stack_gain"]["requires_active"])
        tonic = self.by_name["多功能补剂"]
        self.assertTrue(tonic["stack_gain"]["transient"])
        self.assertTrue(tonic["needs_review"])

    def test_needs_review_flags(self):
        self.assertTrue(self.by_name["突袭手雷"]["needs_review"])
        self.assertTrue(self.by_name["动能单手弩"]["needs_review"])
        # clean items must not be flagged
        for n in ("坚守盾牌", "维式重锤", "萨尔贡浓茶", "加速维式重锤"):
            self.assertFalse(self.by_name[n]["needs_review"], n)

    def test_combo_target_extracted(self):
        self.assertEqual(self.by_name["动能单手弩"]["combo_of"], "动能轰击弩")
        self.assertEqual(self.by_name["天马之盔"]["combo_of"], "天马之耀")

    def test_meta_counts_self_consistent(self):
        m = self.doc["_meta"]
        self.assertEqual(
            m["clean_combat"] + m["needs_review"],
            len([x for x in self.doc["items"] if not x["consumable"]]))
        self.assertEqual(
            m["consumables"],
            len([x for x in self.doc["items"] if x["consumable"]]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
