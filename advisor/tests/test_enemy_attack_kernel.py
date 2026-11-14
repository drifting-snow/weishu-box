# -*- coding: utf-8 -*-
"""Tests for enemy attacks in the clean-room battle kernel (commit D).

Synthetic, deterministic units so behaviour is pinned without depending on
season data. Ally defense/RES mitigation goes through the same deal_hit trunk
as operator damage.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from advisor.battle.battle import Battle
from advisor.battle.unit import Unit, BaseStats


def defender(hp=1000.0, defense=100.0, block=1, atk=0.0, bat=1.0):
    u = Unit("def", "def", "ally", "op",
             BaseStats(atk=atk, defense=defense, max_hp=hp,
                       base_bat=bat, block_cnt=block))
    u.deployed = True
    u.ground = True
    return u


def attacker(atk=300.0, bat=1.0, enemy_range=0.0, deals=True):
    e = Unit("e", "e", "enemy", "enemy",
             BaseStats(atk=atk, max_hp=99999.0, base_bat=bat))
    e.deployed = True
    e.alive = True
    e.deals_damage = deals
    e.enemy_range = enemy_range
    e.damage_family = "phys"
    return e


class EnemyAttackTest(unittest.TestCase):
    def test_non_attacking_enemy_never_deals_damage(self):
        b = Battle(rows=12, cols=20, time_limit=5.0)
        d = defender()
        b.add_ally(d, 5, 5)
        e = attacker(deals=False)
        e.blocked_by = d
        d.blocking.append(e)
        b.enemies.append(e)
        b.run()
        self.assertEqual(d.account.get("taken", 0.0), 0.0)
        self.assertEqual(b.ally_losses, 0)

    def test_blocked_enemy_hits_blocker_with_defense_mitigation(self):
        b = Battle(rows=12, cols=20, time_limit=2.0)
        d = defender(hp=10000.0, defense=100.0)
        b.add_ally(d, 5, 5)
        e = attacker(atk=300.0, bat=1.0)
        e.blocked_by = d
        d.blocking.append(e)
        b.enemies.append(e)
        b.run()
        # physical: 300 - 100 = 200 per hit; at least one swing landed
        self.assertGreater(d.account.get("taken", 0.0), 0.0)
        self.assertEqual(e.account.get("attacks", 0) >= 1, True)
        # every recorded hit is the mitigated 200 (5% floor never binds here)
        self.assertAlmostEqual(d.account["taken"] / e.account["attacks"], 200.0,
                               places=4)

    def test_enemy_kills_operator_and_releases_block(self):
        b = Battle(rows=12, cols=20, time_limit=10.0)
        d = defender(hp=150.0, defense=0.0, atk=0.0)  # dies quickly, cannot kill
        b.add_ally(d, 5, 5)
        e = attacker(atk=100.0, bat=1.0)
        e.blocked_by = d
        d.blocking.append(e)
        b.enemies.append(e)
        b.run()
        self.assertEqual(b.ally_losses, 1)
        self.assertFalse(d.alive)
        # blocking relationship is released and the tile is freed
        self.assertIsNone(e.blocked_by)
        self.assertEqual(d.blocking, [])
        self.assertNotIn((5, 5), b.grid.occupancy)

    def test_ranged_enemy_strikes_without_blocking(self):
        b = Battle(rows=12, cols=20, time_limit=1.0)
        d = defender(hp=10000.0, defense=0.0)
        b.add_ally(d, 5, 10)
        e = attacker(atk=250.0, bat=1.0, enemy_range=3.0)
        # place the enemy within reach but not in contact
        e.x, e.y = 8.0, 5.0
        b.enemies.append(e)
        b.run()
        self.assertGreater(d.account.get("taken", 0.0), 0.0)
        self.assertIsNone(e.blocked_by)  # never blocked, yet still attacked

    def test_ranged_enemy_respects_range(self):
        b = Battle(rows=12, cols=20, time_limit=1.0)
        d = defender(hp=10000.0, defense=0.0)
        b.add_ally(d, 5, 15)
        e = attacker(atk=250.0, bat=1.0, enemy_range=2.0)
        e.x, e.y = 5.0, 5.0  # far beyond reach
        b.enemies.append(e)
        b.run()
        self.assertEqual(d.account.get("taken", 0.0), 0.0)

    def test_result_reports_ally_losses(self):
        b = Battle(rows=12, cols=20, time_limit=10.0)
        d = defender(hp=50.0, defense=0.0)
        b.add_ally(d, 5, 5)
        e = attacker(atk=100.0, bat=1.0)
        e.blocked_by = d
        d.blocking.append(e)
        b.enemies.append(e)
        res = b.run()
        self.assertIn("ally_losses", res)
        self.assertEqual(res["ally_losses"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
