# -*- coding: utf-8 -*-
"""Tests for clean-room operator buff multipliers (advisor/buffs).

Uses the real committed Dataset and bond formula data; operators are selected
dynamically by bond/profession so the tests do not hard-code roster changes.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from advisor.data import Dataset
from advisor.model import GameState, BoardUnit
from advisor import buffs
from advisor import effdps


def dealers_for_bond(ds, bond, n):
    out = []
    for op in ds.operators:
        if bond in op.get("bonds", []) and op.get("prof") != "医疗":
            out.append(op["name"])
        if len(out) >= n:
            break
    return out


class BuffsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()

    def _state(self, board, **kw):
        return GameState(board=[BoardUnit(name=n) for n in board], **kw)

    def test_no_board_no_buff(self):
        st = self._state([])
        # an operator not on the board still resolves to neutral on empty state
        info = buffs.operator_damage_multiplier(self.ds, st, "卡达")
        self.assertEqual(info["dps_mult"], 1.0)
        self.assertEqual(info["notes"], [])

    def test_activated_bond_panel_base_bonus(self):
        # 炎 core need=3, atk additive base +23% (stacks default 0)
        need = self.ds.bond_need("炎")
        members = dealers_for_bond(self.ds, "炎", need)
        self.assertEqual(len(members), need)
        st = self._state(members)
        self.assertIn("炎", buffs.active_bonds(self.ds, st))
        for nm in members:
            info = buffs.operator_damage_multiplier(self.ds, st, nm)
            self.assertAlmostEqual(info["atk_mult"], 1.23, places=3)
        # a non-炎 operator does not get the bond-scoped bonus
        outsider = next(o["name"] for o in self.ds.operators
                        if "炎" not in o.get("bonds", []))
        self.assertEqual(
            buffs.operator_damage_multiplier(self.ds, st, outsider)["atk_mult"], 1.0)

    def test_below_activation_threshold_no_bonus(self):
        need = self.ds.bond_need("炎")
        members = dealers_for_bond(self.ds, "炎", need - 1)
        st = self._state(members)
        self.assertNotIn("炎", buffs.active_bonds(self.ds, st))
        for nm in members:
            self.assertEqual(
                buffs.operator_damage_multiplier(self.ds, st, nm)["atk_mult"], 1.0)

    def test_bond_stacks_grow_panel_multiplier(self):
        need = self.ds.bond_need("炎")
        members = dealers_for_bond(self.ds, "炎", need)
        st = self._state(members, bond_stacks={"炎": 10})
        # additive: 1 + (23 + 0.9*10)/100 = 1.32
        info = buffs.operator_damage_multiplier(self.ds, st, members[0])
        self.assertAlmostEqual(info["atk_mult"], 1.32, places=3)

    def test_equipment_atk_bonus(self):
        # 源石溶剂 atk_pct +40; needs an equipment entry on the operator
        st = GameState(board=[BoardUnit(name="卡达")],
                       equipment={"卡达": ["源石溶剂"]})
        info = buffs.operator_damage_multiplier(self.ds, st, "卡达")
        self.assertAlmostEqual(info["atk_mult"], 1.40, places=3)

    def test_equipment_condition_auto_satisfied_with_gear(self):
        # 维多利亚 total_pct damage formula is conditioned on 携带装备.
        need = self.ds.bond_need("维多利亚")
        members = dealers_for_bond(self.ds, "维多利亚", need)
        if len(members) < need:
            self.skipTest("not enough 维多利亚 damage dealers in roster")
        carry = members[0]
        st = GameState(board=[BoardUnit(name=n) for n in members],
                       equipment={carry: ["源石溶剂"]})
        info = buffs.operator_damage_multiplier(self.ds, st, carry)
        # total_pct at stacks 0 -> 120/100 = 1.20, then equipment x1.40
        self.assertAlmostEqual(info["atk_mult"], 1.20 * 1.40, places=2)

    def test_ranged_scope_only_benefits_ranged(self):
        # 精准 attached need=2, scope=ranged, atk base +10%
        need = self.ds.bond_need("精准")
        members = [o["name"] for o in self.ds.operators
                   if "精准" in o.get("bonds", [])][:need]
        st = self._state(members)
        if "精准" not in buffs.active_bonds(self.ds, st):
            self.skipTest("精准 not activated by first members")
        ranged = next((n for n in members
                       if self.ds.operator(n).get("position") == "远程位"), None)
        melee = next((n for n in members
                      if self.ds.operator(n).get("position") == "近战位"), None)
        if ranged:
            self.assertAlmostEqual(
                buffs.operator_damage_multiplier(self.ds, st, ranged)["atk_mult"],
                1.10, places=2)
        if melee:
            self.assertEqual(
                buffs.operator_damage_multiplier(self.ds, st, melee)["atk_mult"], 1.0)


class EliteScalingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.profiles = effdps.load_damage_profiles()
        cls.metrics = effdps.load_combat_metrics()

    def test_elite_panel_ratio_scales_team_dps(self):
        from advisor import clear_margin as cm
        base_st = GameState(enemy_types=["special"],
                            board=[BoardUnit(name="卡达", elite=False)])
        elite_st = GameState(enemy_types=["special"],
                             board=[BoardUnit(name="卡达", elite=True)])
        d0, c0, s0, detail0 = cm.team_effective_dps(
            self.ds, base_st, self.profiles, self.metrics)
        d1, c1, s1, detail1 = cm.team_effective_dps(
            self.ds, elite_st, self.profiles, self.metrics)
        self.assertEqual((c0, s0), (1, 0))
        self.assertGreater(d1, d0)
        ratio = self.metrics["卡达"]["elite"]["base_dps"] / \
            self.metrics["卡达"]["initial"]["base_dps"]
        self.assertAlmostEqual(d1 / d0, ratio, places=3)
        self.assertTrue(detail1[0]["scale"] > 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
