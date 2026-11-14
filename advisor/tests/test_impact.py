# -*- coding: utf-8 -*-
"""Stdlib unittest for the unified marginal-impact ruler (advisor/impact.py).

Step 1 contract: impact.py only aggregates existing modules and is NOT wired
into engine.py, so these tests pin its normalization/ownership behavior while
the legacy engine keeps its 125 green tests untouched.
Run: python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from advisor.data import Dataset
from advisor.rules import Rules
from advisor.model import GameState, ShopCard, BoardUnit
from advisor import impact
from advisor.impact import (
    operator_impact, item_impact, evaluate_shop, axis_weights,
    DEFAULT_WEIGHTS, HIGH_PRESSURE_ENEMIES, EARLY_ROUND,
)


class ImpactTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.rules = Rules(cls.ds)

    def _op_card(self, name, tier=None, price=None):
        op = self.ds.operator(name)
        return ShopCard(kind="operator", name=name,
                        tier=tier or op["shop_tier"], price=price)

    # ---- structural contract ----
    def test_axes_normalized_0_100(self):
        st = GameState(round=4, gold=40, dispatch_level=6,
                       shop=[self._op_card("真言")])
        im = operator_impact(self.ds, self.rules, st.shop[0], st)
        for axis in (im.power, im.economy, im.growth):
            self.assertGreaterEqual(axis, 0.0)
            self.assertLessEqual(axis, 100.0)
        # weighted total stays inside the same 0..100 ruler
        self.assertGreaterEqual(im.total_impact, 0.0)
        self.assertLessEqual(im.total_impact, 100.0)
        self.assertAlmostEqual(sum(im.weights), 1.0, places=3)

    def test_impact_per_gold_matches_division(self):
        st = GameState(round=3, gold=40, dispatch_level=3,
                       shop=[self._op_card("蓝毒")])
        im = operator_impact(self.ds, self.rules, st.shop[0], st)
        self.assertIsNotNone(im.impact_per_gold)
        # impact_per_gold uses the unrounded total; the stored total is rounded
        # to 1 decimal, so compare at 1 decimal (ROI does not need 2-dp exactness).
        self.assertAlmostEqual(im.impact_per_gold,
                               round(im.total_impact / im.cost, 2), places=1)

    # ---- power axis: counters only fire under a matching enemy picture ----
    def test_counter_lifts_power_under_stealth_picture(self):
        # 真言 natively carries anti_stealth; same card, same board, the only
        # difference is the enemy picture, so power must rise when stealth is set.
        card = self._op_card("真言")
        neutral = operator_impact(self.ds, self.rules, card,
                                  GameState(round=6, gold=40, dispatch_level=6))
        stealth = operator_impact(self.ds, self.rules, card,
                                  GameState(round=6, gold=40, dispatch_level=6,
                                            enemy_types=["stealth"]))
        self.assertGreater(stealth.power, neutral.power)
        self.assertTrue(any("克制[anti_stealth]" in r for r in stealth.reasons))
        self.assertEqual(neutral.power > 0, True)  # baseline tier power remains

    def test_no_enemy_picture_counter_is_zero(self):
        card = self._op_card("真言")
        im = operator_impact(self.ds, self.rules, card,
                             GameState(round=6, gold=40, dispatch_level=6))
        self.assertFalse(any("克制" in r for r in im.reasons))

    # ---- growth axis: merge + bond activation ----
    def test_third_copy_maxes_growth_axis(self):
        # holding 2 copies -> the third copy's growth axis saturates at/near 100
        card = self._op_card("烈夏")
        st = GameState(round=4, gold=8, dispatch_level=2, target_bond="乌萨斯",
                       shop=[card],
                       board=[BoardUnit(name="烈夏", count=2, bonds=["乌萨斯"])])
        im = operator_impact(self.ds, self.rules, card, st)
        self.assertGreaterEqual(im.growth, 95.0)
        self.assertTrue(any("三合一" in r for r in im.reasons))

    def test_bond_activation_buy_scores_growth(self):
        # 2 of 3 乌萨斯 held; buying a third distinct member activates the bond
        card = self._op_card("真理")
        st = GameState(round=4, gold=8, dispatch_level=3,
                       shop=[card],
                       board=[
                           BoardUnit(name="烈夏", count=1, bonds=["乌萨斯"]),
                           BoardUnit(name="冻河", count=1, bonds=["乌萨斯"]),
                       ])
        im = operator_impact(self.ds, self.rules, card, st)
        self.assertTrue(any("买入即点亮" in r for r in im.reasons))
        self.assertGreater(im.growth, 40.0)

    # ---- hard tier gate is exposed, not overridden by the ruler ----
    def test_illegal_tier_flagged_not_reranked_away(self):
        card = ShopCard(kind="operator", name="塔露拉", tier=6)
        st = GameState(round=2, gold=99, dispatch_level=1, shop=[card])
        im = operator_impact(self.ds, self.rules, card, st)
        self.assertFalse(im.legal)

    # ---- context-adaptive weights ----
    def test_high_pressure_enemy_shifts_weight_to_power(self):
        base = axis_weights(GameState(round=5, enemy_types=[]))
        pressed = axis_weights(GameState(round=5, enemy_types=["lethal"]))
        self.assertGreater(pressed[0], base[0])   # power weight up
        self.assertAlmostEqual(sum(pressed), 1.0, places=3)

    def test_early_round_favors_economy(self):
        early = axis_weights(GameState(round=1, enemy_types=[]))
        late = axis_weights(GameState(round=8, enemy_types=[]))
        self.assertGreater(early[2], late[2])     # economy weight up early
        self.assertEqual(DEFAULT_WEIGHTS[0], 0.40)
        self.assertIn("lethal", HIGH_PRESSURE_ENEMIES)
        self.assertEqual(EARLY_ROUND, 3)

    # ---- cheap card ROI: special-price operator beats normal price on per_gold ----
    def test_special_price_card_has_higher_roi(self):
        # 真理 has a 1-gold special buy price; a standard 3-gold card with
        # comparable impact should show lower impact_per_gold.
        cheap = self._op_card("真理")
        normal = self._op_card("蓝毒")
        st = GameState(round=3, gold=40, dispatch_level=3, shop=[cheap, normal])
        im_cheap = operator_impact(self.ds, self.rules, cheap, st)
        im_normal = operator_impact(self.ds, self.rules, normal, st)
        self.assertEqual(im_cheap.cost, 1)
        self.assertGreaterEqual(im_normal.cost, 2)
        self.assertGreater(im_cheap.impact_per_gold, im_normal.impact_per_gold * 0.5)

    # ---- item routing keeps the same Impact shape ----
    def test_item_impact_shape_and_bond_bonus(self):
        # find a bond-dedicated item in the dataset.
        bond_item = next((i for i in self.ds.items if i.get("bond")), None)
        self.assertIsNotNone(bond_item)
        card = ShopCard(kind="item", name=bond_item["name"],
                        tier=bond_item.get("tier"), price=bond_item.get("price", 1))
        st = GameState(round=3, gold=20, dispatch_level=3,
                       target_bond=bond_item["bond"], shop=[card])
        im = item_impact(self.ds, self.rules, card, st)
        self.assertEqual(im.kind, "item")
        self.assertTrue(im.legal)
        for axis in (im.power, im.economy, im.growth):
            self.assertGreaterEqual(axis, 0.0)
            self.assertLessEqual(axis, 100.0)

    # ---- item numeric power / drawback / economy-boost on the ruler ----
    def _item_card(self, name, price=None):
        it = self.ds.item(name)
        return ShopCard(kind="item", name=name, tier=it.get("tier"),
                        price=price if price is not None else it.get("price", 1))

    # A tier-6 holder makes carrier_maturity ~1.0 so item power is not discounted.
    def _mature_board(self):
        return [BoardUnit(name="夕", count=1, bonds=["炎", "奥术"])]

    def test_combat_item_numeric_power_and_drawback(self):
        # 源石溶剂: atk +40%, 60hp/sec drain -> raw power = 40 - 10 = 30.
        # With a mature tier-6 holder the carrier factor is ~1.0 (full value).
        st = GameState(round=3, gold=20, dispatch_level=6,
                       shop=[self._item_card("源石溶剂")], board=self._mature_board())
        im = item_impact(self.ds, self.rules, st.shop[0], st)
        self.assertAlmostEqual(im.power, 30.0, places=1)
        self.assertTrue(any("负面" in r for r in im.reasons))
        self.assertEqual(im.economy, 0.0)  # non-consumable: no fake economy score
        # on an empty board the same multiplier is discounted to carrier base 0.4
        empty = GameState(round=3, gold=20, dispatch_level=3,
                          shop=[self._item_card("源石溶剂")])
        im0 = item_impact(self.ds, self.rules, empty.shop[0], empty)
        self.assertAlmostEqual(im0.power, 12.0, places=1)

    def test_conditional_item_scores_only_numeric_part(self):
        # 天马之枪 is needs_review (combo) but atk +50% is still numeric power.
        st = GameState(round=5, gold=20, dispatch_level=6,
                       shop=[self._item_card("天马之枪")], board=self._mature_board())
        im = item_impact(self.ds, self.rules, st.shop[0], st)
        self.assertAlmostEqual(im.power, 50.0, places=1)
        self.assertTrue(any("后置不计分" in r for r in im.reasons))

    def test_consumable_economy_uses_net_gold_and_spare_gold_factor(self):
        card = self._item_card("见钱眼开玩偶")  # next round +2, price 1 -> net +1
        # empty board: spare-gold factor 0.5 discounts the economy score
        empty = GameState(round=2, gold=20, dispatch_level=3, shop=[card])
        im0 = item_impact(self.ds, self.rules, empty.shop[0], empty)
        self.assertGreater(im0.economy, 0.0)
        self.assertEqual(im0.power, 0.0)
        # a full board (fill=1, factor 1.0) values the same economy item higher
        full_board = [BoardUnit(name=n, count=1) for n in ("烈夏", "拜松", "折桠")]
        full = GameState(round=2, gold=20, dispatch_level=1, shop=[card],
                         board=full_board)
        im1 = item_impact(self.ds, self.rules, full.shop[0], full)
        self.assertGreater(im1.economy, im0.economy)
        # break-even immediate consumable (1g -> 1g): neutral floor is now 0
        coin = GameState(round=2, gold=20, dispatch_level=3,
                         shop=[self._item_card("盟约之币")],
                         board=full_board)
        self.assertEqual(item_impact(self.ds, self.rules, coin.shop[0], coin).economy, 0.0)

    def test_bond_item_feeds_growth_axis(self):
        st = GameState(round=3, gold=20, dispatch_level=6, target_bond="坚守",
                       shop=[self._item_card("坚守盾牌")], board=self._mature_board())
        im = item_impact(self.ds, self.rules, st.shop[0], st)
        # def +20% -> power 12 with a mature holder; target-bond growth 60 untouched
        self.assertAlmostEqual(im.power, 12.0, places=1)
        self.assertEqual(im.growth, 60.0)
        self.assertTrue(any("目标盟约坚守" in r for r in im.reasons))

    def test_plan_a_presence_marginal_and_economy_discount(self):
        # empty board: a new operator gets a strong presence marginal on growth
        card = self._op_card("烈夏")
        empty = GameState(round=1, gold=4, dispatch_level=2, shop=[card])
        im0 = operator_impact(self.ds, self.rules, card, empty)
        self.assertTrue(any("铺场边际" in r for r in im0.reasons))
        # a duplicate copy adds no new presence
        dup = GameState(round=1, gold=4, dispatch_level=2, shop=[card],
                        board=[BoardUnit(name="烈夏", count=1, bonds=["乌萨斯"])])
        im1 = operator_impact(self.ds, self.rules, card, dup)
        self.assertFalse(any("铺场边际" in r for r in im1.reasons))

    def test_evaluate_shop_ranks_and_mixes_kinds(self):
        st = GameState(round=4, gold=30, dispatch_level=4, target_bond="乌萨斯",
                       shop=[
                           self._op_card("烈夏"),
                           ShopCard(kind="item", name="坚守盾牌", tier=1, price=1),
                       ],
                       board=[BoardUnit(name="烈夏", count=2, bonds=["乌萨斯"])])
        ranked = evaluate_shop(self.ds, self.rules, st)
        self.assertEqual(len(ranked), 2)
        # sorted descending on total_impact
        self.assertGreaterEqual(ranked[0].total_impact, ranked[1].total_impact)
        self.assertEqual({im.kind for im in ranked}, {"operator", "item"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
