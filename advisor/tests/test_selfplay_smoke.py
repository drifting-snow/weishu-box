# -*- coding: utf-8 -*-
"""Smoke tests for self-play scaffold (ASSUMED odds + income)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from advisor import shop_odds
from advisor.data import Dataset
from advisor.selfplay import income as income_mod
from advisor.selfplay.episode import run_episode
from advisor.selfplay.hillclimb import hillclimb_step
from advisor.selfplay.params import apply_params, snapshot_params
from advisor.model import BoardUnit, GameState, ShopCard
from advisor.selfplay.shop_roll import odds_disclaimer, roll_shop


class ShopOddsAssumedTest(unittest.TestCase):
    def test_tier_probs_assumed_guicheng(self):
        doc = shop_odds.load_shop_roll_odds()
        self.assertTrue(doc.get("assumed"))
        self.assertFalse(doc.get("official"))
        probs = shop_odds.tier_probs(3, season="guicheng")
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=2)
        self.assertIn("ASSUMED", odds_disclaimer())


class ShopRollTest(unittest.TestCase):
    def test_roll_shop_length_matches_slots(self):
        import random
        ds = Dataset()
        cards = roll_shop(ds, 2, "standard", rng=random.Random(0),
                          include_items=False)
        self.assertEqual(len(cards), int(ds.slots(2, "standard")))
        self.assertTrue(all(c.kind == "operator" and c.name for c in cards))

    def test_assumed_item_mix_can_roll_items(self):
        import random
        from advisor.selfplay.shop_roll import item_slot_rate
        ds = Dataset()
        self.assertGreater(item_slot_rate(), 0)
        # Force items with a high rate via odds_doc override.
        doc = shop_odds.load_shop_roll_odds()
        forced = dict(doc)
        forced["item_mix"] = {
            "assumed": True, "official": False,
            "per_slot_item_rate": 1.0,
            "within_item_model": "uniform_all_items",
        }
        cards = roll_shop(ds, 3, "standard", rng=random.Random(1),
                          odds_doc=forced)
        self.assertTrue(cards)
        self.assertTrue(any(c.kind == "item" for c in cards))
        self.assertIn("item_mix", odds_disclaimer().lower())


class FreezePersistTest(unittest.TestCase):
    def test_freeze_carries_shop_into_next_rest(self):
        from advisor.selfplay import episode as ep
        import random
        ds = Dataset()
        st = GameState(
            round=1, gold=4, dispatch_level=1, difficulty="standard",
            board=[BoardUnit(name=ds.operators[0]["name"])],
            shop=[ShopCard(kind="operator", name="冻结牌A", tier=1, price=2),
                  ShopCard(kind="operator", name="冻结牌B", tier=1, price=2)],
            frozen=True,
        )
        meta = ep._rest_start_shop(ds, st, season="guicheng",
                                   rng=random.Random(0))
        self.assertTrue(meta["shop_carry_frozen"])
        self.assertGreaterEqual(meta["frozen_kept"], 2)
        self.assertEqual(st.shop[0].name, "冻结牌A")
        self.assertFalse(st.frozen)  # one-round lock consumed

    def test_freeze_action_sets_flag(self):
        from advisor.selfplay import episode as ep
        import random
        ds = Dataset()
        st = GameState(round=1, gold=4, dispatch_level=1, shop=[], board=[])
        verb = ep._apply_top(
            ds, st,
            {"recommendations": [{"verb": "freeze", "target": "x", "cost": 0}]},
            random.Random(0), "guicheng")
        self.assertEqual(verb, "freeze")
        self.assertTrue(st.frozen)

    def test_buy_item_uses_item_path(self):
        from advisor.selfplay import episode as ep
        import random
        ds = Dataset()
        item = ds.items[0]
        carrier = ds.operators[0]["name"]
        st = GameState(
            round=1, gold=20, dispatch_level=3,
            board=[BoardUnit(name=carrier)],
            shop=[ShopCard(kind="item", name=item["name"],
                           tier=int(item.get("tier") or 1),
                           price=int(item.get("price") or 1))],
            equipment={},
        )
        verb = ep._apply_top(
            ds, st,
            {"recommendations": [{
                "verb": "buy", "target": item["name"],
                "cost": int(item.get("price") or 1),
            }]},
            random.Random(0), "guicheng")
        self.assertEqual(verb, "buy_item")
        self.assertIn(item["name"], st.equipment.get(carrier) or [])
        self.assertEqual(st.shop, [])

    def test_sell_returns_default_gold(self):
        from advisor.selfplay import episode as ep
        import random
        ds = Dataset()
        name = ds.operators[0]["name"]
        st = GameState(
            round=1, gold=0, dispatch_level=1,
            board=[BoardUnit(name=name), BoardUnit(name=ds.operators[1]["name"])],
            shop=[],
        )
        verb = ep._apply_top(
            ds, st,
            {"recommendations": [{"verb": "sell", "target": name, "cost": 0}]},
            random.Random(0), "guicheng")
        self.assertEqual(verb, "sell")
        self.assertGreaterEqual(st.gold, 1)
        self.assertEqual(len(st.board), 1)


class IncomeAssumedTest(unittest.TestCase):
    def test_income_marked_assumed_formula(self):
        # Community ASSUMED: min(3+r, 12); R1–R3 verified 4/5/6.
        doc = income_mod.load_gold_income()
        self.assertTrue(doc.get("assumed"))
        self.assertFalse(doc.get("official"))
        self.assertEqual(doc.get("income_cap"), 12)
        self.assertIn("ASSUMED", income_mod.ASSUMED_INCOME_NOTE)
        self.assertEqual(income_mod.gold_for_round(1), 4)
        self.assertEqual(income_mod.gold_for_round(2), 5)
        self.assertEqual(income_mod.gold_for_round(3), 6)
        self.assertEqual(income_mod.gold_for_round(9), 12)
        self.assertEqual(income_mod.gold_for_round(15), 12)
        self.assertEqual(income_mod.gold_for_round(1, flat=7), 7)
        table = income_mod.table_for_mode(doc)
        for r in range(1, 16):
            self.assertEqual(table[r], income_mod.income_formula(r, doc))

    def test_episode_clears_unspent_each_rest(self):
        out = run_episode(seed=0, max_rounds=3, actions_per_round=2,
                          use_battle=False)
        self.assertTrue(out["log"])
        for i, row in enumerate(out["log"]):
            self.assertEqual(row["gold_granted"], income_mod.gold_for_round(i + 1))
            self.assertTrue(row["gold_unspent_cleared"])
            self.assertFalse(row["gold_interest"])
            self.assertTrue(row["gold_assumed"])


class EpisodeSmokeTest(unittest.TestCase):
    def test_episode_returns_max_round(self):
        # Keep cheap: few rounds; battle may be slow but one/two waves OK.
        out = run_episode(seed=1, max_rounds=2, actions_per_round=4,
                          regulation_level=1, use_battle=True)
        self.assertIn("max_round_cleared", out)
        self.assertGreaterEqual(out["max_round_cleared"], 0)
        self.assertIn("assumed", out["shop_odds"].lower())
        self.assertTrue(out["log"])


class ParamsAndHillclimbSmokeTest(unittest.TestCase):
    def test_apply_restore_invest_weight(self):
        from advisor import economy
        before = economy.INVEST_WEIGHT["free_refresh"]
        prev = apply_params({"invest.free_refresh": before + 2})
        self.assertEqual(economy.INVEST_WEIGHT["free_refresh"], before + 2)
        apply_params(prev)
        self.assertEqual(economy.INVEST_WEIGHT["free_refresh"], before)

    def test_hillclimb_step_runs(self):
        # Short seed sweep (suite=None): 1 episode × 2 rounds × base+cand
        out = hillclimb_step(
            episodes=1, seed0=2, max_rounds=2,
            param_key="gap.cap",
            suite=None,
        )
        self.assertEqual(out["param"], "gap.cap")
        self.assertIn("improved", out)
        self.assertIn("mean_max_round", out["base"])
        self.assertIn("fitness", out["base"])


class ObjectiveAndEvalHarnessTest(unittest.TestCase):
    def test_score_episode_penalizes_leaks(self):
        from advisor.selfplay.objective import score_episode
        clean = score_episode({
            "max_round_cleared": 2,
            "log": [
                {"ok": True, "leaked": 0, "gold_end": 0},
                {"ok": True, "leaked": 0, "gold_end": 1},
            ],
        })
        leaky = score_episode({
            "max_round_cleared": 2,
            "log": [
                {"ok": True, "leaked": 0, "gold_end": 0},
                {"ok": False, "leaked": 5, "gold_end": 0},
            ],
        })
        self.assertGreater(clean["fitness"], leaky["fitness"])
        self.assertEqual(clean["max_round_cleared"], 2)

    def test_eval_cards_suite_smoke_runs(self):
        from advisor.selfplay.eval_harness import evaluate_on_cards, list_cards
        cards = list_cards(suite="smoke")
        self.assertGreaterEqual(len(cards), 2)
        # Run only first two cards for CI speed.
        out = evaluate_on_cards(cards=cards[:2])
        self.assertIn("fitness", out)
        self.assertIn("mean_max_round", out)
        self.assertEqual(out["n"], 2)
        self.assertTrue(out.get("assumed_env"))
        self.assertEqual(len(out["cards"]), 2)

    def test_aggregate_variance_penalty(self):
        from advisor.selfplay.objective import aggregate_scores, better
        stable = aggregate_scores([
            {"fitness": 10, "max_round_cleared": 1, "total_leaked": 0},
            {"fitness": 10, "max_round_cleared": 1, "total_leaked": 0},
        ], variance_weight=0.35)
        noisy = aggregate_scores([
            {"fitness": 20, "max_round_cleared": 2, "total_leaked": 0},
            {"fitness": 0, "max_round_cleared": 0, "total_leaked": 0},
        ], variance_weight=0.35)
        self.assertEqual(stable["mean_fitness"], 10.0)
        self.assertGreater(noisy["std_fitness"], stable["std_fitness"])
        # Same mean (10) but noisy has std>0 → lower fitness after penalty.
        self.assertGreater(stable["fitness"], noisy["fitness"])
        self.assertTrue(better(stable, noisy))


if __name__ == "__main__":
    unittest.main(verbosity=2)
