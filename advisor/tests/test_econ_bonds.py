# -*- coding: utf-8 -*-
"""Stdlib tests for the static economy-bond (经济羁绊) buy logic.
Run: python -m unittest tests.test_econ_bonds -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from advisor.data import Dataset
from advisor.engine import Advisor
from advisor.model import GameState, ShopCard, BoardUnit
from advisor import econ_bonds as eb
from advisor.item_economy import DEFAULT_TOTAL_ROUNDS


class EconBondRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()

    def test_activation_need_matches_bond_data(self):
        for bond, spec in eb.ECON_BONDS.items():
            self.assertEqual(spec["need"], self.ds.bond_need(bond), bond)

    def test_agreed_weight_ordering(self):
        # 远见 (direct gold) ranks above the probability/amplifier engines
        self.assertGreater(eb.ECON_BONDS["远见"]["base_weight"],
                           eb.ECON_BONDS["奇迹"]["base_weight"])
        self.assertEqual(eb.ECON_BONDS["奇迹"]["base_weight"],
                         eb.ECON_BONDS["投资人"]["base_weight"])

    def test_timing_factor_decays_with_window(self):
        self.assertEqual(eb.timing_factor(1), 1.0)                 # 14 rounds left
        self.assertEqual(eb.timing_factor(DEFAULT_TOTAL_ROUNDS), 0.0)  # no window
        mid = eb.timing_factor(DEFAULT_TOTAL_ROUNDS - 4)           # 4 rounds left
        self.assertAlmostEqual(mid, 4.0 / eb.FULL_PAYOFF_WINDOW)
        self.assertTrue(0 < mid < 1)


class EconBondValueTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.adv = Advisor(cls.ds)
        # locate real members dynamically
        def members(bond):
            return [o["name"] for o in cls.ds.operators if bond in o.get("bonds", [])]
        cls.yuanjian = members("远见")
        cls.qiji = members("奇迹")
        cls.touziren = members("投资人")
        assert len(cls.yuanjian) >= 2
        assert len(cls.touziren) >= 1

    def _counts(self, st):
        return self.adv.rules.bond_counts(st)

    def test_locked_when_below_activation_headcount(self):
        name = self.yuanjian[0]
        op = self.ds.operator(name)
        st = GameState(round=3, gold=10, dispatch_level=6)
        r = eb.econ_bond_value(self.ds, op, st, self._counts(st))
        self.assertEqual(r["active"], [])
        self.assertEqual(len(r["locked"]), 1)
        self.assertEqual(r["locked"][0]["bond"], "远见")
        self.assertEqual(r["locked"][0]["missing"], 1)  # need 2, prospective 1
        self.assertGreater(r["score"], 0)               # partial future credit

    def test_activates_on_second_distinct_member(self):
        first, second = self.yuanjian[0], self.yuanjian[1]
        st = GameState(round=3, gold=10, dispatch_level=6,
                       board=[BoardUnit(name=first, count=1, bonds=["远见"])])
        op = self.ds.operator(second)
        r = eb.econ_bond_value(self.ds, op, st, self._counts(st))
        self.assertEqual(len(r["active"]), 1)
        self.assertEqual(r["active"][0]["bond"], "远见")
        self.assertEqual(r["locked"], [])
        # full base weight at timing factor 1.0, then discounted by growability
        feas = eb.sf.feasibility_factor("远见")
        expected = round(eb.ECON_BONDS["远见"]["base_weight"] * 1.0 * feas, 1)
        self.assertEqual(r["score"], expected)
        self.assertEqual(r["active"][0]["feasibility"], feas)

    def test_already_owned_adds_no_new_member(self):
        name = self.yuanjian[0]
        op = self.ds.operator(name)
        st = GameState(round=3, gold=10, dispatch_level=6,
                       board=[BoardUnit(name=name, count=1, bonds=["远见"])])
        r = eb.econ_bond_value(self.ds, op, st, self._counts(st))
        # same name held -> prospective stays 1, still missing one, not active
        self.assertEqual(r["active"], [])
        self.assertEqual(r["locked"][0]["missing"], 1)

    def test_no_payoff_window_zeroes_engine_score(self):
        name = self.yuanjian[0]
        op = self.ds.operator(name)
        st = GameState(round=DEFAULT_TOTAL_ROUNDS, gold=10, dispatch_level=6)
        r = eb.econ_bond_value(self.ds, op, st, self._counts(st))
        self.assertTrue(r["dead_window"])
        self.assertEqual(r["score"], 0.0)
        self.assertTrue(r["locked"][0]["no_window"])

    def test_touren_needs_three(self):
        name = self.touziren[0]
        op = self.ds.operator(name)
        st = GameState(round=3, gold=10, dispatch_level=6)
        r = eb.econ_bond_value(self.ds, op, st, self._counts(st))
        self.assertEqual(r["locked"][0]["missing"], 2)  # need 3, prospective 1

    def test_non_econ_bond_operator_is_neutral(self):
        # pick an operator with none of the three economy bonds
        name = next(o["name"] for o in self.ds.operators
                    if not (set(o.get("bonds", [])) & set(eb.ECON_BONDS)))
        op = self.ds.operator(name)
        st = GameState(round=3, gold=10, dispatch_level=6)
        r = eb.econ_bond_value(self.ds, op, st, self._counts(st))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["active"], [])
        self.assertEqual(r["locked"], [])


class EconBondEngineIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.adv = Advisor(cls.ds)
        cls.yuanjian = [o["name"] for o in cls.ds.operators
                        if "远见" in o.get("bonds", [])]

    def test_buy_reason_cites_economy_bond(self):
        name = self.yuanjian[0]
        op = self.ds.operator(name)
        st = GameState(round=3, gold=20, dispatch_level=6,
                       shop=[ShopCard(kind="operator", name=name,
                                      tier=op["shop_tier"], price=3)])
        res = self.adv.recommend(st)
        pick = next(a for a in res["recommendations"] if a["target"] == name)
        self.assertIn("经济引擎", pick["reason"])
        self.assertIn("远见", pick["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
