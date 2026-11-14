# -*- coding: utf-8 -*-
"""Tests for the lineup (team-composition) layer and the curated lineup library."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from advisor import lineup
from advisor.lineup import (
    load_lineups, recommend_lineups, counter_fit, get_lineup, stage_units,
)

OPS = None


def ops():
    global OPS
    if OPS is None:
        import json
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "data", "operators.json")
        with open(path, encoding="utf-8") as f:
            OPS = {o["name"]: o for o in json.load(f)}
    return OPS


class LineupLibraryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lineups = load_lineups()
        cls.ids = [L["id"] for L in cls.lineups]

    def test_library_count_and_archetypes(self):
        self.assertEqual(len(self.lineups), 13)
        arch = {L["archetype"] for L in self.lineups}
        self.assertEqual(arch, {"combat", "economy", "growth", "flex"})

    def test_ids_unique(self):
        self.assertEqual(len(self.ids), len(set(self.ids)))

    def test_every_stage_has_units_and_population_label(self):
        for L in self.lineups:
            for stage in ("early", "mid", "late"):
                st = L["stages"][stage]
                self.assertIn("pop", st)
                self.assertGreaterEqual(len(st["units"]), 3)
                for u in st["units"]:
                    self.assertIn(u["name"], ops())
                    self.assertIn(u["role"],
                                  {"carry", "tank", "heal", "control", "support", "econ"})

    def test_tier_matches_dataset_and_curves_up(self):
        for L in self.lineups:
            max_by_stage = {}
            for stage in ("early", "mid", "late"):
                tiers = []
                for u in L["stages"][stage]["units"]:
                    real = ops()[u["name"]]["shop_tier"]
                    self.assertEqual(u["tier"], real,
                                     f"{L['id']} {u['name']} tier mismatch")
                    tiers.append(real)
                max_by_stage[stage] = max(tiers)
            # late-game core must reach at least as high a tier as early picks
            self.assertGreaterEqual(max_by_stage["late"], max_by_stage["early"])

    def test_counter_and_weak_keys_are_real_enemy_types(self):
        import json
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "data", "enemy_traits.json")
        with open(path, encoding="utf-8") as f:
            valid = set(json.load(f)["enemy_types"].keys())
        for L in self.lineups:
            for k in L.get("counters", []) + L.get("weak", []):
                self.assertIn(k, valid)


class CounterFitTest(unittest.TestCase):
    def test_neutral_without_enemy_picture(self):
        L = get_lineup("arts_anti_stealth")
        fit = counter_fit(L, [])
        self.assertTrue(fit["neutral"])
        self.assertEqual(fit["score"], 0.0)

    def test_stealth_wave_rewards_anti_stealth_lineup(self):
        L = get_lineup("arts_anti_stealth")
        fit = counter_fit(L, ["stealth"])
        self.assertIn("stealth", fit["hits"])
        self.assertGreater(fit["score"], 0)

    def test_weakness_penalty_is_negative(self):
        # bulwark cannot hit air -> flying wave is a weakness
        L = get_lineup("bulwark_sustain")
        fit = counter_fit(L, ["flying"])
        self.assertIn("flying", fit["weaknesses"])
        self.assertLess(fit["score"], 0)


class RecommendTest(unittest.TestCase):
    def test_stealth_ranks_anti_stealth_first(self):
        recs = recommend_lineups(enemy_types=["stealth"])
        self.assertEqual(recs[0]["id"], "arts_anti_stealth")
        self.assertIn("stealth", recs[0]["counter_hits"])

    def test_refraction_prefers_physical_over_arts(self):
        recs = recommend_lineups(enemy_types=["refraction"])
        top_ids = [r["id"] for r in recs[:2]]
        self.assertIn("physical_pierce_kazimierz", top_ids)
        # pure-arts anti-stealth lineup must sit below the physical piercer here
        order = {r["id"]: i for i, r in enumerate(recs)}
        self.assertLess(order["physical_pierce_kazimierz"],
                        order["arts_anti_stealth"])

    def test_banned_core_bond_filters_lineup(self):
        recs = recommend_lineups(banned_bonds=["奥术"])
        self.assertNotIn("arts_anti_stealth", [r["id"] for r in recs])
        # others remain
        self.assertIn("bulwark_sustain", [r["id"] for r in recs])

    def test_availability_filter_keeps_lineup_with_obtainable_core(self):
        # only late cores of the economy lineup are offered -> it survives,
        # lineups whose late core is entirely absent drop out
        econ_late = {u["name"] for u in get_lineup("economy_investor_miracle")
                     ["stages"]["late"]["units"]}
        recs = recommend_lineups(available_operators=list(econ_late))
        ids = {r["id"] for r in recs}
        self.assertIn("economy_investor_miracle", ids)

    def test_default_order_when_no_picture_is_stable(self):
        recs = recommend_lineups()
        # all 13 present and combat archetypes rank before economy on ties
        self.assertEqual(len(recs), 13)
        self.assertTrue(all(r["neutral"] for r in recs))

    def test_stage_units_helper(self):
        early = stage_units("growth_aegir_devour", "early")
        self.assertTrue(any(u["name"] == "幽灵鲨" for u in early))
        self.assertEqual(stage_units("growth_aegir_devour", "nope"), [])


class TiaoeMowangFlexTest(unittest.TestCase):
    def test_flex_lineup_exists_with_special_mechanic(self):
        L = get_lineup("tiaoe_mowang_flex")
        self.assertIsNotNone(L)
        self.assertEqual(L["archetype"], "flex")
        sm = L["special_mechanic"]
        self.assertIn("linchpin", sm)
        self.assertIn("hero_gift", sm)
        # linchpin must be the real in-dataset operator 魔王
        self.assertIn("魔王", sm["linchpin"])

    def test_mowang_is_real_operator_and_late_stage_carries_heal(self):
        import json
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "data", "operators.json")
        with open(path, encoding="utf-8") as f:
            opnames = {o["name"] for o in json.load(f)}
        self.assertIn("魔王", opnames)
        late = stage_units("tiaoe_mowang_flex", "late")
        self.assertTrue(any(u["name"] == "魔王" for u in late))

    def test_hero_gift_unit_is_not_pretended_to_be_a_dataset_unit(self):
        # the gifted 盟约·辅助干员 is a runtime token, must NOT appear as a unit
        L = get_lineup("tiaoe_mowang_flex")
        all_units = [u["name"] for s in L["stages"].values() for u in s["units"]]
        self.assertNotIn("盟约·辅助干员", all_units)
        self.assertIn("盟约·辅助干员", L["special_mechanic"]["hero_gift"])

    def test_recommend_passes_through_special_mechanic(self):
        recs = recommend_lineups()
        flex = next(r for r in recs if r["id"] == "tiaoe_mowang_flex")
        self.assertIsNotNone(flex["special_mechanic"])
        self.assertEqual(flex["archetype_label"], "万用挂件型")

    def test_banning_tiaohe_removes_flex_lineup(self):
        recs = recommend_lineups(banned_bonds=["调和"])
        self.assertNotIn("tiaoe_mowang_flex", [r["id"] for r in recs])


if __name__ == "__main__":
    unittest.main()
