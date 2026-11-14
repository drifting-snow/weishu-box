# -*- coding: utf-8 -*-
"""Tests for round-aware consumable economy item valuation.

Core rule being guarded: delayed items (next_round / recurring gold) are good
early when many payback rounds remain, but should be rejected near the end of
a run when there is no time to recover the cost.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from advisor.data import Dataset
from advisor import item_economy as ie
from advisor.engine import Advisor
from advisor.model import GameState, ShopCard

TOTAL = ie.DEFAULT_TOTAL_ROUNDS  # 15


class ItemEconomyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.adv = Advisor(cls.ds)
        cls.by_name = {i["name"]: i for i in cls.ds.items}

    # ---- classification ----
    def test_classification_timing_and_benefit(self):
        self.assertEqual(ie.classify(self.by_name["盟约之币"]),
                         (ie.IMMEDIATE, ie.GOLD))
        self.assertEqual(ie.classify(self.by_name["见钱眼开玩偶"]),
                         (ie.NEXT_ROUND, ie.GOLD))
        self.assertEqual(ie.classify(self.by_name["精打细算玩偶"]),
                         (ie.RECURRING, ie.GOLD))
        self.assertEqual(ie.classify(self.by_name["博士投影"]),
                         (ie.NEXT_ROUND, ie.ELITE))
        self.assertEqual(ie.classify(self.by_name["人事部记录"]),
                         (ie.IMMEDIATE, ie.REFRESH))
        self.assertEqual(ie.classify(self.by_name["简易通讯机"]),
                         (ie.IMMEDIATE, ie.RECRUIT))

    def test_all_consumables_classify_without_other(self):
        # every consumable must land on a known benefit, not fall through to OTHER
        for it in self.ds.items:
            if ie.is_consumable(it):
                timing, benefit = ie.classify(it)
                self.assertIn(timing, (ie.IMMEDIATE, ie.NEXT_ROUND, ie.RECURRING),
                              it["name"])
                self.assertNotEqual(benefit, ie.OTHER, it["name"])

    def test_non_consumable_returns_none(self):
        # 坚守盾牌 is a persistent bond item, not a consumable
        self.assertFalse(ie.is_consumable(self.by_name["坚守盾牌"]))
        self.assertIsNone(ie.value_item(self.by_name["坚守盾牌"], 1))

    # ---- payback window ----
    def test_window_calculation(self):
        self.assertEqual(ie.effective_rounds_left(2, TOTAL), 13)
        self.assertEqual(ie.effective_rounds_left(15, TOTAL), 0)
        self.assertEqual(ie.effective_rounds_left(99, TOTAL), 0)

    def test_recurring_gold_strong_early_weak_late(self):
        it = self.by_name["精打细算玩偶"]  # price 3, +1 per later round
        early = ie.value_item(it, current_round=2, total_rounds=TOTAL)
        late = ie.value_item(it, current_round=14, total_rounds=TOTAL)
        self.assertEqual(early["timing"], ie.RECURRING)
        self.assertGreater(early["score"], late["score"])
        self.assertGreater(early["window"], late["window"])

    def test_recurring_gold_no_window_is_rejected(self):
        it = self.by_name["精打细算玩偶"]
        dead = ie.value_item(it, current_round=TOTAL, total_rounds=TOTAL)
        self.assertEqual(dead["window"], 0)
        self.assertLess(dead["score"], 0)
        self.assertIn("来不及回本", dead["rationale"])

    def test_next_round_gold_rejected_on_final_round(self):
        it = self.by_name["见钱眼开玩偶"]  # next-round +2 gold
        dead = ie.value_item(it, current_round=TOTAL, total_rounds=TOTAL)
        self.assertLess(dead["score"], 0)
        # but fine with at least one round remaining
        ok = ie.value_item(it, current_round=TOTAL - 1, total_rounds=TOTAL)
        self.assertGreaterEqual(ok["window"], 1)

    def test_immediate_gold_works_any_round(self):
        it = self.by_name["盟约之币"]  # price 1, immediate +1 gold
        early = ie.value_item(it, current_round=1, total_rounds=TOTAL)
        last = ie.value_item(it, current_round=TOTAL, total_rounds=TOTAL)
        self.assertEqual(early["timing"], ie.IMMEDIATE)
        # immediate payoff does not depend on remaining window
        self.assertEqual(early["score"], last["score"])

    # ---- engine end-to-end: same recurring item, early vs late ranking ----
    def test_engine_prefers_recurring_item_early_over_late(self):
        card = ShopCard(kind="item", name="精打细算玩偶", price=3)
        early_st = GameState(round=2, gold=6, dispatch_level=3, shop=[card])
        late_st = GameState(round=14, gold=6, dispatch_level=3, shop=[card])
        early = next(a for a in self.adv.recommend(early_st)["recommendations"]
                     if a["verb"] == "buy" and a["target"] == "精打细算玩偶")
        late = next(a for a in self.adv.recommend(late_st)["recommendations"]
                    if a["verb"] == "buy" and a["target"] == "精打细算玩偶")
        self.assertGreater(early["score"], late["score"])
        self.assertIn("延时生效", early["reason"])

    def test_engine_flags_delayed_item_window_in_reason(self):
        card = ShopCard(kind="item", name="见钱眼开玩偶", price=1)
        st = GameState(round=5, gold=5, dispatch_level=3, shop=[card])
        res = self.adv.recommend(st)
        buy = next(a for a in res["recommendations"]
                   if a["verb"] == "buy" and a["target"] == "见钱眼开玩偶")
        self.assertIn("回本窗口", buy["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
