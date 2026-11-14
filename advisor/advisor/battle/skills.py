# -*- coding: utf-8 -*-
"""Timed burst-skill state machine for ally operators (clean-room).

Drives the subset of skills extracted by tools/build_operator_skills.py:
INCREASE_WITH_TIME (auto SP recovery), additive ATK-up skills with a finite
duration and a multiplier > 1. In the auto-battle there is no manual skill
button, so a skill fires the instant SP reaches its cost, stays active for its
duration (multiplier applied through Unit.skill_atk_mul), then recharges.

Design constraints
------------------
* Data-only: the module never reads data files itself; the adapter hands each
  burst_skill dict to attach(). No global state, no GPL imports.
* Reversible: the ATK buff lives in the dedicated Unit.skill_atk_mul slot, not
  the shared mods bucket, so ending a window restores exactly 1.0.
* Out-of-scope skills (attack/hit-taken recovery, DoT, control, total-source)
  have no SkillCycle upstream, so those units simply keep doing basic attacks.
"""
from typing import Dict, Optional


class SkillCycle:
    """One operator's charge -> active -> charge burst loop."""

    def __init__(self, spec: dict):
        self.charge_time = float(spec["charge_time"])
        self.duration = float(spec["duration"])
        self.multiplier = float(spec["multiplier"])
        self.skill_name = spec.get("name")
        init = min(float(spec.get("initial_charge", 0.0)), self.charge_time)
        # SP already banked at deploy time; a fully-precharged skill opens active.
        self.sp_seconds = init
        self.active = init >= self.charge_time
        self.active_remaining = self.duration if self.active else 0.0
        self.activations = 0

    def step(self, dt: float, unit) -> None:
        if self.active:
            self.active_remaining -= dt
            if self.active_remaining <= 0.0:
                # Window ends: drop the buff exactly and restart the charge.
                self.active = False
                self.active_remaining = 0.0
                self.sp_seconds = 0.0
                unit.skill_atk_mul = 1.0
                unit.mark_dirty()
            # While active the multiplier is constant, so no recalc needed.
            return
        self.sp_seconds += dt
        if self.sp_seconds >= self.charge_time:
            self.active = True
            self.active_remaining = self.duration
            unit.skill_atk_mul = self.multiplier
            unit.mark_dirty()
            self.activations += 1


class SkillDriver:
    """Holds one SkillCycle per operator that has a drivable burst skill."""

    def __init__(self):
        self._cycles: Dict[str, SkillCycle] = {}

    def attach(self, unit, spec: Optional[dict]) -> None:
        """Bind a burst_skill spec to a unit; None/empty means plain attacks."""
        if not spec:
            return
        cyc = SkillCycle(spec)
        self._cycles[unit.id] = cyc
        if cyc.active:  # precharged at deploy: apply the opening buff immediately
            unit.skill_atk_mul = cyc.multiplier
            unit.mark_dirty()

    def step_all(self, dt: float, allies) -> None:
        for unit in allies:
            cyc = self._cycles.get(unit.id)
            if cyc is not None and unit.alive and unit.deployed:
                cyc.step(dt, unit)

    def is_active(self, unit_id: str) -> bool:
        cyc = self._cycles.get(unit_id)
        return bool(cyc and cyc.active)

    def snapshot(self) -> dict:
        return {uid: {"active": c.active, "activations": c.activations,
                      "sp_seconds": round(c.sp_seconds, 2),
                      "multiplier": c.multiplier}
                for uid, c in self._cycles.items()}
