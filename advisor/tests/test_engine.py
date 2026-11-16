# -*- coding: utf-8 -*-
"""Stdlib unittest for the rule + decision engine. Run: python -m unittest discover -s tests -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from advisor.data import Dataset
from advisor.engine import (
    Advisor, STAR_TIER_WEIGHT, REFRESH_SOFT_CEILING, REFRESH_CRITICAL_FLOOR,
)
from advisor.model import GameState, ShopCard, BoardUnit


class EngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.adv = Advisor(cls.ds)

    def test_dataset_loaded(self):
        self.assertEqual(self.ds.meta["unique_operators"], 141)
        self.assertEqual(len(self.ds.items), 70)
        self.assertEqual(len(self.ds.bonds["core"]), 10)

    def test_upgrade_price_decay_and_reset(self):
        st = GameState(round=3, gold=10, dispatch_level=1, difficulty="standard")
        self.assertEqual(self.adv.rules.current_upgrade_price(st, 0), 5)
        self.assertEqual(self.adv.rules.current_upgrade_price(st, 3), 2)
        self.assertEqual(self.adv.rules.current_upgrade_price(st, 99), 0)
        maxed = GameState(dispatch_level=6)
        self.assertIsNone(self.adv.rules.current_upgrade_price(maxed, 0))

    def test_tier_gate(self):
        ok = ShopCard(kind="operator", name="真理", tier=2)
        bad = ShopCard(kind="operator", name="塔露拉", tier=6)
        self.assertFalse(self.adv.rules.violates_tier_gate(ok, 3))
        self.assertTrue(self.adv.rules.violates_tier_gate(bad, 3))

    def test_bond_activation(self):
        # three distinct 乌萨斯 operators should activate the bond (need 3)
        st = GameState(board=[
            BoardUnit(name="烈夏", count=1, bonds=["乌萨斯"]),
            BoardUnit(name="真理", count=1, bonds=["乌萨斯"]),
            BoardUnit(name="冻河", count=1, bonds=["乌萨斯"]),
        ])
        status = {b["bond"]: b for b in self.adv.rules.bond_status(st)}
        self.assertIn("乌萨斯", status)
        self.assertTrue(status["乌萨斯"]["active"])
        self.assertEqual(status["乌萨斯"]["have"], 3)

    def test_third_copy_buy_scores_high(self):
        # holding 2 copies, the third copy in shop is the top buy priority
        st = GameState(round=4, gold=8, dispatch_level=2, target_bond="乌萨斯",
                       shop=[
                           ShopCard(kind="operator", name="烈夏", tier=1, price=3),
                           ShopCard(kind="item", name="坚守盾牌", tier=1, price=1),
                       ],
                       board=[BoardUnit(name="烈夏", count=2, bonds=["乌萨斯"])])
        res = self.adv.recommend(st)
        buy = [a for a in res["recommendations"]
               if a["verb"] == "buy" and a["target"] == "烈夏"][0]
        self.assertGreaterEqual(buy["score"], 90)

    def test_merge_ready_is_top_pick(self):
        # once 3 copies are held, the merge callout appears and ranks first
        st = GameState(round=4, gold=8, dispatch_level=2, target_bond="乌萨斯",
                       shop=[ShopCard(kind="item", name="坚守盾牌", tier=1, price=1)],
                       board=[BoardUnit(name="烈夏", count=3, bonds=["乌萨斯"])])
        res = self.adv.recommend(st)
        verbs = {(a["verb"], a["target"]) for a in res["recommendations"]}
        self.assertIn(("merge", "烈夏"), verbs)
        self.assertEqual(res["top_pick"]["verb"], "merge")

    def test_star_is_only_in_tier_micro_adjustment(self):
        # Find a clean in-tier pair whose ONLY scoring difference is star:
        # same shop tier, same number of bonds, same investment-tag count, and
        # neither is the target bond. On an empty board their bond/tier/invest
        # contributions then match, so the exact delta must be the star bonus.
        from advisor.economy import investment_tags
        by_tier = {}
        for o in self.ds.operators:
            by_tier.setdefault(o["shop_tier"], []).append(o)
        pair = None
        for tier, group in by_tier.items():
            def sig(o):
                return (len(o.get("bonds", [])), len(investment_tags(o)))
            s3 = [o for o in group if o["star"] == "3"]
            s5 = [o for o in group if o["star"] == "5"]
            for a in s3:
                for b in s5:
                    if sig(a) == sig(b):
                        pair = (tier, a["name"], b["name"])
                        break
                if pair:
                    break
            if pair:
                break
        self.assertIsNotNone(pair, "need a clean same-tier 3* vs 5* pair")
        tier, n3, n5 = pair
        st = GameState(round=3, gold=40, dispatch_level=tier, shop=[
            ShopCard(kind="operator", name=n3, tier=tier, price=3),
            ShopCard(kind="operator", name=n5, tier=tier, price=3),
        ])
        res = {a["target"]: a for a in self.adv.recommend(st)["recommendations"]
               if a["verb"] == "buy"}
        self.assertEqual(res[n5]["score"] - res[n3]["score"],
                         2 * STAR_TIER_WEIGHT)
        # 3-star never gets a star-bonus reason; 5-star does.
        self.assertNotIn("星底子", res[n3]["reason"])
        self.assertIn("星底子", res[n5]["reason"])

    def test_star_bonus_stays_small_vs_counter(self):
        # A full star spread (2 points) must be dwarfed by a counter hit.
        self.assertLess(2 * STAR_TIER_WEIGHT, 10)

    def test_string_item_price_does_not_crash(self):
        # items.json / OCR may supply price as a string; engine must coerce it
        # instead of crashing on the int-vs-str comparison (regression).
        st = GameState(round=2, gold=5, dispatch_level=2,
                       shop=[ShopCard(kind="item", name="坚守盾牌", tier=1,
                                      price="1")])
        res = self.adv.recommend(st)
        buys = [a for a in res["recommendations"] if a["verb"] == "buy"]
        self.assertTrue(buys)
        self.assertEqual(buys[0]["cost"], 1)
        # the parallel impact breakdown is attached on every buy action
        self.assertIsNotNone(buys[0].get("impact"))

    def test_illegal_card_never_recommended(self):
        st = GameState(round=2, gold=99, dispatch_level=1,
                       shop=[ShopCard(kind="operator", name="塔露拉", tier=6, price=3)])
        res = self.adv.recommend(st)
        bad = [a for a in res["recommendations"] if a["target"] == "塔露拉"]
        self.assertTrue(all(a["score"] < 0 for a in bad))

    # -- Leithanien summon-line integration --
    def test_summon_synergy_inert_without_leithanien_context(self):
        # No target bond and no Leithanien on board -> summon term must not fire.
        st = GameState(round=2, gold=20, dispatch_level=3,
                       shop=[ShopCard(kind="operator", name="地灵", tier=1, price=2)])
        res = self.adv.recommend(st)
        buy = next(a for a in res["recommendations"]
                   if a["verb"] == "buy" and a["target"] == "地灵")
        self.assertNotIn("召唤", buy["reason"])
        self.assertNotIn("小节", buy["reason"])

    def test_summon_synergy_ignores_non_leithanien_card(self):
        # A Leithanien target build must not add summon points to a non-member.
        st = GameState(round=2, gold=20, dispatch_level=3, target_bond="莱塔尼亚",
                       shop=[ShopCard(kind="operator", name="塞雷娅", tier=4, price=3)])
        res = self.adv.recommend(st)
        buy = next(a for a in res["recommendations"]
                   if a["verb"] == "buy" and a["target"] == "塞雷娅")
        self.assertNotIn("小节", buy["reason"])

    def test_summon_activation_scores_third_member(self):
        # Two distinct Leithanien on board; the third member in shop turns on
        # the kill->summon engine and must surface the activation reason.
        st = GameState(round=3, gold=20, dispatch_level=3, target_bond="莱塔尼亚",
                       shop=[ShopCard(kind="operator", name="折光", tier=2, price=3)],
                       board=[
                           BoardUnit(name="地灵", count=1, bonds=["莱塔尼亚"]),
                           BoardUnit(name="复奏", count=1, bonds=["莱塔尼亚"]),
                       ])
        res = self.adv.recommend(st)
        buy = next(a for a in res["recommendations"]
                   if a["verb"] == "buy" and a["target"] == "折光")
        self.assertIn("小节", buy["reason"])
        self.assertIn("激活召唤", buy["reason"])

    def test_summon_synergy_raises_score_inside_build(self):
        # Same card, same shop: a Leithanien build in progress must outscore the
        # no-context baseline by a strictly positive summon contribution.
        card = ShopCard(kind="operator", name="折光", tier=2, price=3)
        base = GameState(round=3, gold=20, dispatch_level=3, shop=[card])
        built = GameState(round=3, gold=20, dispatch_level=3, target_bond="莱塔尼亚",
                          shop=[card],
                          board=[
                              BoardUnit(name="地灵", count=1, bonds=["莱塔尼亚"]),
                              BoardUnit(name="复奏", count=1, bonds=["莱塔尼亚"]),
                          ])
        s_base = next(a for a in self.adv.recommend(base)["recommendations"]
                      if a["verb"] == "buy" and a["target"] == "折光")["score"]
        s_built = next(a for a in self.adv.recommend(built)["recommendations"]
                       if a["verb"] == "buy" and a["target"] == "折光")["score"]
        self.assertGreater(s_built, s_base)

    def test_six_member_milestone_reason(self):
        # Five distinct Leithanien on board; the sixth surfaces the lebu milestone.
        five = ["地灵", "复奏", "折光", "卡涅利安", "车尔尼"]
        st = GameState(round=5, gold=30, dispatch_level=4, target_bond="莱塔尼亚",
                       shop=[ShopCard(kind="operator", name="艾雅法拉", tier=4, price=3)],
                       board=[BoardUnit(name=n, count=1, bonds=["莱塔尼亚"]) for n in five])
        res = self.adv.recommend(st)
        buy = next(a for a in res["recommendations"]
                   if a["verb"] == "buy" and a["target"] == "艾雅法拉")
        self.assertIn("乐部", buy["reason"])
        self.assertIn("6人里程碑", buy["reason"])


    # ---- gate-0 team capability gap integration ----
    def _first_op(self, pred):
        for op in self.ds.operators:
            if pred(op):
                return op["name"]
        raise AssertionError("no operator matched predicate")

    def test_flying_gap_bonus_reaches_recommendation(self):
        ground_board = self._first_op(lambda o: not o.get("anti_air")
                                      and o.get("prof") != "术师")
        aa_card = self._first_op(lambda o: o.get("anti_air"))
        ground_card = self._first_op(lambda o: not o.get("anti_air")
                                     and o.get("prof") != "术师"
                                     and o["name"] != ground_board)
        st = GameState(round=3, gold=50, dispatch_level=6,
                       enemy_types=["flying"],
                       board=[BoardUnit(name=ground_board)],
                       shop=[ShopCard(kind="operator", name=aa_card, tier=2),
                             ShopCard(kind="operator", name=ground_card, tier=2)])
        res = self.adv.recommend(st)
        gap_ids = {g["gap"] for g in res["team_gaps"]}
        self.assertIn("anti_air", gap_ids)
        aa_action = next(a for a in res["recommendations"]
                         if a["verb"] == "buy" and a["target"] == aa_card)
        ground_action = next(a for a in res["recommendations"]
                             if a["verb"] == "buy" and a["target"] == ground_card)
        self.assertIn("补缺", aa_action["reason"])
        self.assertNotIn("补缺", ground_action["reason"])
        # inert without an enemy picture: no gap, no bonus reason
        st_none = GameState(round=3, gold=50, dispatch_level=6,
                            board=[BoardUnit(name=ground_board)],
                            shop=[ShopCard(kind="operator", name=aa_card, tier=2)])
        res_none = self.adv.recommend(st_none)
        self.assertEqual(res_none["team_gaps"], [])
        aa_none = next(a for a in res_none["recommendations"]
                       if a["verb"] == "buy" and a["target"] == aa_card)
        self.assertNotIn("补缺", aa_none["reason"])

    def test_silence_item_gap_bonus_reaches_recommendation(self):
        ground_board = self._first_op(lambda o: "silence" not in (o.get("mechanic_tags") or [])
                                      and not o.get("anti_air"))
        st = GameState(round=4, gold=20, dispatch_level=6,
                       enemy_names=["冰爆源石虫·α"],
                       board=[BoardUnit(name=ground_board)],
                       shop=[ShopCard(kind="item", name="奥术法阵", tier=3, price=1)])
        res = self.adv.recommend(st)
        self.assertIn("silence", {g["gap"] for g in res["team_gaps"]})
        item_action = next(a for a in res["recommendations"]
                           if a["verb"] == "buy" and a["target"] == "奥术法阵")
        self.assertIn("补缺", item_action["reason"])


    # ---- scoring weight direction (2026-11-13) ----
    def test_merge_2to3_still_dominates_soft_combat(self):
        # 2→3 三连 stays high: must beat a soft combat filler with no merge progress
        soft = self._first_op(lambda o: o["name"] != "烈夏"
                              and o.get("shop_tier", 9) <= 2)
        st = GameState(round=4, gold=20, dispatch_level=3, target_bond="乌萨斯",
                       shop=[
                           ShopCard(kind="operator", name="烈夏", tier=1, price=2),
                           ShopCard(kind="operator", name=soft, tier=2, price=3),
                       ],
                       board=[BoardUnit(name="烈夏", count=2, bonds=["乌萨斯"])])
        res = self.adv.recommend(st)
        by = {a["target"]: a for a in res["recommendations"] if a["verb"] == "buy"}
        self.assertGreaterEqual(by["烈夏"]["score"], 90)
        self.assertGreater(by["烈夏"]["score"], by[soft]["score"])
        self.assertEqual(res["top_pick"]["verb"], "buy")
        self.assertEqual(res["top_pick"]["target"], "烈夏")

    def test_refresh_can_beat_noncritical_one_copy_merge(self):
        # Non-critical = 1-copy progress + weak bond-progress only (no bond
        # one-away, no compass carry). Spare gold + mid dispatch EV must let
        # refresh outrank that soft merge.
        name = "拉普兰德"
        op = self.ds.operator(name)
        st = GameState(round=4, gold=12, dispatch_level=3, difficulty="standard",
                       shop=[ShopCard(kind="operator", name=name,
                                      tier=op["shop_tier"], price=3)],
                       board=[BoardUnit(name=name, count=1,
                                        bonds=list(op.get("bonds") or []))])
        res = self.adv.recommend(st)
        buy = next(a for a in res["recommendations"]
                   if a["verb"] == "buy" and a["target"] == name)
        refresh = next(a for a in res["recommendations"] if a["verb"] == "refresh")
        self.assertIn("已有1张", buy["reason"])
        self.assertNotIn("差1人激活", buy["reason"])
        self.assertLessEqual(buy["score"], REFRESH_SOFT_CEILING)
        self.assertGreater(refresh["score"], buy["score"])
        self.assertIn("刷新EV", refresh["reason"])
        self.assertLess(refresh["score"], REFRESH_CRITICAL_FLOOR)

    def test_refresh_loses_to_critical_2to3_merge(self):
        st = GameState(round=4, gold=12, dispatch_level=3, difficulty="standard",
                       shop=[ShopCard(kind="operator", name="烈夏", tier=1, price=2)],
                       board=[BoardUnit(name="烈夏", count=2, bonds=["乌萨斯"])])
        res = self.adv.recommend(st)
        buy = next(a for a in res["recommendations"]
                   if a["verb"] == "buy" and a["target"] == "烈夏")
        refresh = next(a for a in res["recommendations"] if a["verb"] == "refresh")
        self.assertGreaterEqual(buy["score"], 90)
        self.assertGreater(buy["score"], refresh["score"])
        self.assertLess(refresh["score"], REFRESH_CRITICAL_FLOOR)

    # ---- stage-1 clear-margin integration ----
    def test_clear_margin_block_and_damage_steering(self):
        dealer_board = self._first_op(lambda o: o.get("prof") != "医疗")
        dealer_shop = self._first_op(
            lambda o: o.get("prof") != "医疗" and o["name"] != dealer_board)
        healer = self._first_op(lambda o: o.get("prof") == "医疗")
        st = GameState(round=1, gold=50, dispatch_level=6,
                       difficulty="standard", enemy_types=["special"],
                       board=[BoardUnit(name=dealer_board)],
                       shop=[ShopCard(kind="operator", name=dealer_shop, tier=2),
                             ShopCard(kind="operator", name=healer, tier=2)])
        res = self.adv.recommend(st)
        cm_rec = res["clear_margin"]
        self.assertIsNotNone(cm_rec)
        self.assertEqual(cm_rec["band"], "critical")  # single weak dealer leaks
        dealer_action = next(a for a in res["recommendations"]
                             if a["verb"] == "buy" and a["target"] == dealer_shop)
        healer_action = next(a for a in res["recommendations"]
                             if a["verb"] == "buy" and a["target"] == healer)
        self.assertIn("清场吃紧", dealer_action["reason"])
        self.assertNotIn("清场", healer_action["reason"])

    def test_clear_margin_inert_without_enemy_picture(self):
        st = GameState(round=1, gold=50, dispatch_level=6,
                       board=[BoardUnit(name="卡达")],
                       shop=[ShopCard(kind="operator", name="卡达", tier=2)])
        res = self.adv.recommend(st)
        self.assertIsNone(res["clear_margin"])
        buy = next(a for a in res["recommendations"]
                   if a["verb"] == "buy" and a["target"] == "卡达")
        self.assertNotIn("清场", buy["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class BattleSimOutputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        cls.adv = Advisor(cls.ds)

    def _battle_state(self):
        # metric-backed operators across ranged/melee/blocker roles
        return GameState(round=1, regulation_level=1, enemy_types=["special"],
                         board=[BoardUnit(name="陨星"), BoardUnit(name="玛恩纳"),
                                BoardUnit(name="折桠")])

    def test_recommend_includes_inert_battle_sim_block(self):
        res = self.adv.recommend(self._battle_state())
        sim = res.get("battle_sim")
        self.assertIsNotNone(sim)
        # never an error in normal operation; carries a discrete result
        self.assertNotIn("error", sim)
        result = sim["result"]
        self.assertIn(result["reason"], ("cleared", "timeout"))
        self.assertGreaterEqual(result["total"], 1)
        self.assertLessEqual(result["killed"] + result["leaked"], result["total"])
        # one accounting row per board operator
        self.assertEqual(len(sim["allies"]), 3)
        # honest first-cut approximations are surfaced, not hidden
        self.assertTrue(sim["approximations"])

    def test_battle_sim_none_without_board(self):
        st = GameState(round=1, regulation_level=1, enemy_types=["special"])
        res = self.adv.recommend(st)
        self.assertIsNone(res.get("battle_sim"))

    def test_battle_sim_wires_into_clear_margin_reservoir(self):
        # 蓄水池: battle_sim folds into clear_margin via apply_reservoir_pressure
        st = self._battle_state()
        res = self.adv.recommend(st)
        cm_rec = res.get("clear_margin")
        self.assertIsNotNone(cm_rec)
        self.assertIn("margin_paper", cm_rec)
        self.assertIn("reservoir", cm_rec)
        self.assertTrue(cm_rec["reservoir"].get("applied"))
        self.assertIn(cm_rec["band"],
                      ("critical", "tight", "adequate", "comfortable"))
        scores = [(a["verb"], a["target"], a["score"])
                  for a in res["recommendations"]]
        self.assertTrue(scores)
        for _verb, _target, score in scores:
            self.assertIsInstance(score, (int, float))
