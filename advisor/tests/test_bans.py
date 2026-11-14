# -*- coding: utf-8 -*-
"""Tests for draft bans: banned operators (never recommended) and banned
bonds (lineups built on them excluded). Real Dataset, deterministic.
"""
import unittest

from advisor.data import Dataset
from advisor.model import GameState, ShopCard, BoardUnit, state_from_dict
from advisor.engine import Advisor
from advisor import compass as cm
from advisor.lineup import load_lineups


def state(**kw):
    base = dict(round=3, gold=20, dispatch_level=3,
                shop=[ShopCard(kind="operator", name="卡达", tier=1, price=3),
                      ShopCard(kind="operator", name="烈夏", tier=1, price=3)],
                board=[], enemy_types=[])
    base.update(kw)
    return GameState(**base)


class BannedOperatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adv = Advisor(Dataset())

    def _buy_targets(self, st):
        r = self.adv.recommend(st)
        return [a["target"] for a in r["recommendations"] if a["verb"] == "buy"]

    def test_no_ban_keeps_both_cards(self):
        targets = self._buy_targets(state())
        self.assertIn("卡达", targets)
        self.assertIn("烈夏", targets)

    def test_banned_operator_never_recommended(self):
        st = state(banned_operators=["卡达"])
        targets = self._buy_targets(st)
        self.assertNotIn("卡达", targets)
        self.assertIn("烈夏", targets)

    def test_ban_all_operators_leaves_only_non_buy_actions(self):
        st = state(banned_operators=["卡达", "烈夏"])
        r = self.adv.recommend(st)
        self.assertFalse(any(a["verb"] == "buy" for a in r["recommendations"]))
        # upgrade/refresh still present, i.e. the advisor does not go silent
        self.assertTrue(r["recommendations"])


class BannedBondCompassTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.lineups = load_lineups()

    def test_banned_core_bond_excludes_that_lineup(self):
        # Board clearly builds the arts lineup, but 奥术 is banned this run.
        st = state(board=[BoardUnit(name="Miss.Christine"),
                          BoardUnit(name="伊桑")],
                   banned_bonds=["奥术"])
        plan = cm.infer_lineup(self.ds, st, self.lineups)
        if plan is not None:
            self.assertNotEqual(plan.lineup_id, "arts_anti_stealth")
            self.assertNotIn("奥术", plan.core_bonds)

    def test_enemy_fallback_respects_banned_bond(self):
        # Empty board + stealth enemies normally picks the arts anti-stealth
        # lineup; banning 奥术 must route around it.
        st = state(enemy_types=["stealth"], banned_bonds=["奥术"])
        plan = cm.infer_lineup(self.ds, st, self.lineups)
        if plan is not None:
            self.assertNotEqual(plan.lineup_id, "arts_anti_stealth")
            self.assertEqual(plan.source, "enemy_fallback")


class ModelBanParsingTest(unittest.TestCase):
    def test_defaults_are_empty(self):
        st = GameState()
        self.assertEqual(st.banned_operators, [])
        self.assertEqual(st.banned_bonds, [])

    def test_state_from_dict_parses_bans(self):
        st = state_from_dict({
            "round": 2, "shop": [], "board": [],
            "banned_operators": ["卡达"], "banned_bonds": ["奥术"],
        })
        self.assertEqual(st.banned_operators, ["卡达"])
        self.assertEqual(st.banned_bonds, ["奥术"])

    def test_legacy_state_without_ban_fields_still_loads(self):
        st = state_from_dict({"round": 1, "shop": [], "board": []})
        self.assertEqual(st.banned_operators, [])
        self.assertEqual(st.banned_bonds, [])
        self.assertEqual(st.enemy_names, [])

    def test_state_roundtrips_enemy_names(self):
        st = state_from_dict({
            "round": 3, "shop": [], "board": [],
            "enemy_types": ["refraction"],
            "enemy_names": ["假想敌：镜波", "源石虫"],
        })
        self.assertEqual(st.enemy_types, ["refraction"])
        self.assertEqual(st.enemy_names, ["假想敌：镜波", "源石虫"])
        self.assertEqual(st.to_dict()["enemy_names"], ["假想敌：镜波", "源石虫"])


if __name__ == "__main__":
    unittest.main()
