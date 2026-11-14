# -*- coding: utf-8 -*-
"""Tests for armor-fit effDps (advisor/effdps.py) backed by REAL enemy stats.

The armor-fit term stays inert without an enemy picture (legacy engine
assertions stay byte-identical). Where the old guessed-band tests assumed
refraction meant "use physical", the real level-0 stats reverse that: refraction
enemies are high-DEF / low-RES, so arts dealers keep most of their damage while
physical dealers hit the 5% floor. These tests lock the real-data contract.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from advisor import damage_calc as dc
from advisor import effdps
from advisor.data import Dataset
from advisor.engine import Advisor, EFFDPS_FULL
from advisor.model import GameState, ShopCard


class EnemyResistanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stats = effdps._enemy_stats()

    def test_empty_or_unknown_picture_is_none(self):
        self.assertIsNone(effdps.enemy_resistance([]))
        self.assertIsNone(effdps.enemy_resistance(["does_not_exist"]))

    def test_known_category_returns_measured_worst(self):
        d, r = effdps.enemy_resistance(["refraction"])
        cw = self.stats["category_worst"]["refraction"]
        self.assertEqual(d, cw["worst_def"])
        self.assertEqual(r, cw["worst_res"])

    def test_multiple_categories_take_the_max(self):
        d, r = effdps.enemy_resistance(["special", "refraction"])
        self.assertEqual(d, max(self.stats["category_worst"]["special"]["worst_def"],
                                self.stats["category_worst"]["refraction"]["worst_def"]))
        self.assertEqual(r, max(self.stats["category_worst"]["special"]["worst_res"],
                                self.stats["category_worst"]["refraction"]["worst_res"]))

    def test_refraction_is_high_def_low_res(self):
        # The measured reversal that invalidated the old guessed bands.
        d, r = effdps.enemy_resistance(["refraction"])
        self.assertGreaterEqual(d, 1000)   # heavy physical armor
        self.assertLessEqual(r, 20)        # but low arts resistance


class MitigationFactorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = effdps.load_damage_profiles()
        cls.metrics = effdps.load_combat_metrics()

    def _expected_physical(self, name, defense):
        sp = effdps._representative_skill(self.profiles, name)
        atk = sp["skill_attack_power"]
        return dc.physical_hit(atk, defense) / dc.physical_hit(atk, 0)

    def _expected_arts(self, name, res):
        sp = effdps._representative_skill(self.profiles, name)
        atk = sp["skill_attack_power"]
        return dc.arts_hit(atk, res) / dc.arts_hit(atk, 0)

    def test_physical_factor_uses_continuous_formula(self):
        d, _ = effdps.enemy_resistance(["flying"])
        factor = effdps.mitigation_factor(self.profiles, "幽灵鲨", (d, 0))
        self.assertAlmostEqual(factor, self._expected_physical("幽灵鲨", d))

    def test_arts_factor_equals_one_minus_res_fraction(self):
        _, r = effdps.enemy_resistance(["special"])
        factor = effdps.mitigation_factor(self.profiles, "卡达", (0, r))
        self.assertAlmostEqual(factor, 1.0 - r / 100.0)

    def test_def_above_matrix_cap_lands_on_floor(self):
        # special worst def (3500) exceeds the old 1000 matrix cap; the
        # continuous formula must still resolve, clamped to the 5% floor.
        d, _ = effdps.enemy_resistance(["special"])
        self.assertGreater(d, 1000)
        factor = effdps.mitigation_factor(self.profiles, "幽灵鲨", (d, 0))
        self.assertEqual(factor, effdps.MIN_FACTOR)

    def test_refraction_penalizes_physical_rewards_arts(self):
        resistance = effdps.enemy_resistance(["refraction"])
        phys = effdps.mitigation_factor(self.profiles, "幽灵鲨", resistance)
        arts = effdps.mitigation_factor(self.profiles, "卡达", resistance)
        self.assertEqual(phys, effdps.MIN_FACTOR)   # cannot break 1100 def
        self.assertGreaterEqual(arts, 0.8)          # res only 20
        self.assertGreater(arts, phys)

    def test_true_damage_keeps_full_factor(self):
        if "魔王" in self.profiles:
            factor = effdps.mitigation_factor(
                self.profiles, "魔王", (3500, 60))
            self.assertEqual(factor, 1.0)

    def test_healer_has_no_armor_factor(self):
        self.assertIsNone(
            effdps.mitigation_factor(self.profiles, "褐果", (300, 30)))

    def test_none_picture_is_neutral_none(self):
        self.assertIsNone(
            effdps.mitigation_factor(self.profiles, "幽灵鲨", None))

    def test_factor_never_below_minimum_floor(self):
        for cat in self.stats_categories():
            resistance = effdps.enemy_resistance([cat])
            for name in ("幽灵鲨", "卡达"):
                f = effdps.mitigation_factor(self.profiles, name, resistance)
                self.assertGreaterEqual(f, effdps.MIN_FACTOR)

    def stats_categories(self):
        return list(effdps._enemy_stats()["category_worst"].keys())

    def test_effective_dps_components(self):
        eff, factor, raw = effdps.effective_dps(
            self.profiles, self.metrics, "幽灵鲨", ["special"])
        self.assertIsNotNone(eff)
        self.assertAlmostEqual(eff, round(raw * factor, 2))

    def test_unknown_operator_returns_none(self):
        eff, factor, raw = effdps.effective_dps(
            self.profiles, self.metrics, "不存在的干员", ["flying"])
        self.assertIsNone(eff)


class EngineArmorFitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.adv = Advisor(cls.ds)
        cls.profiles = effdps.load_damage_profiles()
        cls.metrics = effdps.load_combat_metrics()
        cls.phys = "幽灵鲨"
        cls.arts = "卡达"

    def _buy_scores(self, enemy_types):
        st = GameState(
            round=4, gold=99, dispatch_level=6, enemy_types=list(enemy_types),
            shop=[
                ShopCard(kind="operator", name=self.phys,
                         tier=self.ds.operator(self.phys)["shop_tier"], price=3),
                ShopCard(kind="operator", name=self.arts,
                         tier=self.ds.operator(self.arts)["shop_tier"], price=3),
            ])
        res = self.adv.recommend(st)
        return {a["target"]: a for a in res["recommendations"]
                if a["verb"] == "buy"}

    def test_no_picture_keeps_term_inert(self):
        scores = self._buy_scores([])
        for name in (self.phys, self.arts):
            self.assertNotIn("护甲契合", scores[name]["reason"])

    def test_refraction_wave_favors_arts_dealer(self):
        # Real stats: refraction is high-DEF/low-RES, so the arts dealer keeps
        # ~80% while the physical dealer sits on the 5% floor.
        scores = self._buy_scores(["refraction"])
        self.assertIn("护甲契合", scores[self.phys]["reason"])
        self.assertIn("护甲契合", scores[self.arts]["reason"])
        self.assertGreaterEqual(
            scores[self.arts]["score"], scores[self.phys]["score"])
        phys_reason = [r for r in scores[self.phys]["reason"].split("；")
                       if "护甲契合" in r][0]
        self.assertIn("5%", phys_reason)   # physical retained only the floor

    def test_special_high_def_penalizes_physical_to_floor(self):
        eff, factor, _ = effdps.effective_dps(
            self.profiles, self.metrics, self.phys, ["special"])
        self.assertIsNotNone(eff)
        self.assertEqual(factor, effdps.MIN_FACTOR)


if __name__ == "__main__":
    unittest.main(verbosity=2)
