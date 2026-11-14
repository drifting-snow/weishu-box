# -*- coding: utf-8 -*-
"""Battle orchestration: the fixed-order tick loop (clean-room).

Tick order (methodology cross-reference in docs/stronghold_engine_mapping.md):
  scheduled -> spawns -> (DP) -> buffs -> attackCommit -> enemies
  -> enemy index -> allies (skill tick + attack) -> (projectiles)
  -> (redeploy) -> (boss sync) -> pressure/wave bookkeeping -> end check.

Parenthesised phases are explicit extension points in this first cut. The loop
shape and ordering match the reference protocol so each can be filled in without
restructuring; the implementation is our own and imports no GPL code.
"""

from .clock import Clock
from .grid import Grid
from .unit import Unit
from . import blocking
from .wave import WaveScheduler, ReservoirPressure
from .constants import TICK, MOVE_SCALE
from . import damage
from .skills import SkillDriver


class Battle:
    def __init__(self, rows=12, cols=20, time_limit=60.0,
                 scheduler=None, pressure_key="front"):
        self.clock = Clock()
        self.grid = Grid(rows, cols)
        self.time_limit = time_limit
        self.scheduler: WaveScheduler = scheduler or WaveScheduler([])
        self.pressure = ReservoirPressure()
        self.pressure_key = pressure_key

        self.allies = []
        self.enemies = []
        self._spawn_factory = None   # callable(enemy_key)->Unit, set by caller
        self.finished = False
        self.reason = None
        self.killed = 0
        self.total = 0
        self.leaked = 0
        # Operators knocked out by enemy attacks (distinct from leaks).
        self.ally_losses = 0
        # Simple inflow bookkeeping per pressure tile.
        self._pressure = self.pressure.reservoir(pressure_key, capacity=0)
        # Timed burst-skill state machine (no-op for units without a burst skill).
        self.skill_driver = SkillDriver()

    # -- setup --
    def set_spawn_factory(self, fn):
        """fn(enemy_key, spawn_event) -> Unit (an enemy unit)."""
        self._spawn_factory = fn

    def add_ally(self, unit, row, col, block_capacity=None):
        unit.deployed = True
        unit.ground = True
        if block_capacity is not None:
            unit.base.block_cnt = block_capacity
            unit.mark_dirty()
        self.grid.occupy(unit, row, col)
        self.allies.append(unit)

    def set_front_capacity(self, capacity):
        self._pressure.capacity = capacity

    def attach_skill(self, unit, spec):
        """Bind a burst_skill spec (from operator_skills.json) to an ally."""
        self.skill_driver.attach(unit, spec)

    # -- one tick --
    def step(self):
        if self.finished:
            return
        dt = self.clock.dt

        # 1. scheduled callbacks (extension point; none in first cut)
        # 2. spawns
        self._process_spawns()
        # 3. DP (extension point)
        # 4. buffs tick (extension point; mods are static in first cut)
        # 5. attack commit (allies keep current target; implicit below)
        # 6. enemies: move then block
        self._update_enemies(dt)
        # 6b. enemies that can reach an operator attack it (blocked or ranged)
        self._update_enemy_attacks(dt)
        # 6c. periodic enemy skill bursts: pure physical AoE hits every ally in
        # radius (e.g. 矩兽 CombatAoe). Arts/nerve/chain bursts are not modelled.
        self._update_enemy_bursts(dt)
        # 7. enemy index (occupancy already maintained; range queries inline)
        # 8. allies: skill tick then attack
        self.skill_driver.step_all(dt, self.allies)
        self._update_allies(dt)
        # 9-12. projectiles / redeploy / boss (extension points)
        # Wave pressure reservoir advances every tick.
        self.pressure.step(dt)

        self.clock.advance()
        self._check_end()

    def run(self, max_seconds=3600.0):
        limit = self.clock.time + max_seconds
        while not self.finished and self.clock.time < limit:
            self.step()
        return self.result()

    # -- phase implementations --
    def _process_spawns(self):
        for ev in self.scheduler.due(self.clock.time):
            self.total += 1
            if self._spawn_factory is None:
                continue
            enemy = self._spawn_factory(ev.enemy_key, ev)
            if enemy is None:
                continue
            enemy.deployed = True
            # Enemies enter at a red gate; callers may override start tile.
            enemy.x = getattr(enemy, "x", 0.0)
            enemy.y = getattr(enemy, "y", 0.0)
            self.enemies.append(enemy)
            # One more body presses the front reservoir.
            self._pressure.inflow += 0.0  # inflow rate set externally; count via level
            self._pressure.level += 1.0

    def _update_enemies(self, dt):
        survivors = []
        for e in self.enemies:
            if not e.alive:
                continue
            # Already blocked? Stay put (contact block halts movement).
            if getattr(e, "blocked_by", None) is not None:
                survivors.append(e)
                continue
            # Re-evaluate contact block each tick.
            blocker = blocking.check_block(e, self.grid.occupancy)
            if blocker is not None:
                survivors.append(e)
                continue
            # Move toward the blue gate along +x at effective tile speed.
            speed = e.stats.move_speed * MOVE_SCALE
            e.x += speed * dt
            e.moving = speed > 0
            # Reached the blue gate -> leak.
            if e.x >= self.grid.cols:
                self.leaked += 1
                self._pressure.level = max(0.0, self._pressure.level - 1.0)
                e.alive = False
                continue
            survivors.append(e)
        self.enemies = survivors

    def _update_enemy_attacks(self, dt):
        """Enemies hit back: blocked melee contact or ranged reach.

        Targeting follows the official applyWay/rangeRadius fields carried on
        each enemy Unit by the adapter:
          * a blocked enemy always attacks its blocker (contact melee);
          * a RANGED/ALL enemy with rangeRadius>0 also attacks the nearest
            operator within Euclidean reach even when not blocked;
          * non-attackers (atk 0 / applyWay NONE) simply never swing.
        Damage goes through the same deal_hit trunk as ally attacks, so
        operator DEF/RES mitigation and the 5% floor apply identically.
        """
        for e in self.enemies:
            if not e.alive:
                continue
            if not getattr(e, "deals_damage", False):
                continue
            e.atk_cd = max(0.0, getattr(e, "atk_cd", 0.0) - dt)
            if e.atk_cd > 0:
                continue
            target = self._enemy_target(e)
            if target is None:
                continue
            family = getattr(e, "damage_family", damage.PHYS)
            damage.deal_hit(e, target, e.stats.atk, family)
            e.atk_cd = e.stats.interval
            if not target.alive:
                self._remove_ally(target)

    def _enemy_target(self, enemy):
        # Contact: whatever blocks this enemy is the priority target.
        blocker = getattr(enemy, "blocked_by", None)
        if blocker is not None and blocker.alive:
            return blocker
        radius = float(getattr(enemy, "enemy_range", 0.0) or 0.0)
        if radius <= 0:
            return None  # melee enemy with no blocker cannot reach anyone
        best, best_d2 = None, float("inf")
        for u in self.allies:
            if not u.alive or not u.deployed:
                continue
            d2 = (u.x - enemy.x) ** 2 + (u.y - enemy.y) ** 2
            if d2 <= radius * radius and d2 < best_d2:
                best, best_d2 = u, d2
        return best

    def _update_enemy_bursts(self, dt):
        """Periodic AoE skill bursts from enemies, physical or arts.

        Each burst on a living enemy counts down; when ready it hits EVERY
        deployed operator within Euclidean range_radius for base_atk * atk_scale.
        The burst's damage_family (data/enemy_skills.json, proven from the enemy
        description text) picks the trunk: phys -> operator DEF, arts -> operator
        RES; both keep the 5% minimum-damage floor. Operators felled this way are
        removed exactly like attack casualties, releasing their blocks. Elemental
        (nerve) side-damage, chain, stun, DoT, shields and summons never reach
        here because the data builder parks them.
        """
        for e in self.enemies:
            if not e.alive or not getattr(e, "aoe_bursts", None):
                continue
            for burst in e.aoe_bursts:
                cd = max(0.0, float(burst.get("_cd", 0.0)) - dt)
                burst["_cd"] = cd
                if cd > 0:
                    continue
                radius = float(burst["range_radius"])
                amount = e.stats.atk * float(burst["atk_scale"])
                family = damage.ARTS_T if burst.get("damage_family") == "arts" \
                    else damage.PHYS
                # Snapshot targets first so removing a casualty mid-loop does not
                # mutate the ally list while we still iterate over it.
                victims = [u for u in self.allies
                           if u.alive and u.deployed and
                           (u.x - e.x) ** 2 + (u.y - e.y) ** 2 <= radius ** 2]
                for target in victims:
                    damage.deal_hit(e, target, amount, family)
                for target in victims:
                    if not target.alive and target in self.allies:
                        self._remove_ally(target)
                burst["_cd"] = float(burst["cooldown"])

    def _remove_ally(self, ally):
        """Take a defeated operator out of the field and release its blocks."""
        self.ally_losses += 1
        blocking.release_blocked(ally)
        self.grid.vacate(ally.tile_r, ally.tile_c)
        ally.deployed = False
        if ally in self.allies:
            self.allies.remove(ally)

    def _update_allies(self, dt):
        for u in self.allies:
            if not u.alive or not u.deployed:
                continue
            u.atk_cd = max(0.0, u.atk_cd - dt)
            if u.atk_cd > 0:
                continue
            target = self._acquire_target(u)
            if target is None:
                continue
            family = getattr(u, "damage_family", damage.PHYS)
            damage.deal_hit(u, target, u.stats.atk, family)
            u.account["attacks"] = u.account.get("attacks", 0)
            u.atk_cd = u.stats.interval
            if not target.alive:
                self.killed += 1
                blocking.unblock(target)
                self._pressure.level = max(0.0, self._pressure.level - 1.0)
                if target in self.enemies:
                    self.enemies.remove(target)

    def _acquire_target(self, ally):
        """Nearest enemy the ally can hit.

        Two range models, chosen by what the unit carries:
          * range_cells (real operator_ranges grid, facing already baked in by
            the adapter): the enemy's tile offset from the ally's tile must be a
            member of the offset-cell set.
          * legacy range_radius (synthetic first-cut units): Euclidean centre
            distance <= radius. Retained unchanged so the kernel's own tests and
            any hand-built units keep their original behaviour.
        Blocked enemies are always hittable by their blocker regardless of
        range ('whatever blocks an enemy can hit it').
        """
        cells = getattr(ally, "range_cells", None)
        ar, ac = round(ally.y), round(ally.x)
        radius = ally.stats.range_radius
        best, best_d2 = None, float("inf")
        for e in self.enemies:
            if not e.alive:
                continue
            if getattr(e, "blocked_by", None) is ally:
                return e
            d2 = (e.x - ally.x) ** 2 + (e.y - ally.y) ** 2
            if cells is not None:
                offset = (round(e.y) - ar, round(e.x) - ac)
                in_range = offset in cells
            else:
                if radius <= 0:
                    continue
                in_range = d2 <= radius * radius
            if in_range and d2 < best_d2:
                best, best_d2 = e, d2
        return best

    def _check_end(self):
        if self.finished:
            return
        no_pending = self.scheduler.pending() == 0
        no_enemy = all(not e.alive for e in self.enemies)
        if no_pending and no_enemy and self.total > 0:
            self._finish("cleared")
            return
        if self.clock.time >= self.time_limit - 1e-9:
            # Survivors at the limit count as leaks.
            for e in self.enemies:
                if e.alive:
                    self.leaked += 1
                    e.alive = False
            self._finish("timeout")

    def _finish(self, reason):
        self.finished = True
        self.reason = reason

    def result(self):
        return {
            "time": round(self.clock.time, 3),
            "reason": self.reason,
            "killed": self.killed,
            "leaked": self.leaked,
            "ally_losses": self.ally_losses,
            "total": self.total,
            "resolved": min(self.total, self.killed + self.leaked),
            "pressure": self.pressure.snapshot(),
        }
