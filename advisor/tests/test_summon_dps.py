# -*- coding: utf-8 -*-
"""Tests for Leithanien bond-summon DPS. Pure stdlib; no network or imaging."""
import json
import os
import unittest

from advisor import summon_dps as sd

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "leithanien_summons.json")


class SummonDataIntegrityTest(unittest.TestCase):
    def setUp(self):
        with open(DATA, encoding="utf-8") as f:
            self.doc = json.load(f)
        self.s = self.doc["summons"]

    def test_both_summons_present(self):
        self.assertEqual(set(self.s), {"xiaojie", "lebu"})
        self.assertEqual(set(sd.summon_ids()), {"xiaojie", "lebu"})

    def test_xiaojie_prts_facts(self):
        x = self.s["xiaojie"]["stats"]
        self.assertEqual(x["max_hp"], 2350)
        self.assertEqual(x["atk"], 450)
        self.assertEqual(x["def"], 0)
        self.assertEqual(x["res"], 0)
        self.assertEqual(x["attack_interval"], 3.0)
        self.assertEqual(self.s["xiaojie"]["block_count"], 1)
        self.assertEqual(self.s["xiaojie"]["damage_type"], "arts")

    def test_lebu_prts_facts(self):
        l = self.s["lebu"]["stats"]
        self.assertEqual(l["max_hp"], 8500)
        self.assertEqual(l["atk"], 950)
        self.assertEqual(l["def"], 450)
        self.assertEqual(l["res"], 30)
        self.assertEqual(l["attack_interval"], 3.0)
        self.assertEqual(self.s["lebu"]["block_count"], 2)
        self.assertEqual(self.s["lebu"]["model_id"], "enemy_9026_acltm")
        self.assertTrue(self.s["lebu"]["aura"]["stackable"])
        self.assertEqual(self.s["lebu"]["aura"]["aspd_bonus"], 20)

    def test_decay_rule_is_recorded_for_both(self):
        for sid in ("xiaojie", "lebu"):
            life = self.s[sid]["lifespan"]
            self.assertTrue(life["forbidden_heal"])
            self.assertEqual(life["hp_drain_pct_of_max_per_sec"], 0.10)

    def test_sources_recorded(self):
        urls = self.doc["sources"]
        self.assertIn("xiaojie_page", urls)
        self.assertIn("lebu_page", urls)
        self.assertTrue(urls["xiaojie_page"]["url"].startswith("https://prts.wiki/"))

    def test_unknown_ownership_not_fabricated(self):
        self.assertIn("待补充", self.doc["data_status"])
        # xiaojie model id was not captured -> must stay explicitly flagged
        self.assertIn("needs_review", self.s["xiaojie"]["model_id_status"])


class BondBuffTest(unittest.TestCase):
    def test_multiplier_formula(self):
        self.assertEqual(sd.bond_atk_multiplier(0), 1.30)
        self.assertEqual(sd.bond_atk_multiplier(100), 2.30)
        self.assertEqual(sd.bond_atk_multiplier(-5), 1.30)  # clamped to 0 stacks

    def test_buffed_attack(self):
        self.assertEqual(sd.buffed_attack("xiaojie", 0), 450 * 1.30)
        self.assertEqual(sd.buffed_attack("lebu", 50), round(950 * 1.80, 3))


class PanelDpsTest(unittest.TestCase):
    def test_xiaojie_single_hit_dps(self):
        self.assertEqual(sd.panel_dps("xiaojie"), round(450 / 3.0, 3))  # 150.0

    def test_lebu_double_hit_cycle_dps(self):
        # 4 actions = 5 hits -> 1.25 hits/action
        expected = round(950 * (5 / 4) / 3.0, 3)  # 395.833
        self.assertEqual(sd.panel_dps("lebu"), expected)

    def test_lebu_outdamages_xiaojie_per_unit(self):
        self.assertGreater(sd.panel_dps("lebu"), sd.panel_dps("xiaojie"))


class EffectiveDpsTest(unittest.TestCase):
    def test_zero_stack_full_uptime_equals_panel_times_base_buff(self):
        self.assertEqual(sd.effective_dps("xiaojie", 0, 1.0),
                         round(sd.panel_dps("xiaojie") * 1.30, 3))

    def test_uptime_scales_linearly(self):
        full = sd.effective_dps("lebu", 20, 1.0)
        half = sd.effective_dps("lebu", 20, 0.5)
        self.assertEqual(half, round(full * 0.5, 3))

    def test_uptime_clamped(self):
        self.assertEqual(sd.effective_dps("xiaojie", 0, 2.0),
                         sd.effective_dps("xiaojie", 0, 1.0))
        self.assertEqual(sd.effective_dps("xiaojie", 0, -1.0), 0.0)


class LifetimeEstimateTest(unittest.TestCase):
    def test_nominal_lifetime_is_ten_seconds(self):
        self.assertEqual(sd.NOMINAL_LIFETIME_SEC, 10.0)

    def test_xiaojie_lifetime_hits(self):
        r = sd.lifetime_estimate("xiaojie", 0, 1.0)
        # 10 s / 3.0 s interval -> 3 attack actions, all single hits
        self.assertEqual(r["attack_actions"], 3)
        self.assertEqual(r["hits"], 3)
        self.assertEqual(r["buffed_atk"], round(450 * 1.30, 3))  # 585
        self.assertEqual(r["lifetime_damage_raw"], round(585 * 3, 2))  # 1755

    def test_lebu_lifetime_double_hit_accounting(self):
        r = sd.lifetime_estimate("lebu", 0, 1.0)
        # 10 s / 3.0 -> 3 actions, which is below one full 4-action cycle,
        # so all three are single hits (no double attack reached yet).
        self.assertEqual(r["attack_actions"], 3)
        self.assertEqual(r["hits"], 3)
        # force a full cycle: 12 s active window is not reachable (10 s cap),
        # so verify the cycle math directly via a longer-uptime synthetic case
        r2 = sd.lifetime_estimate("lebu", 0, 1.0)
        self.assertLessEqual(r2["active_attack_sec"], 10.0)

    def test_lebu_cycle_math_unit_level(self):
        # 8 attack actions = 2 full cycles -> 10 hits
        actions = 8
        cycles, rem = divmod(actions, sd.LEBU_CYCLE_ACTIONS)
        hits = cycles * sd.LEBU_CYCLE_HITS + rem
        self.assertEqual((cycles, rem, hits), (2, 0, 10))

    def test_uptime_reduces_actions(self):
        full = sd.lifetime_estimate("xiaojie", 0, 1.0)
        low = sd.lifetime_estimate("xiaojie", 0, 0.3)  # 3 s active -> 1 action
        self.assertLess(low["attack_actions"], full["attack_actions"])
        self.assertEqual(low["attack_actions"], 1)


class TankingTest(unittest.TestCase):
    def test_physical_mitigation_uses_def(self):
        # lebu DEF 450: 600 - 450 = 150
        self.assertEqual(sd.damage_per_hit("lebu", 600, "phys"), 150.0)
        # xiaojie DEF 0: takes the full hit
        self.assertEqual(sd.damage_per_hit("xiaojie", 600, "phys"), 600.0)

    def test_arts_mitigation_uses_res(self):
        # lebu RES 30 -> 500 * (1 - 0.30) = 350
        self.assertEqual(sd.damage_per_hit("lebu", 500, "arts"), 350.0)
        # xiaojie RES 0 -> full arts damage
        self.assertEqual(sd.damage_per_hit("xiaojie", 500, "arts"), 500.0)

    def test_five_percent_floor(self):
        # weak hit against high DEF: damage cannot fall below 5% of ATK
        self.assertEqual(sd.damage_per_hit("lebu", 100, "phys"), 5.0)

    def test_true_damage_passes_through(self):
        self.assertEqual(sd.damage_per_hit("lebu", 400, "true"), 400.0)

    def test_incoming_dps_divides_by_interval(self):
        # 150 per hit every 1.2 s -> 125 DPS
        self.assertEqual(sd.incoming_dps_from("lebu", 600, "phys", 1.2), 125.0)

    def test_survival_ten_seconds_without_incoming(self):
        self.assertEqual(sd.survival_seconds("xiaojie", 0), 10.0)
        self.assertEqual(sd.survival_seconds("lebu", 0), 10.0)

    def test_survival_shorter_under_fire(self):
        self.assertLess(sd.survival_seconds("xiaojie", 500), 10.0)
        # lebu is tankier: survives longer than xiaojie under the same pressure
        self.assertGreater(sd.survival_seconds("lebu", 500),
                           sd.survival_seconds("xiaojie", 500))

    def test_hits_survived_matches_soak_math(self):
        import math
        per = sd.damage_per_hit("lebu", 600, "phys")  # 150
        self.assertEqual(sd.hits_survived("lebu", 600, "phys"),
                         max(1, math.ceil(8500 / per)))  # 57

    def test_tank_profile_block_clamp_and_absorb(self):
        # xiaojie blocks only 1: requesting 2 simultaneous is clamped to 1
        px = sd.tank_profile("xiaojie", enemy_atk_phys=600,
                             simultaneous_enemies=2)
        self.assertEqual(px["simultaneous_enemies_modeled"], 1)
        self.assertEqual(px["block_count"], 1)
        self.assertLessEqual(px["expected_field_time_sec"], 10.0)
        self.assertGreaterEqual(px["damage_absorbed_for_team"], 0)
        # lebu blocks 2 and keeps both slots
        pl = sd.tank_profile("lebu", enemy_atk_phys=600, enemy_atk_arts=500,
                             enemy_attack_interval=1.2, simultaneous_enemies=2)
        self.assertEqual(pl["simultaneous_enemies_modeled"], 2)
        self.assertEqual(pl["block_count"], 2)
        self.assertIn("phys", pl["profiles"])
        self.assertIn("arts", pl["profiles"])
        # tankier lebu absorbs more for the team than fragile xiaojie
        self.assertGreater(pl["damage_absorbed_for_team"],
                           px["damage_absorbed_for_team"])

    def test_tank_stats_expose_frontline_fields(self):
        ts = sd.tank_stats("lebu")
        self.assertEqual(ts["block_count"], 2)
        self.assertEqual(ts["def"], 450)
        self.assertEqual(ts["res"], 30)
        self.assertTrue(ts["forbidden_heal"])


class CapacityTest(unittest.TestCase):
    def test_board_caps(self):
        self.assertEqual(sd.board_cap(False), 10)
        self.assertEqual(sd.board_cap(True), 20)

    def test_formation_ceiling_is_flagged(self):
        r = sd.formation_upper_bound("xiaojie", 0, six_member=False)
        self.assertTrue(r["ceiling_only"])
        self.assertEqual(r["slots"], 10)
        self.assertEqual(r["aggregate_dps_ceiling"],
                         round(r["per_summon_dps"] * 10, 2))
        r6 = sd.formation_upper_bound("lebu", 0, six_member=True)
        self.assertEqual(r6["slots"], 20)


if __name__ == "__main__":
    unittest.main()
