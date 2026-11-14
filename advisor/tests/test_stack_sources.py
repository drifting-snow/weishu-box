# -*- coding: utf-8 -*-
"""Stdlib tests for the universal bond-stack source registry.
Run: python -m unittest tests.test_stack_sources -v"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, ROOT)


def load():
    with open(os.path.join(DATA, "stack_sources.json"), encoding="utf-8") as f:
        return json.load(f)


class StackRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = load()
        cls.src = cls.reg["sources"]
        with open(os.path.join(DATA, "operators.json"), encoding="utf-8") as f:
            cls.ops = json.load(f)
        cls.op_names = {o["name"] for o in cls.ops}

    def test_registry_is_current_with_parser(self):
        # regenerating must not change the committed file (deterministic)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "parse_stacks.py")],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        fresh = load()
        self.assertEqual(fresh["sources"], self.src)

    def test_no_unreviewed_unknown_shapes(self):
        self.assertEqual(self.reg["_meta"]["needs_review"], 0)
        self.assertNotIn("other", {s["shape"] for s in self.src})

    def test_every_operator_name_is_real(self):
        for s in self.src:
            self.assertIn(s["operator"], self.op_names)

    def test_multi_bond_entry_emits_one_record_per_bond(self):
        # 黍 gives both 炎 and 远见 layers from one entry
        shu = [s for s in self.src if s["operator"] == "黍" and s["form"] == "基础"]
        bonds = {s["target_bond"] for s in shu}
        self.assertIn("炎", bonds)
        self.assertIn("远见", bonds)
        yuanjian = next(s for s in shu if s["target_bond"] == "远见")
        self.assertEqual(yuanjian["amount"], 4)

    def test_named_fixed_amount_parsed(self):
        xi = [s for s in self.src if s["operator"] == "锡人" and s["form"] == "基础"]
        self.assertTrue(any(s["target_bond"] == "投资人" and s["amount"] == 4 for s in xi))

    def test_generic_aura_uses_wildcard(self):
        du = [s for s in self.src if s["operator"] == "渡桥" and s["form"] == "基础"]
        self.assertTrue(all(s["target_bond"] == "*" for s in du))
        self.assertTrue(any(s["shape"] == "generic_active_bond" and s["amount"] == 2 for s in du))
        # trigger timing is end-of-rest; the front-cell positioning now lives
        # in the separate scope field rather than being conflated with means.
        self.assertTrue(all(s["means"] == "end_of_rest" for s in du))
        self.assertTrue(all(s["scope"] == "front_cell" for s in du))

    def test_flat_cap_booster(self):
        # 薇薇安娜 raises the stacking cap by a flat layer count, not percent
        vv = [s for s in self.src if s["operator"] == "薇薇安娜"]
        self.assertTrue(vv)
        self.assertTrue(all(s["shape"] == "cap_booster" for s in vv))
        self.assertTrue(any(s.get("cap_bonus_flat") in (7, 14) for s in vv))

    def test_transient_conversion(self):
        zy = [s for s in self.src if s["operator"] == "折桠" and s["form"] == "基础"]
        self.assertTrue(any(s["shape"] == "convert_transient" and
                            s["target_bond"] == "乌萨斯" for s in zy))

    def test_dynamic_variable_amount_flagged(self):
        # 可露希尔 uses {showtag_value}; amount unknown statically but means known
        kl = [s for s in self.src if s["operator"] == "可露希尔"]
        self.assertTrue(kl)
        self.assertTrue(all(s["amount_dynamic"] and s["amount"] is None for s in kl))
        # fires at rest end; "each operator acquired" is the amount condition,
        # not the trigger, so means is end_of_rest rather than op_acquire.
        self.assertTrue(any(s["means"] == "end_of_rest" for s in kl))

    def test_caps_extracted(self):
        # 遥 奇迹 per-round capped stacking
        yao = [s for s in self.src if s["operator"] == "遥"
               and s["target_bond"] == "奇迹" and s["form"] == "基础"]
        self.assertTrue(any(s["cap_scope"] == "per_round" and s["cap"] == 12 for s in yao))

    def test_means_use_controlled_vocabulary(self):
        allowed = {"op_refresh", "op_acquire", "on_acquire", "on_sell",
                   "on_deploy", "on_skill", "on_kill", "on_affliction",
                   "aura_front", "aura_adjacent", "convert_transient",
                   "end_of_rest", "start_of_rest", "battle_start", "battle_end",
                   "passive_or_other"}
        for s in self.src:
            self.assertIn(s["means"], allowed, s["operator"])

    def test_economy_bonds_have_sources(self):
        for bond in ("远见", "奇迹", "投资人"):
            self.assertTrue(any(s["target_bond"] == bond for s in self.src), bond)

    def test_growth_mode_classifies_injection_vs_continuous(self):
        # 锡人 投资人 one-shot injection (no active requirement)
        xi = [s for s in self.src if s["operator"] == "锡人"
              and s["target_bond"] == "投资人" and s["form"] == "基础"]
        self.assertTrue(xi)
        self.assertTrue(all(s["growth_mode"] == "injection" for s in xi))
        # 卡达 奥术 continuous (text requires an already-active bond)
        kd = [s for s in self.src if s["operator"] == "卡达"]
        self.assertTrue(kd)
        self.assertTrue(all(s["growth_mode"] == "continuous" for s in kd))

    def test_growth_mode_controlled_vocabulary(self):
        allowed = {"injection", "continuous", "cap_booster"}
        for s in self.src:
            self.assertIn(s["growth_mode"], allowed)

    def test_cap_booster_growth_mode(self):
        vv = [s for s in self.src if s["operator"] == "薇薇安娜"]
        self.assertTrue(all(s["growth_mode"] == "cap_booster" for s in vv))

    def test_mowang_end_of_rest_override(self):
        # Source text omits trigger timing; human-curated override marks 魔王
        # (调和/吟游者, tier 6) as end-of-rest growth of the active core bond.
        mw = [s for s in self.src if s["operator"] == "魔王"]
        self.assertTrue(mw)
        # timing now comes from the data-driven operator_timing extractor,
        # not a hand-written override table.
        self.assertTrue(all(s["means"] == "end_of_rest" for s in mw))
        self.assertTrue(all(s["target_bond"] == "*" for s in mw))
        self.assertTrue(any(s["amount"] == 10 and s["form"] == "基础" for s in mw))
        self.assertTrue(any(s["amount"] == 20 and s["form"] == "进阶" for s in mw))


if __name__ == "__main__":
    unittest.main(verbosity=2)
