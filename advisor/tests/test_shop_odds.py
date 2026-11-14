# -*- coding: utf-8 -*-
"""Minimal tests for ASSUMED shop roll odds loader (no scoring hookup)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from advisor import shop_odds as so  # noqa: E402


class ShopRollOddsTest(unittest.TestCase):
    def setUp(self):
        so.clear_shop_roll_odds_cache()

    def test_doc_marked_assumed_non_official(self):
        doc = so.load_shop_roll_odds()
        self.assertTrue(doc["assumed"])
        self.assertFalse(doc["official"])
        self.assertEqual(doc["unit"], "fraction")
        self.assertEqual(doc["pool_stock_per_operator"], [12, 14, 18, 16, 8, 5])

    def test_lv1_is_100_percent_tier1(self):
        for season in ("guicheng", "mengyue"):
            probs = so.tier_probs(1, season=season)
            self.assertEqual(set(probs.keys()), {"1"})
            self.assertAlmostEqual(probs["1"], 1.0, places=9)

    def test_lv6_has_six_keys_summing_to_one(self):
        for season in ("guicheng", "mengyue"):
            probs = so.tier_probs(6, season=season)
            self.assertEqual(set(probs.keys()),
                             {"1", "2", "3", "4", "5", "6"})
            self.assertAlmostEqual(sum(probs.values()), 1.0, places=2)

    def test_default_season_is_guicheng(self):
        self.assertEqual(so.tier_probs(2), so.tier_probs(2, season="guicheng"))
        self.assertNotEqual(so.tier_probs(2, season="guicheng"),
                            so.tier_probs(2, season="mengyue"))

    def test_bad_season_raises(self):
        with self.assertRaises(ValueError):
            so.tier_probs(1, season="unknown")


if __name__ == "__main__":
    unittest.main()
