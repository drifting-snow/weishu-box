# -*- coding: utf-8 -*-
"""Stdlib unittest for advisor/scaling.py (standalone scaling layer).

The engine (advisor/engine.py) must never import this module; these tests only
cover the pure multiplier functions. Run: python -m unittest discover -s tests
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from advisor import scaling as sc  # noqa: E402


class EnemyDifficultyTest(unittest.TestCase):
    def test_dispatch_level_coeff_table(self):
        # published AC-SP-1..20 curve (doc 08)
        self.assertEqual(sc.enemy_difficulty_coeff(1), 1.00)
        self.assertEqual(sc.enemy_difficulty_coeff(2), 1.05)
        self.assertEqual(sc.enemy_difficulty_coeff(6), 1.25)
        self.assertEqual(sc.enemy_difficulty_coeff(10), 1.35)
        self.assertEqual(sc.enemy_difficulty_coeff(15), 1.50)
        self.assertEqual(sc.enemy_difficulty_coeff(20), 1.50)
        # plateau: levels 15-20 all cap at 1.5
        for lv in range(15, 21):
            self.assertEqual(sc.enemy_difficulty_coeff(lv), 1.50)

    def test_unknown_level_neutral(self):
        self.assertEqual(sc.enemy_difficulty_coeff(99), 1.0)

    def test_alliance_coeff_overrides(self):
        self.assertEqual(sc.enemy_difficulty_coeff(1, "standard"), 1.00)
        self.assertEqual(sc.enemy_difficulty_coeff(1, "hard_abyss"), 1.20)
        self.assertEqual(sc.enemy_difficulty_coeff(1, "desperate"), 1.35)
        self.assertEqual(sc.enemy_difficulty_coeff(1, "ultimate"), 1.50)

    def test_scale_enemy_applies_coeff(self):
        out = sc.scale_enemy(1000, 200, dispatch_level=6)
        self.assertEqual(out["hp"], 1250.0)   # 1000 * 1.25
        self.assertEqual(out["atk"], 250.0)
        self.assertEqual(out["difficulty_coeff"], 1.25)

    def test_resistance_delta_neutral_without_data(self):
        # no published per-level RES table -> additive delta stays 0
        self.assertEqual(sc.enemy_resistance_delta(10), 0)
        self.assertEqual(sc.enemy_defense_delta(10), 0)
        out = sc.scale_enemy(1000, 200, dispatch_level=10)
        self.assertEqual(out["res_delta"], 0)
        self.assertEqual(out["def_delta"], 0)

    def test_resistance_delta_accepts_measured_table(self):
        # a future measured table plugs in without code changes
        table = {5: 10, 10: 20}
        self.assertEqual(sc.enemy_resistance_delta(10, table), 20)
        self.assertEqual(sc.enemy_resistance_delta(6, table), 0)


class AccountPracticeTest(unittest.TestCase):
    def test_published_bonus_tiers(self):
        atk, dfn, hp = sc.account_practice_multiplier("e2_lvl60")
        self.assertEqual((atk, dfn, hp), (1.10, 1.10, 1.10))
        atk2, dfn2, hp2 = sc.account_practice_multiplier("e1_lvl1")
        self.assertEqual((atk2, dfn2, hp2), (1.05, 1.00, 1.00))

    def test_unknown_tier_neutral(self):
        self.assertEqual(sc.account_practice_multiplier("none"), (1.0, 1.0, 1.0))


class BondAttackTest(unittest.TestCase):
    # real rule shape from data/bond_scaling.json (e.g. 斥罪 advanced: every 3 stacks +2%)
    RULE = {
        "basic": {"stack_step": 3, "atk_pct_per_step": 1.0, "bond": "叙拉古"},
        "advanced": {"stack_step": 3, "atk_pct_per_step": 2.0, "bond": "叙拉古"},
    }

    def test_zero_stacks_neutral(self):
        self.assertEqual(sc.bond_attack_multiplier(self.RULE, 0, "advanced"), 1.0)

    def test_per_stack_formula(self):
        # 3 stacks -> one tick -> +2% ; 6 stacks -> two ticks -> +4%
        self.assertEqual(sc.bond_attack_multiplier(self.RULE, 3, "advanced"), 1.02)
        self.assertEqual(sc.bond_attack_multiplier(self.RULE, 6, "advanced"), 1.04)
        # floor division: 2 stacks -> no tick yet
        self.assertEqual(sc.bond_attack_multiplier(self.RULE, 2, "advanced"), 1.0)

    def test_basic_vs_advanced_form(self):
        self.assertEqual(sc.bond_attack_multiplier(self.RULE, 3, "basic"), 1.01)
        self.assertEqual(sc.bond_attack_multiplier(self.RULE, 3, "advanced"), 1.02)

    def test_missing_rule_neutral(self):
        self.assertEqual(sc.bond_attack_multiplier(None, 99), 1.0)
        self.assertEqual(sc.bond_attack_multiplier({}, 99), 1.0)

    def test_scale_panel_combines_bond_and_account(self):
        out = sc.scale_operator_panel(
            1000, 200, 3000, bond_rule=self.RULE, active_stacks=6,
            form="advanced", account_tier="e2_lvl60")
        # bond 1.04 * account 1.10 = 1.144
        self.assertAlmostEqual(out["atk_multiplier"], 1.04 * 1.10, places=5)
        self.assertAlmostEqual(out["atk"], 1000 * 1.04 * 1.10, places=2)
        # DEF/HP only get account bonus (no published bond rule for them)
        self.assertEqual(out["def"], 220.0)
        self.assertEqual(out["hp"], 3300.0)

    def test_scale_panel_def_hp_neutral_without_account(self):
        out = sc.scale_operator_panel(1000, 200, 3000, bond_rule=self.RULE,
                                      active_stacks=3, form="advanced")
        self.assertEqual(out["def"], 200.0)
        self.assertEqual(out["hp"], 3000.0)


class BondPanelFormulaTest(unittest.TestCase):
    # mirrors data/bond_panel_formulas.json rule shape
    YAN = {"bond": "炎", "stat": "atk", "scope": "bond",
           "form": "additive_pct", "base": 23, "per_stack": 0.9,
           "condition": None}
    JIANHSHOU = {"bond": "坚守", "stat": "hp", "scope": "all",
                 "form": "additive_pct", "base": 30, "per_stack": 1.25,
                 "condition": None}
    ZHULI = {"bond": "助力", "stat": "def", "scope": "all",
             "form": "additive_pct", "base": 15, "per_stack": 1.2,
             "condition": None}
    JINGZHUN = {"bond": "精准", "stat": "atk", "scope": "ranged",
                "form": "additive_pct", "base": 10, "per_stack": 1.2,
                "condition": None}
    TUXI = {"bond": "突袭", "stat": "atk_hp", "scope": "bond",
            "form": "additive_pct", "base": 10, "per_stack": 1.0,
            "condition": "技能期间"}
    WEIDUOLIYA = {"bond": "维多利亚", "stat": "damage", "scope": "bond",
                  "form": "total_pct", "base": 120, "per_stack": 0.8,
                  "condition": "携带装备"}

    def test_additive_formula_math(self):
        # 炎 at 100 stacks: 23 + 0.9*100 = 113% -> 2.13x
        self.assertAlmostEqual(
            sc.panel_multiplier_from_formula(self.YAN, 100), 2.13, places=4)
        # 坚守 at 40 stacks: 30 + 1.25*40 = 80% -> 1.8x
        self.assertAlmostEqual(
            sc.panel_multiplier_from_formula(self.JIANHSHOU, 40), 1.8, places=4)

    def test_total_formula_math(self):
        # 维多利亚 total_pct at 100: (120+80)% = 2.0x
        self.assertAlmostEqual(
            sc.panel_multiplier_from_formula(self.WEIDUOLIYA, 100), 2.0, places=4)

    def test_scope_all_applies_to_everyone(self):
        out = sc.bond_panel_multipliers(
            [self.JIANHSHOU, self.ZHULI], {"坚守": 40, "助力": 40},
            operator_bonds=["其他"], is_ranged=False)
        self.assertAlmostEqual(out["hp_multiplier"], 1.8, places=4)
        self.assertAlmostEqual(out["def_multiplier"], 1.63, places=4)  # 15+48=63%

    def test_ranged_scope_skips_melee(self):
        out_melee = sc.bond_panel_multipliers(
            [self.JINGZHUN], {"精准": 50}, operator_bonds=["精准"], is_ranged=False)
        self.assertEqual(out_melee["atk_multiplier"], 1.0)
        self.assertTrue(out_melee["skipped_conditional"])
        out_ranged = sc.bond_panel_multipliers(
            [self.JINGZHUN], {"精准": 50}, operator_bonds=["精准"], is_ranged=True)
        # 10 + 1.2*50 = 70% -> 1.7x
        self.assertAlmostEqual(out_ranged["atk_multiplier"], 1.7, places=4)

    def test_conditional_buff_skipped_unless_declared(self):
        # 突袭 only works during skill window; without the condition it is skipped
        out = sc.bond_panel_multipliers(
            [self.TUXI], {"突袭": 30}, operator_bonds=["突袭"], is_ranged=False)
        self.assertEqual(out["atk_multiplier"], 1.0)
        out2 = sc.bond_panel_multipliers(
            [self.TUXI], {"突袭": 30}, operator_bonds=["突袭"],
            conditions_met={"技能期间"})
        # 10 + 1*30 = 40% -> 1.4x on both atk and hp
        self.assertAlmostEqual(out2["atk_multiplier"], 1.4, places=4)
        self.assertAlmostEqual(out2["hp_multiplier"], 1.4, places=4)

    def test_inactive_bond_ignored(self):
        out = sc.bond_panel_multipliers(
            [self.YAN], {}, operator_bonds=["炎"], is_ranged=False)
        self.assertEqual(out["atk_multiplier"], 1.0)

    def test_multiple_bonds_multiply_on_same_stat(self):
        # 炎 (bond atk) + 精准 (ranged atk) both hit atk for a ranged 炎 operator
        out = sc.bond_panel_multipliers(
            [self.YAN, self.JINGZHUN], {"炎": 100, "精准": 50},
            operator_bonds=["炎", "精准"], is_ranged=True)
        # 2.13 * 1.7 = 3.621
        self.assertAlmostEqual(out["atk_multiplier"], 2.13 * 1.7, places=4)

    def test_real_formula_file_loads_and_computes(self):
        path = os.path.join(ROOT, "data", "bond_panel_formulas.json")
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        formulas = doc["formulas"]
        names = {r["bond"] for r in formulas}
        for required in ("炎", "阿戈尔", "坚守", "助力", "精准", "突袭"):
            self.assertIn(required, names)
        # all-ranged 坚守+助力 at 40 stacks must stay neutral for an unrelated
        # bond-only operator on atk, but still move hp/def (scope=all)
        out = sc.bond_panel_multipliers(
            formulas, {"坚守": 40, "助力": 40}, operator_bonds=[], is_ranged=False)
        self.assertGreater(out["hp_multiplier"], 1.0)
        self.assertGreater(out["def_multiplier"], 1.0)
        self.assertEqual(out["atk_multiplier"], 1.0)


class EngineDecouplingTest(unittest.TestCase):
    def test_engine_does_not_import_scaling(self):
        engine_path = os.path.join(ROOT, "advisor", "engine.py")
        with open(engine_path, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("scaling", src)


if __name__ == "__main__":
    unittest.main()
