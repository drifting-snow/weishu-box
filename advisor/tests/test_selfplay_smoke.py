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
        cards = roll_shop(ds, 2, "standard", rng=random.Random(0))
        self.assertEqual(len(cards), int(ds.slots(2, "standard")))
        self.assertTrue(all(c.kind == "operator" and c.name for c in cards))


class IncomeAssumedTest(unittest.TestCase):
    def test_income_marked_assumed(self):
        self.assertIn("ASSUMED", income_mod.ASSUMED_INCOME_NOTE)
        self.assertEqual(income_mod.gold_for_round(1), 10)
        self.assertEqual(income_mod.gold_for_round(1, flat=7), 7)


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
        # Short: 1 episode × 2 rounds × base+cand = 4 tiny episodes
        out = hillclimb_step(
            episodes=1, seed0=2, max_rounds=2,
            param_key="gap.cap",
        )
        self.assertEqual(out["param"], "gap.cap")
        self.assertIn("improved", out)
        self.assertIn("mean_max_round", out["base"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
