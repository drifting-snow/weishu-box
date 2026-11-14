# -*- coding: utf-8 -*-
"""Tests for advisor/compass.py (lineup inference + plan synergy) and its
engine integration. Pure stdlib + the real curated lineup library.
"""
import unittest

from advisor.data import Dataset
from advisor.model import GameState, ShopCard, BoardUnit
from advisor.lineup import load_lineups
from advisor import compass as cm
from advisor.engine import Advisor


def state(board=(), shop=(), enemy_types=None, level=3):
    return GameState(
        round=3, gold=20, dispatch_level=level, difficulty="standard",
        shop=[ShopCard(**c) for c in shop],
        board=[BoardUnit(name=n) for n in board],
        enemy_types=list(enemy_types or []),
    )


class InferenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.lineups = load_lineups()

    def test_empty_board_no_enemy_is_none(self):
        self.assertIsNone(cm.infer_lineup(self.ds, state(), self.lineups))

    def test_empty_board_with_enemy_uses_counter_fallback(self):
        st = state(enemy_types=["stealth"])
        plan = cm.infer_lineup(self.ds, st, self.lineups)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.source, "enemy_fallback")
        self.assertEqual(plan.confidence, "weak")
        self.assertEqual(plan.lineup_id, "arts_anti_stealth")
        self.assertIn("stealth", plan.counters)

    def test_two_named_arts_units_infer_strong(self):
        # Miss.Christine + 伊桑 are both named early units of the arts lineup.
        plan = cm.infer_lineup(
            self.ds, state(board=["Miss.Christine", "伊桑"]), self.lineups)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.lineup_id, "arts_anti_stealth")
        self.assertEqual(plan.confidence, "strong")
        self.assertEqual(plan.source, "board")
        self.assertIn("奥术", plan.core_covered)

    def test_aegir_board_infers_growth_lineup(self):
        plan = cm.infer_lineup(
            self.ds, state(board=["幽灵鲨", "深巡"]), self.lineups)
        self.assertEqual(plan.lineup_id, "growth_aegir_devour")
        self.assertEqual(plan.confidence, "strong")

    def test_single_named_unit_is_weak_not_strong(self):
        plan = cm.infer_lineup(
            self.ds, state(board=["卡达"]), self.lineups)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.confidence, "weak")
        self.assertEqual(plan.weight, cm.WEAK_WEIGHT)

    def test_strong_plan_full_weight(self):
        plan = cm.infer_lineup(
            self.ds, state(board=["Miss.Christine", "伊桑"]), self.lineups)
        self.assertEqual(plan.weight, 1.0)


class OnPlanBonusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.lineups = load_lineups()
        cls.plan = cm.infer_lineup(
            cls.ds, state(board=["Miss.Christine", "伊桑"]), cls.lineups)

    def test_no_plan_gives_nothing(self):
        self.assertEqual(cm.on_plan_bonus(None, "卡达", ["奥术"]), (0.0, None))

    def test_named_carry_gets_carry_points(self):
        pts, why = cm.on_plan_bonus(self.plan, "艾雅法拉", ["奥术"])
        self.assertEqual(pts, cm.CARRY_PTS)
        self.assertIsNotNone(why)
        self.assertIn("carry", why)

    def test_named_non_carry_member_gets_member_points(self):
        pts, why = cm.on_plan_bonus(self.plan, "伊桑", ["奥术", "突袭"])
        self.assertEqual(pts, cm.MEMBER_PTS)
        # listed non-carry unit: prefixed as a plan member, role tag shown
        self.assertTrue(why.startswith("阵容名单内"))
        self.assertNotIn("carry", why)

    def test_core_bond_offlist_unit_gets_bond_points(self):
        # Fictional name not on the unit list, but it carries the core bond.
        pts, why = cm.on_plan_bonus(self.plan, "某奥术新干员", ["奥术"])
        self.assertEqual(pts, cm.CORE_BOND_PTS)
        self.assertIn("奥术", why)

    def test_off_plan_unit_gets_nothing(self):
        pts, why = cm.on_plan_bonus(self.plan, "烈夏", ["乌萨斯"])
        self.assertEqual((pts, why), (0.0, None))

    def test_weak_plan_discounts_bonus(self):
        weak = cm.infer_lineup(
            self.ds, state(board=["卡达"]), self.lineups)
        pts, _ = cm.on_plan_bonus(weak, "艾雅法拉", ["奥术"])
        self.assertAlmostEqual(pts, round(cm.CARRY_PTS * cm.WEAK_WEIGHT, 1))


class EngineIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.adv = Advisor(cls.ds)

    def _buy_scores(self, result):
        return {a["target"]: a["score"]
                for a in result["recommendations"] if a["verb"] == "buy"}

    def test_result_carries_lineup_summary(self):
        st = state(board=["Miss.Christine", "伊桑"], shop=[
            {"kind": "operator", "name": "卡达", "tier": 1, "price": 3},
        ])
        result = self.adv.recommend(st)
        self.assertIn("lineup", result)
        self.assertEqual(result["lineup"]["id"], "arts_anti_stealth")
        self.assertEqual(result["lineup"]["confidence"], "strong")

    def test_on_plan_card_outranks_scattered_off_plan_card(self):
        # Board commits to the arts lineup; the shop offers an on-plan arts
        # carry (卡达) and an off-plan 乌萨斯 filler (烈夏), same shop tier.
        st = state(board=["Miss.Christine", "伊桑"], shop=[
            {"kind": "operator", "name": "卡达", "tier": 1, "price": 3},
            {"kind": "operator", "name": "烈夏", "tier": 1, "price": 3},
        ])
        result = self.adv.recommend(st)
        scores = self._buy_scores(result)
        self.assertGreater(scores["卡达"], scores["烈夏"])
        # and the on-plan card is the overall top pick
        self.assertEqual(result["top_pick"]["target"], "卡达")

    def test_directionless_board_has_no_lineup_and_legacy_behavior(self):
        st = state(shop=[
            {"kind": "operator", "name": "烈夏", "tier": 1, "price": 3},
        ])
        result = self.adv.recommend(st)
        self.assertIsNone(result["lineup"])


if __name__ == "__main__":
    unittest.main()
