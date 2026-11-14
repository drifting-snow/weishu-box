# -*- coding: utf-8 -*-
"""Tests for periodic enemy AoE skill bursts in the kernel (commit H).

Synthetic deterministic units; the enemy carries an aoe_bursts runtime slot just
like the adapter populates it from data/enemy_skills.json (today: 矩兽 CombatAoe).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from advisor.battle.battle import Battle
from advisor.battle.unit import Unit, BaseStats


def make_ally(uid, hp=10000.0, defense=0.0, res=0.0):
    u = Unit(uid, uid, "ally", "op",
             BaseStats(atk=10.0, defense=defense, max_hp=hp, res=res,
                       base_bat=1.0))
    return u


def make_aoe_enemy(atk=1500.0, scale=2.0, radius=1.6, cd=2.0, init=0.0,
                   family="phys"):
    e = Unit("e_aoe", "aoe", "enemy", "enemy",
             BaseStats(atk=atk, max_hp=999999.0, base_bat=1.0, move_speed=0.0))
    e.alive = True
    e.deployed = True
    e.deals_damage = False          # no basic attack; damage comes only from the burst
    e.damage_family = "phys"
    e.x, e.y = 10.0, 6.0
    e.aoe_bursts = [{
        "cooldown": cd, "atk_scale": scale, "range_radius": radius,
        "damage_family": family, "_cd": init,
    }]
    return e


class EnemyAoEBurstTest(unittest.TestCase):
    def _battle(self, time_limit=3.0):
        b = Battle(rows=12, cols=20, time_limit=time_limit)
        inside = make_ally("in")
        outside = make_ally("out")
        b.add_ally(inside, 6, 10)
        b.add_ally(outside, 6, 16)
        inside.x, inside.y = 10.5, 6.0    # distance 0.5 <= 1.6
        outside.x, outside.y = 15.0, 6.0  # distance 5.0 > 1.6
        e = make_aoe_enemy()
        b.enemies.append(e)
        return b, inside, outside, e

    def test_burst_hits_all_allies_in_radius_only(self):
        b, inside, outside, e = self._battle(time_limit=1.0)
        b.run()
        # inside: 1500*2 = 3000 physical, defense 0 -> full 3000 on the first burst
        self.assertGreaterEqual(inside.account.get("taken", 0.0), 3000.0 - 1e-6)
        # outside the radius is never touched
        self.assertEqual(outside.account.get("taken", 0.0), 0.0)
        self.assertEqual(outside.alive, True)

    def test_burst_respects_cooldown(self):
        # 5-second window, cd 2.0, first burst at t~0 -> bursts around t=0,2,4
        b, inside, outside, e = self._battle(time_limit=5.0)
        b.run()
        hits = e.account.get("attacks", 0)
        # only the inside ally is hit, once per burst; expect 2..3 bursts, not 5
        self.assertGreaterEqual(hits, 2)
        self.assertLessEqual(hits, 3)
        # every hit is the full mitigated 3000
        self.assertAlmostEqual(inside.account["taken"] / hits, 3000.0, places=3)

    def test_burst_applies_defense_mitigation(self):
        b = Battle(rows=12, cols=20, time_limit=1.0)
        tank = make_ally("tank", defense=500.0)
        b.add_ally(tank, 6, 10)
        tank.x, tank.y = 10.5, 6.0
        e = make_aoe_enemy()
        b.enemies.append(e)
        b.run()
        # 3000 - 500 defense = 2500 per burst
        self.assertAlmostEqual(tank.account["taken"], 2500.0, places=3)

    def test_burst_can_kill_and_release_block(self):
        b = Battle(rows=12, cols=20, time_limit=1.0)
        fragile = make_ally("frail", hp=500.0)
        b.add_ally(fragile, 6, 10)
        fragile.x, fragile.y = 10.5, 6.0
        e = make_aoe_enemy()
        # make the enemy consider this ally its blocker, to prove release on death
        e.blocked_by = fragile
        fragile.blocking.append(e)
        b.enemies.append(e)
        b.run()
        self.assertFalse(fragile.alive)
        self.assertEqual(b.ally_losses, 1)
        self.assertIsNone(e.blocked_by)
        self.assertEqual(fragile.blocking, [])

    def test_enemy_without_bursts_deals_no_aoe(self):
        b = Battle(rows=12, cols=20, time_limit=3.0)
        ally = make_ally("a")
        b.add_ally(ally, 6, 10)
        ally.x, ally.y = 10.5, 6.0
        e = make_aoe_enemy()
        e.aoe_bursts = []
        b.enemies.append(e)
        b.run()
        self.assertEqual(ally.account.get("taken", 0.0), 0.0)
        self.assertEqual(b.ally_losses, 0)


class EnemyArtsAoEBurstTest(unittest.TestCase):
    def _arts_enemy(self, atk=1000.0, scale=1.0):
        # family=arts routes the burst through operator RES, not DEF
        return make_aoe_enemy(atk=atk, scale=scale, radius=2.0, cd=10.0,
                              init=0.0, family="arts")

    def test_arts_uses_res_not_defense(self):
        b = Battle(rows=12, cols=20, time_limit=1.0)
        high_res = make_ally("res", defense=0.0, res=50.0)      # 50% arts resist
        high_def = make_ally("def", defense=900.0, res=0.0)     # DEF must be ignored
        b.add_ally(high_res, 6, 10)
        b.add_ally(high_def, 6, 11)
        for u in (high_res, high_def):
            u.x, u.y = 10.5, 6.0     # both inside radius 2.0
        e = self._arts_enemy()       # amount = 1000 * 1.0
        b.enemies.append(e)
        b.run()
        self.assertAlmostEqual(high_res.account["taken"], 500.0, places=3)   # 1000*(1-.5)
        self.assertAlmostEqual(high_def.account["taken"], 1000.0, places=3)  # DEF no effect

    def test_arts_respects_five_percent_floor(self):
        b = Battle(rows=12, cols=20, time_limit=1.0)
        tanky = make_ally("t", res=99.0)   # 1% would be 10, floor is 5% = 50
        b.add_ally(tanky, 6, 10)
        tanky.x, tanky.y = 10.5, 6.0
        b.enemies.append(self._arts_enemy())
        b.run()
        self.assertAlmostEqual(tanky.account["taken"], 50.0, places=3)

    def test_arts_burst_scales_with_atk_scale(self):
        b = Battle(rows=12, cols=20, time_limit=1.0)
        ally = make_ally("a", res=0.0)
        b.add_ally(ally, 6, 10)
        ally.x, ally.y = 10.5, 6.0
        # 鳍 Discharge shape: atk 750 * 1.25 = 937.5 arts, no RES -> full
        b.enemies.append(make_aoe_enemy(atk=750.0, scale=1.25, radius=1.5,
                                        cd=24.0, family="arts"))
        b.run()
        self.assertAlmostEqual(ally.account["taken"], 937.5, places=3)

    def test_arts_burst_respects_range(self):
        b = Battle(rows=12, cols=20, time_limit=1.0)
        inside = make_ally("in", res=0.0)
        outside = make_ally("out", res=0.0)
        b.add_ally(inside, 6, 10)
        b.add_ally(outside, 6, 16)
        inside.x, inside.y = 10.5, 6.0
        outside.x, outside.y = 15.0, 6.0    # distance 5 > radius 2
        b.enemies.append(self._arts_enemy())
        b.run()
        self.assertGreater(inside.account["taken"], 0.0)
        self.assertEqual(outside.account.get("taken", 0.0), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
