# -*- coding: utf-8 -*-
"""Tests for the timed burst-skill state machine (commit F, kernel side).

Pure unit/driver construction with hand-built specs, so these run without the
git-ignored source tables or the committed data artifact.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from advisor.battle.unit import Unit, BaseStats
from advisor.battle.skills import SkillCycle, SkillDriver


def make_unit(uid="op_test", name="测试干员"):
    base = BaseStats(atk=100.0, max_hp=1000.0, base_bat=1.0)
    return Unit(uid, name, "ally", "op", base)


class SkillCycleTest(unittest.TestCase):
    def spec(self, **over):
        s = {"charge_time": 10.0, "duration": 5.0, "multiplier": 2.0,
             "name": "攻击强化", "initial_charge": 0.0}
        s.update(over)
        return s

    def test_starts_idle_and_charges(self):
        u = make_unit()
        c = SkillCycle(self.spec())
        self.assertFalse(c.active)
        c.step(9.9, u)
        self.assertFalse(c.active)
        self.assertEqual(u.skill_atk_mul, 1.0)

    def test_fires_at_full_sp_and_applies_multiplier(self):
        u = make_unit()
        c = SkillCycle(self.spec())
        c.step(10.0, u)
        self.assertTrue(c.active)
        self.assertEqual(u.skill_atk_mul, 2.0)
        self.assertEqual(u.stats.atk, 200.0)
        self.assertEqual(c.activations, 1)

    def test_window_ends_and_reverses_exactly(self):
        u = make_unit()
        c = SkillCycle(self.spec())
        c.step(10.0, u)                 # fires
        self.assertEqual(u.stats.atk, 200.0)
        c.step(5.0, u)                  # full active window
        self.assertFalse(c.active)
        self.assertEqual(u.skill_atk_mul, 1.0)
        self.assertEqual(u.stats.atk, 100.0)

    def test_recharges_and_fires_again(self):
        u = make_unit()
        c = SkillCycle(self.spec())
        c.step(10.0, u)   # first fire
        c.step(5.0, u)    # window ends
        c.step(10.0, u)   # recharged
        self.assertTrue(c.active)
        self.assertEqual(u.stats.atk, 200.0)
        self.assertEqual(c.activations, 2)

    def test_precharged_skill_opens_active(self):
        u = make_unit()
        d = SkillDriver()
        d.attach(u, self.spec(initial_charge=10.0))
        self.assertTrue(d.is_active(u.id))
        self.assertEqual(u.skill_atk_mul, 2.0)
        c = d._cycles[u.id]
        c.step(5.0, u)
        self.assertFalse(c.active)
        self.assertEqual(u.stats.atk, 100.0)

    def test_partial_initial_charge_still_waits(self):
        u = make_unit()
        c = SkillCycle(self.spec(initial_charge=4.0))
        c.step(5.0, u)   # 4 + 5 = 9 < 10
        self.assertFalse(c.active)
        c.step(1.0, u)   # reaches 10
        self.assertTrue(c.active)

    def test_initial_charge_clamped_to_full(self):
        u = make_unit()
        c = SkillCycle(self.spec(initial_charge=99.0))
        self.assertTrue(c.active)
        self.assertEqual(c.active_remaining, 5.0)


class SkillDriverTest(unittest.TestCase):
    def test_attach_none_keeps_plain_attacks(self):
        u = make_unit()
        d = SkillDriver()
        d.attach(u, None)
        d.step_all(100.0, [u])
        self.assertEqual(u.skill_atk_mul, 1.0)
        self.assertEqual(d.snapshot(), {})

    def test_driver_runs_multiple_units(self):
        fast = make_unit("op_fast", "快速")
        slow = make_unit("op_slow", "慢速")
        d = SkillDriver()
        d.attach(fast, {"charge_time": 5.0, "duration": 2.0,
                        "multiplier": 1.5, "initial_charge": 0.0})
        d.attach(slow, {"charge_time": 20.0, "duration": 3.0,
                        "multiplier": 3.0, "initial_charge": 0.0})
        fast.deployed = slow.deployed = True
        d.step_all(5.0, [fast, slow])
        self.assertTrue(d.is_active(fast.id))
        self.assertFalse(d.is_active(slow.id))
        self.assertEqual(fast.stats.atk, 150.0)
        snap = d.snapshot()
        self.assertIn(fast.id, snap)
        self.assertTrue(snap[fast.id]["active"])

    def test_skips_dead_or_undeployed(self):
        u = make_unit()
        d = SkillDriver()
        d.attach(u, {"charge_time": 5.0, "duration": 2.0,
                     "multiplier": 2.0, "initial_charge": 0.0})
        u.deployed = True
        u.alive = False
        d.step_all(10.0, [u])
        self.assertFalse(d.is_active(u.id))
        self.assertEqual(u.skill_atk_mul, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
