# -*- coding: utf-8 -*-
"""Stdlib tests for static weakness/counter matching. Run: python -m unittest tests.test_counters -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from advisor.data import Dataset
from advisor.engine import Advisor
from advisor.model import GameState, ShopCard
from advisor.counters import (
    load_enemy_types, operator_native_tags, counter_score, BOND_COUNTERS,
)


class EnemyTraitTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.types = load_enemy_types()

    def test_nine_tactical_enemy_types(self):
        self.assertEqual(
            set(self.types),
            {"special", "flying", "multi_hit", "elemental", "sustained",
             "stealth", "refraction", "lethal", "revival"},
        )

    def test_every_type_has_nonzero_counters(self):
        for key, et in self.types.items():
            self.assertTrue(et["counter_tags"], key)
            self.assertTrue(all(w > 0 for w in et["counter_tags"].values()), key)

    def test_bond_counter_bonds_are_real(self):
        ds = Dataset()
        names = {b["name"] for b in ds.bonds["core"] + ds.bonds["attached"]}
        for bond in BOND_COUNTERS:
            self.assertIn(bond, names)


class CounterScoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.ops = {o["name"]: o for o in cls.ds.operators}

    def test_native_anti_stealth_from_skill(self):
        r = counter_score(self.ds, self.ops["真言"], ["stealth"])
        self.assertTrue(any(h["tag"] == "anti_stealth" and h["ready"]
                            for h in r["hits"]))
        self.assertGreater(r["score"], 0)
        self.assertEqual(r["anti_synergy"], [])

    def test_no_counter_penalized_for_stealth(self):
        # 卡达 has no anti-stealth: no native hit, bond route still locked
        r = counter_score(self.ds, self.ops["卡达"], ["stealth"])
        self.assertFalse(any(h["tag"] == "anti_stealth" for h in r["hits"]))
        self.assertTrue(any(l["tag"] == "anti_stealth" for l in r["locked"]))

    def test_bond_counter_locked_then_unlocked(self):
        op = self.ops["艾雅法拉"]
        locked = counter_score(self.ds, op, ["stealth"], {"奥术": 2})
        self.assertTrue(any(l["bond"] == "奥术" and l["missing"] == 1
                            for l in locked["locked"]))
        self.assertFalse(any(h["tag"] == "anti_stealth" for h in locked["hits"]))
        unlocked = counter_score(self.ds, op, ["stealth"], {"奥术": 3})
        self.assertTrue(any(h["tag"] == "anti_stealth" and h["source"] == "bond"
                            for h in unlocked["hits"]))
        # unlocked answer suppresses the no-anti-stealth warning
        self.assertEqual(unlocked["anti_synergy"], [])
        self.assertGreater(unlocked["score"], locked["score"])

    def test_flying_rewards_anti_air_and_penalizes_ground(self):
        sniper = counter_score(self.ds, self.ops["灰喉"], ["flying"])
        self.assertTrue(any(h["tag"] == "anti_air" for h in sniper["hits"]))
        ground = counter_score(self.ds, self.ops["角峰"], ["flying"])
        self.assertTrue(any("对空" in a for a in ground["anti_synergy"]))
        self.assertLess(ground["score"], sniper["score"])

    def test_refraction_prefers_pierce_pure_arts_warned(self):
        pierce = counter_score(self.ds, self.ops["迷迭香"], ["refraction"])
        self.assertTrue(any(h["tag"] == "def_pierce" for h in pierce["hits"]))
        caster = counter_score(self.ds, self.ops["卡达"], ["refraction"])
        self.assertTrue(any("折射" in a for a in caster["anti_synergy"]))

    def test_revival_silence_and_dot(self):
        self.assertTrue(any(h["tag"] == "silence"
                            for h in counter_score(self.ds, self.ops["拉普兰德"], ["revival"])["hits"]))
        self.assertTrue(any(h["tag"] == "dot"
                            for h in counter_score(self.ds, self.ops["蓝毒"], ["revival"])["hits"]))

    def test_neutral_when_no_enemy_picture(self):
        r = counter_score(self.ds, self.ops["真言"], [])
        self.assertTrue(r["neutral"])
        self.assertEqual(r["score"], 0)

    def test_native_tags_include_anti_air_flag(self):
        self.assertIn("anti_air", operator_native_tags(self.ops["灰喉"]))
        self.assertNotIn("anti_air", operator_native_tags(self.ops["角峰"]))


class EngineIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.adv = Advisor(cls.ds)

    def test_enemy_picture_feeds_buy_reason(self):
        # 真言 answers a stealth run; its buy reason should cite the counter
        st = GameState(round=3, gold=9, dispatch_level=4, enemy_types=["stealth"],
                       shop=[ShopCard(kind="operator", name="真言", tier=4, price=4)])
        res = self.adv.recommend(st)
        pick = next(a for a in res["recommendations"] if a["target"] == "真言")
        self.assertIn("克制[anti_stealth]", pick["reason"])

    def test_no_enemy_picture_means_no_counter_reason(self):
        st = GameState(round=3, gold=9, dispatch_level=4,
                       shop=[ShopCard(kind="operator", name="真言", tier=4, price=4)])
        res = self.adv.recommend(st)
        pick = next(a for a in res["recommendations"] if a["target"] == "真言")
        self.assertNotIn("克制[", pick["reason"])

    def test_locked_bond_counter_surfaces_progress(self):
        # 艾雅法拉 in a stealth run with 2 奥术 on board -> "差1人解锁"
        st = GameState(round=4, gold=9, dispatch_level=4, enemy_types=["stealth"],
                       shop=[ShopCard(kind="operator", name="艾雅法拉", tier=4, price=4)])
        res = self.adv.recommend(st)
        pick = next(a for a in res["recommendations"] if a["target"] == "艾雅法拉")
        self.assertTrue("解锁anti_stealth" in pick["reason"] or
                        "奥术差" in pick["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
