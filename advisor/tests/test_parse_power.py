# -*- coding: utf-8 -*-
"""Stdlib unittest for tools/parse_power.py (base stats + buff tiers).

Run: python -m unittest discover -s tests -v
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DATA = os.path.join(ROOT, "data", "operator_power.json")
VALID_TIERS = {None, "S", "A", "B", "C"}


class ParsePowerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DATA, encoding="utf-8") as f:
            cls.doc = json.load(f)
        cls.by_name = {r["name"]: r for r in cls.doc["operators"]}

    def test_all_141_operators_covered(self):
        self.assertEqual(self.doc["_meta"]["operator_count"], 141)
        self.assertEqual(len(self.doc["operators"]), 141)
        self.assertEqual(self.doc["_meta"]["missing_wiki"], [])

    def test_precise_base_stats_match_manual_math(self):
        # 蓝毒: (atk 535 + trust 75) / interval 1.0s = 610.0
        blue = self.by_name["蓝毒"]["base"]
        self.assertEqual(blue["atk_with_trust"], 610)
        self.assertEqual(blue["interval"], 1.0)
        self.assertEqual(blue["base_dps"], 610.0)
        self.assertEqual(blue["elite_cap"], "精英2")
        # 史尔特尔: (672 + 100) / 1.25 = 617.6
        surt = self.by_name["史尔特尔"]["base"]
        self.assertAlmostEqual(surt["base_dps"], 617.6, places=1)
        # a tank: low dps, large hp pool and block 3
        bison = self.by_name["拜松"]["base"]
        self.assertLess(bison["base_dps"], 320)
        self.assertGreater(bison["hp"], 3000)
        self.assertEqual(bison["block"], 3)

    def test_all_operators_use_elite2_block(self):
        # In 卫戍协议 even 3-star operators carry a valid elite-2 stat block in
        # the source data (unlike base Arknights where 3-star caps at elite-1).
        # Verify against real data rather than assume the base-game rule.
        star3 = [r for r in self.doc["operators"] if str(r["star"]) == "3"]
        self.assertTrue(star3)
        for r in self.doc["operators"]:
            self.assertEqual(r["base"]["elite_cap"], "精英2", r["name"])
        # a concrete 3-star still has sane non-empty elite-2 stats
        kada = self.by_name["卡达"]["base"]
        self.assertEqual(kada["elite_cap"], "精英2")
        self.assertGreater(kada["atk"], 0)
        self.assertIsNotNone(kada["base_dps"])

    def test_tiers_valid_and_external_distinct_from_self(self):
        for r in self.doc["operators"]:
            self.assertIn(r["buff_self"]["tier"], VALID_TIERS, r["name"])
            self.assertIn(r["buff_external"]["tier"], VALID_TIERS, r["name"])
        # the two dimensions can disagree (white value vs skill burst)
        any_disagree = any(
            r["buff_self"]["tier"] != r["buff_external"]["tier"]
            for r in self.doc["operators"])
        self.assertTrue(any_disagree)

    def test_mlynar_recovered_multi_target_and_combo(self):
        # word-order variants that initially slipped through regex
        m = self.by_name["玛恩纳"]["buff_self"]
        self.assertEqual(m["max_atk_mult"], 2.0)
        self.assertEqual(m["max_targets"], 5)
        self.assertEqual(m["extra_hits"], 1)

    def test_none_self_tier_are_non_damage_classes(self):
        none_self = [r for r in self.doc["operators"]
                     if r["buff_self"]["tier"] is None]
        # all should be tank / medic / support-style, not 近卫/狙击/术师 DPS
        for r in none_self:
            self.assertNotIn(r["prof"], ("近卫", "狙击", "术师"), r["name"])
        # spot-check known special-mechanic supports
        self.assertIn("浊心斯卡蒂", [r["name"] for r in none_self])
        self.assertIn("拜松", [r["name"] for r in none_self])

    def test_external_tier_tracks_base_dps_percentile(self):
        # the highest white-value DPS operators must land in external S tier
        top = sorted(self.doc["operators"],
                     key=lambda r: -(r["base"]["base_dps"] or 0))[:5]
        for r in top:
            self.assertEqual(r["buff_external"]["tier"], "S", r["name"])

    def test_no_mastery_leak_skills_capped_at_rank7(self):
        # The mode never enables mastery (M1/M2/M3); skill_dps must only carry
        # the base skills (max 3) read from 技能7 rows, never 技能专精 rows.
        for r in self.doc["operators"]:
            self.assertLessEqual(len(r["skill_dps"]), 3, r["name"])
            for s in r["skill_dps"]:
                # every parsed skill is a real named base skill, not a mastery row
                self.assertTrue(s["skill"] and "专精" not in s["skill"])
        # concrete spot check: Surtr has exactly 3 base skills incl. 黄昏
        surt = self.by_name["史尔特尔"]
        names = [s["skill"] for s in surt["skill_dps"]]
        self.assertEqual(names, ["烈焰魔剑", "熔核巨影", "黄昏"])

    def test_mode_level_fixity_matches_in_game_table(self):
        # user-verified in-game table: t1/t2 initial = elite1, t3+ = elite2;
        # skill rank 4 initial / 7 elite; t6 elite module level 3.
        def ml(name):
            return self.by_name[name]["mode_level"]
        # tier-1 4-star initial is elite-1 Lv55
        lixia = ml("烈夏")
        self.assertEqual(lixia["initial"]["phase"], 1)
        self.assertEqual(lixia["initial"]["level"], 55)
        self.assertEqual(lixia["initial"]["skill_rank"], 4)
        self.assertEqual(lixia["elite"]["phase"], 2)
        self.assertEqual(lixia["elite"]["level"], 50)
        self.assertEqual(lixia["elite"]["skill_rank"], 7)
        # tier-3+ initial flips to elite-2 Lv1
        kada = ml("卡达")  # shop tier 1 -> still elite1 initial
        self.assertEqual(kada["initial"]["phase"], 1)
        surt = ml("史尔特尔")  # tier 6
        self.assertEqual(surt["initial"]["phase"], 2)
        self.assertEqual(surt["initial"]["level"], 1)
        self.assertEqual(surt["elite"]["level"], 60)
        self.assertEqual(surt["elite"]["module"], 3)
        # every operator carries an honest anchor bias note
        for r in self.doc["operators"]:
            self.assertIn("anchor", r["mode_level"]["initial"])
            self.assertTrue(r["mode_level"]["initial"]["anchor"]["bias"])

    def test_skill_dps_single_vs_aoe_split(self):
        # 熔核巨影 (Surtr skill 2): multiplier 1.8, targets 2, duration 17.
        surt = self.by_name["史尔特尔"]
        sustained = {s["skill"]: s for s in surt["skill_dps"]
                     if s["skill_mode"] == "sustained"}
        s2 = sustained["熔核巨影"]
        self.assertIsNotNone(s2["single_dps"])
        self.assertEqual(s2["targets"], 2)
        # AoE theoretical = single * distinct targets (full-target assumption)
        self.assertAlmostEqual(s2["aoe_dps"], s2["single_dps"] * 2, places=1)

    def test_instant_and_infinite_skills_have_no_sustained_dps(self):
        surt = self.by_name["史尔特尔"]
        modes = {s["skill"]: s for s in surt["skill_dps"]}
        # 黄昏 is a manual toggle with no fixed duration -> not a sustained DPS
        self.assertIsNone(modes["黄昏"]["single_dps"])
        self.assertIn(modes["黄昏"]["skill_mode"], ("infinite_or_special",))
        # 烈焰魔剑 is a next-attack instant skill
        self.assertIsNone(modes["烈焰魔剑"]["single_dps"])
        self.assertEqual(modes["烈焰魔剑"]["skill_mode"], "instant_next_attack")

    def test_mlynar_aoe_skill_targets_five(self):
        m = self.by_name["玛恩纳"]
        glory = next(s for s in m["skill_dps"] if s["skill"] == "未照耀的荣光")
        self.assertEqual(glory["targets"], 5)
        self.assertAlmostEqual(glory["aoe_dps"], glory["single_dps"] * 5, places=1)

    def test_best_skill_dps_helper_and_review_scope(self):
        # 109 of 141 operators have at least one sustained skill DPS
        have = [r for r in self.doc["operators"]
                if r["best_skill_dps"]["single"] is not None]
        self.assertGreater(len(have), 100)
        # needs_review now only flags summon/liberation mechanics, not no-duration
        review = [r for r in self.doc["operators"] if r["needs_review"]]
        self.assertLessEqual(len(review), 20)
        for r in review:
            self.assertTrue(any("召唤" in m or "特性" in m for m in r["needs_review"]))

    def test_self_burst_top_is_strong_amplifier(self):
        rated = [r for r in self.doc["operators"]
                 if r["buff_self"]["max_atk_mult"]]
        top = max(rated, key=lambda r: r["buff_self"]["max_atk_mult"])
        self.assertGreaterEqual(top["buff_self"]["max_atk_mult"], 4.0)
        self.assertEqual(top["buff_self"]["tier"], "S")


if __name__ == "__main__":
    unittest.main(verbosity=2)
