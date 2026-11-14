# -*- coding: utf-8 -*-
"""Tests for advisor/roadmap.py: full build curve, stage gating, next-target
selection, and enemy-driven pivot advice. Real curated lineups, deterministic.
"""
import unittest

from advisor.data import Dataset
from advisor.model import GameState, BoardUnit
from advisor.lineup import load_lineups
from advisor import compass as cm
from advisor import roadmap as rm
from advisor.engine import Advisor


def make_state(board=(), level=2, enemies=None, banned_bonds=None):
    return GameState(
        round=3, gold=10, dispatch_level=level,
        board=[BoardUnit(name=n) for n in board],
        enemy_types=list(enemies or []),
        banned_bonds=list(banned_bonds or []),
    )


ARTS_BOARD = ["Miss.Christine", "伊桑"]


class StageMappingTest(unittest.TestCase):
    def test_level_to_stage(self):
        self.assertEqual(rm.current_stage(1), "early")
        self.assertEqual(rm.current_stage(2), "early")
        self.assertEqual(rm.current_stage(3), "mid")
        self.assertEqual(rm.current_stage(4), "mid")
        self.assertEqual(rm.current_stage(5), "late")
        self.assertEqual(rm.current_stage(6), "late")

    def test_out_of_range_clamped(self):
        self.assertEqual(rm.current_stage(99), "late")
        self.assertEqual(rm.current_stage(0), "early")


class RoadmapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.lineups = load_lineups()
        cls.plan = cm.infer_lineup(
            cls.ds, make_state(ARTS_BOARD, level=2), cls.lineups)

    def test_no_plan_returns_none(self):
        self.assertIsNone(rm.build_roadmap(
            self.ds, make_state(), None, self.lineups))

    def test_full_three_stages_present_with_population_and_goal(self):
        road = rm.build_roadmap(
            self.ds, make_state(ARTS_BOARD, level=2), self.plan, self.lineups)
        self.assertEqual(list(road["stages"].keys()), ["early", "mid", "late"])
        for stage in road["stages"].values():
            self.assertTrue(stage["units"])
            self.assertIn("pop", stage)
            self.assertTrue(stage["goal"])

    def test_ownership_flags_and_count(self):
        st = make_state(ARTS_BOARD, level=2)
        road = rm.build_roadmap(self.ds, st, self.plan, self.lineups)
        # the two board operators are flagged owned; Miss.Christine is in early
        owned_flags = [(u["name"], u["owned"])
                       for s in road["stages"].values() for u in s["units"]]
        owned_names = [n for n, ok in owned_flags if ok]
        self.assertIn("Miss.Christine", owned_names)
        self.assertIn("伊桑", owned_names)
        self.assertEqual(road["ownership"]["owned"], 2)
        # cumulative stages repeat names; planned counts unique people
        unique_planned = {n for n, _ in owned_flags}
        self.assertEqual(road["ownership"]["planned"], len(unique_planned))

    def test_next_targets_respect_dispatch_level_and_ownership(self):
        # level 2: only unowned early units with shop tier <= 2 (卡达 T1, 褐果 T1)
        road = rm.build_roadmap(
            self.ds, make_state(ARTS_BOARD, level=2), self.plan, self.lineups)
        self.assertEqual(road["next_targets"], ["卡达", "褐果"])
        # owned and too-high-tier units are excluded
        self.assertNotIn("伊桑", road["next_targets"])      # owned
        self.assertNotIn("艾雅法拉", road["next_targets"])  # T4 > level 2
        # econ / 场下 pieces stay out of the on-board chase list
        self.assertNotIn("星极", road["next_targets"])

    def test_off_board_targets_include_econ(self):
        # early stage lists 星极 as role=econ (奇迹场下); she belongs off-board
        road = rm.build_roadmap(
            self.ds, make_state(ARTS_BOARD, level=2), self.plan, self.lineups)
        self.assertIn("星极", road["off_board_targets"])
        self.assertNotIn("星极", road["next_targets"])
        self.assertNotIn("卡达", road["off_board_targets"])

    def test_higher_level_unlocks_mid_targets(self):
        # Redesign: big carries (艾雅法拉/逻各斯/夕) live in late only; mid is
        # flex/transition (卡达/车尔尼/褐果/流明/夜莺). Do not expect late cores
        # in mid next_targets.
        mid = rm.build_roadmap(
            self.ds, make_state(ARTS_BOARD, level=4), self.plan, self.lineups)
        self.assertEqual(mid["current_stage"], "mid")
        self.assertNotIn("艾雅法拉", mid["next_targets"])
        for flex in ("卡达", "车尔尼", "褐果"):
            self.assertIn(flex, mid["next_targets"])
        late = rm.build_roadmap(
            self.ds, make_state(ARTS_BOARD, level=5), self.plan, self.lineups)
        self.assertEqual(late["current_stage"], "late")
        self.assertIn("艾雅法拉", late["next_targets"])

    def test_roles_and_tips_exposed(self):
        road = rm.build_roadmap(
            self.ds, make_state(ARTS_BOARD, level=2), self.plan, self.lineups)
        self.assertIn("艾雅法拉", road["roles"]["carry"])
        self.assertTrue(road["key_tips"])


class PivotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.lineups = load_lineups()
        cls.plan = cm.infer_lineup(
            cls.ds, make_state(ARTS_BOARD), cls.lineups)

    def test_no_enemy_picture_no_pivot(self):
        self.assertIsNone(rm.evaluate_pivot(
            self.ds, make_state(ARTS_BOARD), self.plan, self.lineups))

    def test_neutral_enemy_no_pivot(self):
        # an enemy key this lineup is not weak to -> no pivot advice
        pv = rm.evaluate_pivot(
            self.ds, make_state(ARTS_BOARD, enemies=["flying"]),
            self.plan, self.lineups)
        self.assertIsNone(pv)

    def test_weakness_hit_suggests_counter_lineups(self):
        pv = rm.evaluate_pivot(
            self.ds, make_state(ARTS_BOARD, enemies=["refraction"]),
            self.plan, self.lineups)
        self.assertIsNotNone(pv)
        self.assertTrue(pv.should_pivot)
        self.assertIn("refraction", pv.weak_hit)
        alt_ids = [a["id"] for a in pv.alternatives]
        self.assertIn("physical_pierce_kazimierz", alt_ids)
        # never recommend pivoting into the same lineup
        self.assertNotIn(self.plan.lineup_id, alt_ids)
        self.assertTrue(pv.weak_why)

    def test_banning_all_counters_forces_tech_fix_verdict(self):
        # ban every core bond of the refraction-counter lineups -> no alt
        st = make_state(ARTS_BOARD, enemies=["refraction"],
                        banned_bonds=["精准", "卡西米尔", "叙拉古", "维多利亚"])
        pv = rm.evaluate_pivot(self.ds, st, self.plan, self.lineups)
        self.assertIsNotNone(pv)
        self.assertFalse(pv.should_pivot)
        self.assertEqual(pv.alternatives, [])


class EngineRoadmapIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adv = Advisor(Dataset())

    def test_result_contains_roadmap_and_pivot(self):
        st = make_state(ARTS_BOARD, level=2, enemies=["refraction"])
        r = self.adv.recommend(st)
        self.assertIsNotNone(r["roadmap"])
        self.assertEqual(r["roadmap"]["name"], "奥术法反隐队")
        self.assertEqual(r["roadmap"]["ownership"]["planned"], 12)
        self.assertIsNotNone(r["pivot"])
        self.assertTrue(r["pivot"]["should_pivot"])

    def test_directionless_run_has_null_roadmap_and_pivot(self):
        r = self.adv.recommend(make_state())
        self.assertIsNone(r["roadmap"])
        self.assertIsNone(r["pivot"])


if __name__ == "__main__":
    unittest.main()
