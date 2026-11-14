# -*- coding: utf-8 -*-
"""Tests for the structured bond parser (milestone preservation regression).

Guards the bug where generic HTML cleaning deleted in-game condition markers
like <在场6名不同【炎】干员>, wiping every bond's milestone effects.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.parse_bonds import parse_bonds, classify_condition


class BondParserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = parse_bonds()
        cls.by_name = {}
        for grp in ("core", "attached"):
            for b in cls.data[grp]:
                cls.by_name[b["name"]] = b

    def test_counts(self):
        self.assertEqual(len(self.data["core"]), 10)
        self.assertEqual(len(self.data["attached"]), 16)

    def test_yan_base_and_6_milestone_preserved(self):
        yan = self.by_name["炎"]
        self.assertEqual(yan["activation_need"], 3)
        self.assertIn("攻击力提升", yan["base_effect"])
        distinct = [m for m in yan["milestones"]
                    if m["trigger_type"] == "distinct_operator"]
        self.assertEqual([m["threshold"] for m in distinct], [6])
        self.assertIn("随机元素损伤", distinct[0]["effect"])

    def test_every_core_bond_has_6_distinct_milestone(self):
        for b in self.data["core"]:
            six = [m for m in b["milestones"]
                   if m["trigger_type"] == "distinct_operator" and m["threshold"] == 6]
            self.assertTrue(six, "core bond %s missing 6-operator milestone" % b["name"])

    def test_stack_milestones(self):
        weijian = self.by_name["远见"]
        each = [m for m in weijian["milestones"] if m["trigger_type"] == "stack_each"]
        first = [m for m in weijian["milestones"] if m["trigger_type"] == "stack_first"]
        self.assertEqual([m["threshold"] for m in each], [10])
        self.assertEqual(sorted(m["threshold"] for m in first), [80, 150])

    def test_elite_milestones_jueji(self):
        jueji = self.by_name["绝技"]
        elite = [m for m in jueji["milestones"] if m["trigger_type"] == "elite_operator"]
        self.assertEqual(sorted(m["threshold"] for m in elite), [2, 5])

    def test_duxing_single_operator(self):
        duxing = self.by_name["独行"]
        self.assertEqual(duxing["activation_need"], 1)
        self.assertEqual(duxing["milestones"][0]["trigger_type"], "distinct_operator")
        self.assertEqual(duxing["milestones"][0]["threshold"], 1)

    def test_last_card_does_not_swallow_later_avatars(self):
        # regression: 奥术 is the last bond card and its block runs to EOF.
        # Its operator list must come only from acb-ops (14), not the 494
        # avatars from every later operator-detail section.
        aoshu = self.by_name["奥术"]
        self.assertEqual(len(aoshu["operators"]), 14)
        self.assertEqual(len(set(aoshu["operators"])), 14)
        # 莱塔尼亚 container also parses correctly (was inside=0)
        self.assertEqual(len(self.by_name["莱塔尼亚"]["operators"]), 10)
        # 绝技 has no fixed operators (activated via elite state)
        self.assertEqual(self.by_name["绝技"]["operators"], [])

    def test_all_bond_operator_counts_match_no_duplicates(self):
        for grp in ("core", "attached"):
            for b in self.data[grp]:
                self.assertEqual(len(b["operators"]), len(set(b["operators"])),
                                 "duplicate operators in %s" % b["name"])

    def test_no_html_tags_classified_as_milestone(self):
        for grp in ("core", "attached"):
            for b in self.data[grp]:
                for m in b["milestones"]:
                    self.assertNotIn("<", m["condition"])
                    self.assertNotIn("span", m["condition"])

    def test_classify_condition_unit(self):
        self.assertEqual(classify_condition("在场6名不同【乌萨斯】干员")["trigger_type"],
                         "distinct_operator")
        self.assertEqual(classify_condition("在场5名精锐状态的干员")["trigger_type"],
                         "elite_operator")
        self.assertEqual(classify_condition("首次达到100层")["trigger_type"], "stack_first")
        self.assertEqual(classify_condition("每叠加25层")["trigger_type"], "stack_each")
        self.assertEqual(classify_condition("达到50层")["trigger_type"], "stack_reach")


if __name__ == "__main__":
    unittest.main(verbosity=2)
