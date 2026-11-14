# -*- coding: utf-8 -*-
"""Stdlib unittest for advisor/damage_type.py (stage-B classifier).

Run: python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from advisor import damage_type as dt  # noqa: E402


class ClassifyTextTest(unittest.TestCase):
    def test_explicit_primary_keywords(self):
        self.assertEqual(dt.classify_text("攻击造成法术伤害")[0], dt.ARTS)
        self.assertEqual(dt.classify_text("下次攻击造成物理伤害")[0], dt.PHYSICAL)
        self.assertEqual(dt.classify_text("造成真实伤害")[0], dt.TRUE)

    def test_no_keyword_returns_none(self):
        primary, elem = dt.classify_text("攻击力+80%，攻击速度+10")
        self.assertIsNone(primary)
        self.assertFalse(elem)

    def test_mixed_primary_returns_none_for_review(self):
        primary, _ = dt.classify_text("攻击交替造成法术伤害与物理伤害")
        self.assertIsNone(primary)

    def test_elemental_is_secondary_flag(self):
        primary, elem = dt.classify_text("攻击造成法术伤害并附加神经损伤")
        self.assertEqual(primary, dt.ARTS)
        self.assertTrue(elem)
        # elemental alone keeps primary unresolved
        primary2, elem2 = dt.classify_text("对目标施加侵蚀损伤")
        self.assertIsNone(primary2)
        self.assertTrue(elem2)

    def test_all_elemental_keywords_detected(self):
        for kw in dt.ELEMENTAL_KEYWORDS:
            _, elem = dt.classify_text("攻击附带%s" % kw)
            self.assertTrue(elem, kw)


class BranchDefaultTest(unittest.TestCase):
    def test_profession_baseline(self):
        self.assertEqual(dt.branch_default("SNIPER", "fastshot"), dt.PHYSICAL)
        self.assertEqual(dt.branch_default("CASTER", "corecaster"), dt.ARTS)
        self.assertEqual(dt.branch_default("MEDIC", "physician"), dt.HEAL)

    def test_audited_branch_exceptions(self):
        # bombarder sniper deals arts; arts guard deals arts; bard is true dmg
        self.assertEqual(dt.branch_default("SNIPER", "bombarder"), dt.ARTS)
        self.assertEqual(dt.branch_default("WARRIOR", "artsfghter"), dt.ARTS)
        self.assertEqual(dt.branch_default("TANK", "artsprotector"), dt.ARTS)
        self.assertEqual(dt.branch_default("SUPPORT", "bard"), dt.TRUE)
        self.assertEqual(dt.branch_default("SPECIAL", "alchemist"), dt.ARTS)

    def test_unknown_branch_returns_none(self):
        self.assertIsNone(dt.branch_default("UNKNOWN", "mystery_branch"))


class ClassifySkillTest(unittest.TestCase):
    def test_text_signal_wins_over_default(self):
        # a physical branch but a skill explicitly says arts
        verdict = dt.classify_skill("造成法术伤害", "WARRIOR", "lord")
        self.assertEqual(verdict["damage_type"], dt.ARTS)
        self.assertEqual(verdict["source"], "text")
        self.assertFalse(verdict["needs_review"])

    def test_default_fallback_when_silent(self):
        verdict = dt.classify_skill("攻击力+50%", "SNIPER", "fastshot")
        self.assertEqual(verdict["damage_type"], dt.PHYSICAL)
        self.assertEqual(verdict["source"], "default")

    def test_mixed_text_does_not_force_default(self):
        # 温蒂液氮大炮: arts hit + true-damage side effect -> None + review,
        # never silently relabeled to the physical branch default.
        verdict = dt.classify_skill("造成群体法术伤害并受到真实伤害", "SPECIAL", "pusher")
        self.assertIsNone(verdict["damage_type"])
        self.assertEqual(verdict["source"], "mixed_text")
        self.assertTrue(verdict["needs_review"])

    def test_silent_medic_buff_uses_branch_default(self):
        # medic attack-buff with no damage keyword: caller maps heal separately
        verdict = dt.classify_skill("攻击力+70%", "MEDIC", "physician")
        self.assertEqual(verdict["damage_type"], dt.HEAL)
        self.assertEqual(verdict["source"], "default")

    def test_unknown_returns_none_with_review(self):
        verdict = dt.classify_skill("无伤害描述", "UNKNOWN", "mystery")
        self.assertIsNone(verdict["damage_type"])
        self.assertTrue(verdict["needs_review"])


class OperatorBaselineTest(unittest.TestCase):
    def test_surtr_trait_arts(self):
        v = dt.classify_operator_baseline("攻击造成法术伤害", "WARRIOR", "artsfghter")
        self.assertEqual(v["damage_type"], dt.ARTS)
        self.assertEqual(v["source"], "trait")

    def test_silent_trait_uses_default(self):
        v = dt.classify_operator_baseline("同时攻击阻挡的所有敌人", "WARRIOR", "centurion")
        self.assertEqual(v["damage_type"], dt.PHYSICAL)
        self.assertEqual(v["source"], "default")

    def test_empty_trait_uses_default(self):
        v = dt.classify_operator_baseline("", "CASTER", "corecaster")
        self.assertEqual(v["damage_type"], dt.ARTS)


if __name__ == "__main__":
    unittest.main()
