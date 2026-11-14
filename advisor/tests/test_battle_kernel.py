# -*- coding: utf-8 -*-
"""Tests for the clean-room battle kernel (advisor/battle/).

These pin the methodology re-implemented from the Stronghold reference using
public game mechanics; no GPL source is imported by the code under test.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from advisor.battle.clock import Clock
from advisor.battle.constants import TICK
from advisor.battle.unit import Unit, BaseStats
from advisor.battle import damage, blocking
from advisor.battle.wave import (
    WaveScheduler, SpawnSpec, ReservoirPressure, travel_seconds,
)
from advisor.battle.battle import Battle


def make_ally(uid="a", **base):
    return Unit(uid, uid, "ally", "op", BaseStats(**base))


def make_enemy(uid="e", hp=1000.0, **base):
    base.setdefault("max_hp", hp)
    u = Unit(uid, uid, "enemy", "enemy", BaseStats(**base))
    u.deployed = True
    return u


class ClockTest(unittest.TestCase):
    def test_time_derived_from_tick_count(self):
        c = Clock()
        self.assertEqual(c.time, 0.0)
        c.advance()
        self.assertAlmostEqual(c.time, TICK)
        for _ in range(29):
            c.advance()
        self.assertAlmostEqual(c.time, 1.0)  # 30 ticks = 1s, no drift

    def test_seconds_to_ticks(self):
        c = Clock()
        self.assertEqual(c.seconds_to_ticks(1.0), 30)


class StatAggregationTest(unittest.TestCase):
    def test_base_interval_uses_bat_and_aspd(self):
        u = make_ally(base_bat=2.9)
        self.assertAlmostEqual(u.stats.interval, 2.9)

    def test_dusk_s3_bat_flat_is_absolute_not_multiplicative(self):
        # Hard bug #2: base_attack_time +0.40 shifts BAT, giving 3.30s,
        # never the old interval*1.4 = 4.06s over-estimate.
        u = make_ally(base_bat=2.9)
        u.add_bat_flat(0.40)
        self.assertAlmostEqual(u.stats.interval, 3.30, places=6)

    def test_bat_pct_is_a_distinct_channel(self):
        u = make_ally(base_bat=2.9)
        u.add_bat_pct(0.40)
        self.assertAlmostEqual(u.stats.interval, 2.9 * 1.4, places=6)

    def test_aspd_clamps_to_allowed_band(self):
        slow = make_ally(base_bat=1.0)
        slow.add_aspd(-1000)  # floor 20 -> interval = 1*100/20 = 5
        self.assertEqual(slow.stats.aspd, 20.0)
        self.assertAlmostEqual(slow.stats.interval, 5.0)
        fast = make_ally(base_bat=1.0)
        fast.add_aspd(10000)  # cap 600
        self.assertEqual(fast.stats.aspd, 600.0)

    def test_atk_pct_sums_but_mul_compounds(self):
        u = make_ally(atk=100.0)
        u.add_atk_pct(0.50)
        u.add_atk_pct(0.20)  # summed -> +70% once
        self.assertAlmostEqual(u.stats.atk, 170.0)
        u2 = make_ally(atk=100.0)
        u2.add_atk_mul(1.5)
        u2.add_atk_mul(1.5)  # compounds -> 225
        self.assertAlmostEqual(u2.stats.atk, 225.0)

    def test_atk_flat_then_pct_then_final_ordering(self):
        u = make_ally(atk=100.0)
        u.add_atk_flat(50.0)
        u.add_atk_pct(0.10)
        # (100+50)*1.1 = 165
        self.assertAlmostEqual(u.stats.atk, 165.0)

    def test_res_clamped_to_cap(self):
        u = make_enemy(res=200.0)
        self.assertEqual(u.stats.res, 95.0)


class DamageTrunkTest(unittest.TestCase):
    def test_physical_uses_defense_and_floor(self):
        src = make_ally(atk=881.0)
        t = make_enemy(defense=800.0)
        dmg = damage.deal_hit(src, t, 881.0, damage.PHYS)
        # max(881-800, 0.05*881=44.05) = 81
        self.assertAlmostEqual(dmg, 81.0)

    def test_physical_floor_binds_vs_high_def(self):
        src = make_ally(atk=100.0)
        t = make_enemy(defense=1000.0)
        dmg = damage.deal_hit(src, t, 100.0, damage.PHYS)
        self.assertAlmostEqual(dmg, 5.0)

    def test_arts_uses_res_and_keeps_floor(self):
        src = make_ally(atk=881.0)
        t = make_enemy(res=50.0)
        dmg = damage.deal_hit(src, t, 881.0, damage.ARTS_T)
        self.assertAlmostEqual(dmg, 440.5)

    def test_true_damage_ignores_def_res(self):
        src = make_ally(atk=500.0)
        t = make_enemy(defense=900.0, res=90.0)
        dmg = damage.deal_hit(src, t, 500.0, damage.TRUE_T)
        self.assertAlmostEqual(dmg, 500.0)

    def test_flat_then_percent_defense_penetration(self):
        src = make_ally(atk=1000.0)
        src.add_def_ignore_flat(200.0)
        src.add_def_ignore_pct(0.50)
        t = make_enemy(defense=600.0)
        # effective DEF = max(0,600-200)*(1-0.5)=200 -> 1000-200=800
        dmg = damage.deal_hit(src, t, 1000.0, damage.PHYS)
        self.assertAlmostEqual(dmg, 800.0)

    def test_kill_marks_dead_and_credits_source(self):
        src = make_ally(atk=100.0)
        t = make_enemy(hp=50.0, defense=0.0)
        damage.deal_hit(src, t, 100.0, damage.PHYS)
        self.assertFalse(t.alive)
        self.assertEqual(src.account["kills"], 1)


class BlockingTest(unittest.TestCase):
    def _blocker(self, cap, r, c):
        b = make_ally(atk=10.0, block_cnt=cap)
        b.deployed = True
        b.tile_r, b.tile_c = r, c
        b.x, b.y = float(c), float(r)
        return b

    def test_ground_contact_blocks_within_radius(self):
        b = self._blocker(1, 5, 5)
        enemy = make_enemy()
        enemy.x, enemy.y = 5.3, 5.0  # within ground radius ~0.707
        occ = {(5, 5): b}
        self.assertIs(blocking.check_block(enemy, occ), b)
        self.assertEqual(enemy.blocked_by, b)
        self.assertIn(enemy, b.blocking)

    def test_capacity_respects_block_weight(self):
        b = self._blocker(1, 5, 5)
        first = make_enemy()
        first.x, first.y = 5.2, 5.0
        occ = {(5, 5): b}
        blocking.check_block(first, occ)
        second = make_enemy()
        second.x, second.y = 5.4, 5.0
        self.assertIsNone(blocking.check_block(second, occ))

    def test_unblockable_flag_skips_block(self):
        b = self._blocker(3, 5, 5)
        enemy = make_enemy()
        enemy.flags = {"unblockable": True}
        enemy.x, enemy.y = 5.1, 5.0
        self.assertIsNone(blocking.check_block(enemy, {(5, 5): b}))

    def test_release_clears_links(self):
        b = self._blocker(2, 5, 5)
        enemy = make_enemy()
        enemy.x, enemy.y = 5.1, 5.0
        blocking.check_block(enemy, {(5, 5): b})
        blocking.release_blocked(b)
        self.assertIsNone(enemy.blocked_by)
        self.assertEqual(b.blocking, [])


class WaveAndReservoirTest(unittest.TestCase):
    def test_scheduler_expands_count_and_interval(self):
        sched = WaveScheduler([SpawnSpec(10.0, "mob", count=3, interval=2.0)])
        events = []
        for t in (10.0, 12.0, 14.0):
            events += sched.due(t)
        self.assertEqual([e.time for e in events], [10.0, 12.0, 14.0])
        self.assertEqual(sched.pending(), 0)

    def test_reservoir_builds_when_inflow_exceeds_kill(self):
        rp = ReservoirPressure()
        res = rp.reservoir("front", capacity=3)
        res.inflow = 2.0
        rp.set_kill_rate("front", effective_dps=1000, enemy_effective_hp=1000)
        for _ in range(30):
            rp.step(1.0)  # net +1/s
        self.assertAlmostEqual(res.level, 30.0)
        self.assertGreater(res.overflow_time, 0.0)
        self.assertIn("front", rp.leak_risk())

    def test_reservoir_drains_when_kill_exceeds_inflow(self):
        rp = ReservoirPressure()
        res = rp.reservoir("front", capacity=5)
        res.level = 10.0
        res.inflow = 0.0
        rp.set_kill_rate("front", effective_dps=2000, enemy_effective_hp=1000)
        for _ in range(10):
            rp.step(1.0)  # -2/s, floored at 0
        self.assertEqual(res.level, 0.0)

    def test_travel_seconds_uses_move_scale(self):
        # moveSpeed 2 -> 1 tile/s; 10 tiles takes 10s.
        self.assertAlmostEqual(travel_seconds(2.0, 10.0), 10.0)


class BattleEndToEndTest(unittest.TestCase):
    def _factory(self, hp, atk, defense=0.0):
        def fn(key, ev):
            e = make_enemy(uid=f"{key}_{ev.seq}", hp=hp, atk=atk,
                           defense=defense, move_speed=2.0)  # 1 tile/s
            e.x = 0.0
            e.y = 5.0
            return e
        return fn

    def test_blocked_enemy_is_killed_and_battle_clears(self):
        sched = WaveScheduler([SpawnSpec(0.0, "mob", count=2, interval=1.0)])
        b = Battle(rows=12, cols=20, time_limit=60.0, scheduler=sched)

        defender = make_ally(atk=500.0, base_bat=1.0, block_cnt=2,
                             range_radius=1.0)
        b.add_ally(defender, 5, 5)
        b.set_spawn_factory(self._factory(hp=500.0, atk=10.0))
        b.set_front_capacity(2)

        result = b.run()
        self.assertEqual(result["reason"], "cleared")
        self.assertEqual(result["killed"], 2)
        self.assertEqual(result["leaked"], 0)
        self.assertEqual(defender.account["kills"], 2)

    def test_timeout_counts_survivors_as_leaks(self):
        # Enemies faster than the field can fully clear within a short limit.
        sched = WaveScheduler([SpawnSpec(0.0, "mob", count=1, interval=0.0)])
        b = Battle(rows=12, cols=50, time_limit=2.0, scheduler=sched)
        # No defender at all: enemy walks and is reaped at timeout.
        b.set_spawn_factory(self._factory(hp=10000.0, atk=10.0))
        result = b.run()
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual(result["leaked"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
