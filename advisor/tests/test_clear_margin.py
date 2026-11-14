# -*- coding: utf-8 -*-
"""Tests for stage-1 continuous clear-margin (advisor/clear_margin).

Logic (mode/round resolution, bands, inert guards) is tested directly; the
end-to-end record uses the committed data/act3_waves.json plus real operator
damage profiles/metrics, asserting the formula and regulation HP scaling.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from advisor.model import GameState, BoardUnit
from advisor import clear_margin as cm
from advisor import effdps
from advisor import regulation_hp as rhp


def state(**kw):
    base = dict(round=1, enemy_types=["special"], enemy_names=["寻险水手"],
                board=[BoardUnit(name="卡达")])
    base.update(kw)
    return GameState(**base)


class InertAndResolutionTest(unittest.TestCase):
    def setUp(self):
        self.doc = cm.load_waves()
        self.profiles = effdps.load_damage_profiles()
        self.metrics = effdps.load_combat_metrics()

    def test_no_enemy_picture_returns_none(self):
        st = GameState(board=[BoardUnit(name="卡达")])
        self.assertIsNone(cm.clear_margin(st, self.profiles, self.metrics, self.doc))

    def test_empty_board_returns_none(self):
        st = GameState(enemy_types=["flying"])
        self.assertIsNone(cm.clear_margin(st, self.profiles, self.metrics, self.doc))

    def test_unknown_round_returns_none(self):
        st = state(round=99)
        self.assertIsNone(cm.clear_margin(st, self.profiles, self.metrics, self.doc))

    def test_resolve_mode_regulation_level_wins(self):
        st = state(regulation_level=20, difficulty="standard")
        self.assertEqual(cm.resolve_mode(st), "mode_single_20")

    def test_resolve_mode_difficulty_fallback(self):
        self.assertEqual(cm.resolve_mode(state(difficulty="standard")),
                         "mode_multi_normal")
        self.assertEqual(cm.resolve_mode(state(difficulty="hard_abyss")),
                         "mode_multi_abyss")
        self.assertEqual(cm.resolve_mode(state(difficulty="speed")),
                         "mode_multi_funny")

    def test_resolve_level_stem_round_one(self):
        stem = cm.resolve_level_stem(self.doc, "mode_multi_normal", 1)
        self.assertEqual(stem, "level_act3autochess_01")

    def test_resolve_level_stem_unknown_mode_is_none(self):
        self.assertIsNone(cm.resolve_level_stem(self.doc, "nope", 1))

    def test_band_boundaries(self):
        self.assertEqual(cm.classify_margin(0.5), cm.BAND_CRITICAL)
        self.assertEqual(cm.classify_margin(0.6), cm.BAND_TIGHT)
        self.assertEqual(cm.classify_margin(0.9), cm.BAND_TIGHT)
        self.assertEqual(cm.classify_margin(1.0), cm.BAND_ADEQUATE)
        self.assertEqual(cm.classify_margin(1.49), cm.BAND_ADEQUATE)
        self.assertEqual(cm.classify_margin(1.5), cm.BAND_COMFORTABLE)


class TeamDpsAggregationTest(unittest.TestCase):
    def setUp(self):
        from advisor.data import Dataset
        self.ds = Dataset()
        self.profiles = effdps.load_damage_profiles()
        self.metrics = effdps.load_combat_metrics()

    def test_damage_dealer_counted_healer_skipped(self):
        # a MEDIC (initial.baseline_damage_type == heal) has no armor-fit
        # effDps, so it is skipped rather than assigned a fabricated number
        healer = next(p["name"] for p in self.profiles.values()
                      if p.get("profession") == "MEDIC"
                      and p["name"] in self.metrics)
        st = GameState(enemy_types=["special"],
                       board=[BoardUnit(name="卡达"), BoardUnit(name=healer)])
        dps, counted, skipped, detail = cm.team_effective_dps(
            self.ds, st, self.profiles, self.metrics)
        self.assertGreater(dps, 0)
        self.assertEqual(counted, 1)
        self.assertEqual(skipped, 1)
        self.assertEqual(len(detail), 1)
        # a lone 卡达 activates no bond -> neutral multiplier
        self.assertEqual(detail[0]["scale"], 1.0)


class EndToEndMarginTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = cm.load_waves()
        cls.profiles = effdps.load_damage_profiles()
        cls.metrics = effdps.load_combat_metrics()
        cls.level = cls.doc["level_stems"]["level_act3autochess_01"]

    def test_record_matches_formula_at_base_hp(self):
        st = state(round=1, difficulty="standard")  # no regulation level -> mult 1
        rec = cm.clear_margin(st, self.profiles, self.metrics, self.doc)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["level_stem"], "level_act3autochess_01")
        self.assertEqual(rec["hp_multiplier"], 1.0)
        self.assertEqual(rec["enemy_hp_total"], float(self.level["total_hp_level0"]))
        expected_margin = rec["team_eff_dps"] * rec["clear_window_t"] / rec["enemy_hp_total"]
        self.assertAlmostEqual(rec["margin"], round(expected_margin, 3), places=2)
        self.assertEqual(rec["band"], cm.classify_margin(rec["margin"]))
        self.assertEqual(rec["kill_time_t"],
                         round(rec["enemy_hp_total"] / rec["team_eff_dps"], 2))

    def test_regulation_level_scales_hp_and_shrinks_margin(self):
        base = cm.clear_margin(state(round=1), self.profiles, self.metrics, self.doc)
        hard = cm.clear_margin(state(round=1, regulation_level=20),
                               self.profiles, self.metrics, self.doc)
        self.assertAlmostEqual(hard["hp_multiplier"],
                               rhp.regulation_hp_multiplier(20), places=4)
        # same team DPS, ~13.89x HP -> margin shrinks by the same factor
        self.assertAlmostEqual(hard["margin"] * hard["hp_multiplier"],
                               base["margin"], places=2)
        self.assertLess(hard["margin"], base["margin"])

    def test_state_roundtrip_keeps_regulation_level(self):
        from advisor.model import state_from_dict
        st = state(regulation_level=14)
        back = state_from_dict(st.to_dict())
        self.assertEqual(back.regulation_level, 14)
        # legacy state without the field still loads
        legacy = state()
        d = legacy.to_dict()
        del d["regulation_level"]
        self.assertIsNone(state_from_dict(d).regulation_level)


class MarginBonusTest(unittest.TestCase):
    def setUp(self):
        self.profiles = effdps.load_damage_profiles()
        self.metrics = effdps.load_combat_metrics()
        self.healer = next(p["name"] for p in self.profiles.values()
                           if p.get("profession") == "MEDIC" and p["name"] in self.metrics)

    def test_damage_card_bonus_on_stress_bands(self):
        pts, why = cm.operator_margin_bonus(
            self.profiles, self.metrics, "卡达", ["special"], cm.BAND_CRITICAL)
        self.assertEqual(pts, cm.DAMAGE_BONUS[cm.BAND_CRITICAL])
        self.assertTrue(why)
        pts2, _ = cm.operator_margin_bonus(
            self.profiles, self.metrics, "卡达", ["special"], cm.BAND_TIGHT)
        self.assertEqual(pts2, cm.DAMAGE_BONUS[cm.BAND_TIGHT])

    def test_no_bonus_on_calm_bands(self):
        for band in (cm.BAND_ADEQUATE, cm.BAND_COMFORTABLE):
            self.assertEqual(cm.operator_margin_bonus(
                self.profiles, self.metrics, "卡达", ["special"], band), (0.0, []))

    def test_healer_never_gets_damage_bonus(self):
        self.assertEqual(cm.operator_margin_bonus(
            self.profiles, self.metrics, self.healer, ["special"],
            cm.BAND_CRITICAL), (0.0, []))

    def test_upgrade_adjustment_signed(self):
        self.assertEqual(cm.upgrade_margin_adjustment(cm.BAND_COMFORTABLE), 10.0)
        self.assertEqual(cm.upgrade_margin_adjustment(cm.BAND_CRITICAL), -15.0)
        for band in (cm.BAND_TIGHT, cm.BAND_ADEQUATE):
            self.assertEqual(cm.upgrade_margin_adjustment(band), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
