# -*- coding: utf-8 -*-
"""Tests for economy derivation and investment-aware buy scoring.

Special prices come from 整备能力 entries, not a marker field:
  真理 / 至简  -> 购买价格为1
  温蒂         -> 售出价格为3 (基础) / 6 (进阶)
  海沫         -> 自身售出价格+1 (基础, max4)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from advisor.data import Dataset
from advisor import economy as econ
from advisor.engine import Advisor
from advisor.model import GameState, ShopCard


class EconomyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.adv = Advisor(cls.ds)

    # ---- default tiered buy price ----
    def test_tiered_buy_price(self):
        table = self.ds.economy["buy_price_by_shop_tier"]
        self.assertEqual(int(table["1"]), 2)
        self.assertEqual(int(table["2"]), 3)
        self.assertEqual(int(table["4"]), 3)
        self.assertEqual(int(table["5"]), 4)
        self.assertEqual(int(table["6"]), 4)

    def test_default_buy_price_uses_shop_tier(self):
        # 幽灵鲨 shop_tier=1 -> 2 gold default
        you = self.ds.operator("幽灵鲨")
        self.assertEqual(you["shop_tier"], 1)
        self.assertEqual(econ.buy_price(self.ds, you), 2)
        # 歌蕾蒂娅 shop_tier=5 -> 4 gold
        glad = self.ds.operator("歌蕾蒂娅")
        self.assertEqual(glad["shop_tier"], 5)
        self.assertEqual(econ.buy_price(self.ds, glad), 4)

    # ---- special buy price override ----
    def test_special_buy_price_one_gold(self):
        for name in ("真理", "至简"):
            op = self.ds.operator(name)
            self.assertEqual(econ.buy_price(self.ds, op), 1, name)

    def test_rules_card_buy_price_derives_without_explicit_price(self):
        card = ShopCard(kind="operator", name="真理", tier=2)  # no price set
        self.assertEqual(self.adv.rules.card_buy_price(card), 1)
        card2 = ShopCard(kind="operator", name="幽灵鲨", tier=1)
        self.assertEqual(self.adv.rules.card_buy_price(card2), 2)

    def test_explicit_card_price_wins(self):
        card = ShopCard(kind="operator", name="真理", tier=2, price=3)
        self.assertEqual(self.adv.rules.card_buy_price(card), 3)

    # ---- sell price ----
    def test_default_sell_price(self):
        self.assertEqual(econ.sell_price(self.ds, self.ds.operator("幽灵鲨")), 1)

    def test_fixed_sell_price(self):
        wendy = self.ds.operator("温蒂")
        self.assertEqual(econ.sell_price(self.ds, wendy, advanced=False), 3)
        self.assertEqual(econ.sell_price(self.ds, wendy, advanced=True), 6)

    def test_bonus_sell_price(self):
        haimo = self.ds.operator("海沫")
        # base default 1 + bonus 1 = 2
        self.assertEqual(econ.sell_price(self.ds, haimo, advanced=False), 2)

    # ---- investment tagging ----
    def test_investment_tags_present(self):
        tags = {t["tag"] for t in econ.investment_tags(self.ds.operator("真理"))}
        self.assertIn("special_buy_price", tags)
        tags_osita = {t["tag"] for t in econ.investment_tags(self.ds.operator("奥斯塔"))}
        self.assertIn("free_refresh", tags_osita)
        tags_wendy = {t["tag"] for t in econ.investment_tags(self.ds.operator("温蒂"))}
        self.assertIn("special_sell_price", tags_wendy)

    def test_pure_combat_operator_has_no_investment(self):
        # 卡达 only has 持续叠加 combat stack -> no economy investment tag
        self.assertFalse(econ.has_investment(self.ds.operator("卡达")))

    def test_investment_score_positive(self):
        self.assertGreater(econ.investment_score(self.ds.operator("真理")), 0)
        self.assertEqual(econ.investment_score(self.ds.operator("卡达")), 0)

    # ---- engine actually factors investment into ranking ----
    def test_engine_ranks_investment_card_above_plain_combat(self):
        # 真理 (1-gold investment) vs a plain 3-gold combat card, same level,
        # no bond context. Investment + ROI should lift 真理's score.
        st = GameState(round=2, gold=5, dispatch_level=3,
                       shop=[
                           ShopCard(kind="operator", name="真理", tier=2),
                           ShopCard(kind="operator", name="卡达", tier=3),
                       ])
        res = self.adv.recommend(st)
        buy = {a["target"]: a for a in res["recommendations"] if a["verb"] == "buy"}
        self.assertIn("投资型", buy["真理"]["reason"])
        self.assertGreater(buy["真理"]["score"], buy["卡达"]["score"])
        # and the reported cost reflects the 1-gold override
        self.assertEqual(buy["真理"]["cost"], 1)

    def test_engine_affordability_uses_derived_price(self):
        # only 1 gold: 真理 (1) affordable, a 3-gold card flagged insufficient
        st = GameState(round=2, gold=1, dispatch_level=3,
                       shop=[
                           ShopCard(kind="operator", name="真理", tier=2),
                           ShopCard(kind="operator", name="歌蕾蒂娅", tier=5),
                       ])
        res = self.adv.recommend(st)
        buy = {a["target"]: a for a in res["recommendations"] if a["verb"] == "buy"}
        self.assertNotIn("资金不足", buy["真理"]["reason"])
        self.assertIn("资金不足", buy["歌蕾蒂娅"]["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
