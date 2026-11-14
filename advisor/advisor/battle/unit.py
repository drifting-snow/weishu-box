# -*- coding: utf-8 -*-
"""Unit model and stat aggregation (clean-room).

Aggregation rule (public Arknights attribute formula), recomputed lazily
whenever a modifier changes:

    ATK   = ((base_atk + sum atk_flat) * (1 + sum atk_pct) + atk_final)
            * prod atk_mul * cult_atk
    DEF   =  (base_def + sum def_flat) * (1 + sum def_pct)
            * prod def_mul * cult_def
    maxHp =  (base_hp  + sum hp_flat)  * (1 + sum hp_pct)
            * prod hp_mul  * cult_hp
    RES   = clamp((base_res + sum res_flat) * prod res_mul, 0, 100)
    aspd  = clamp(base_aspd + sum aspd_delta, ASPD_MIN, ASPD_MAX)
    bat   = (base_bat + sum bat_flat) * max(0.1, 1 + sum bat_pct)
    interval = bat * 100 / aspd

The two modifier buckets are kept separate on purpose:
  *_pct modifiers of the same attribute are SUMMED (direct-multiplication class,
  e.g. bond/strategy/equipment "+ATK%"), while *_mul modifiers are independent
  "raise to X%" multipliers that compound. Collapsing them caused the reference
  engine's historical x74 runaway at high layer counts.
"""

from dataclasses import dataclass, field
from typing import Optional

from .constants import (
    ASPD_MIN, ASPD_MAX, BASE_ASPD, BAT_PCT_FLOOR, BAT_PCT_ABS_FLOOR, RES_CAP,
)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


@dataclass
class BaseStats:
    """Immutable-ish base panel of a unit."""
    atk: float = 0.0
    defense: float = 0.0
    max_hp: float = 1.0
    res: float = 0.0
    base_bat: float = 1.0          # base attack interval (baseAttackTime), seconds
    aspd: float = BASE_ASPD        # base attack-speed points (almost always 100)
    block_cnt: int = 0
    move_speed: float = 0.0
    range_radius: float = 0.0


@dataclass
class Stats:
    """Aggregated, ready-to-use stats (output of Unit.recalc)."""
    atk: float
    defense: float
    max_hp: float
    res: float
    aspd: float
    bat: float
    interval: float
    block_cnt: int
    move_speed: float
    range_radius: float
    # Damage penetration / taken multipliers (extension hooks for the trunk).
    def_ignore_flat: float = 0.0
    def_ignore_pct: float = 0.0
    res_ignore_flat: float = 0.0
    res_ignore_pct: float = 0.0


class ModBucket:
    """Accumulates the additive-flat, summed-percent and compound-mul buckets."""

    def __init__(self):
        self.flat = {}      # e.g. atk_flat, bat_flat
        self.pct = {}       # summed percent terms (stored as fractions)
        self.mul = {}       # independent compound multipliers
        self.final_add = 0.0  # atk_final (post-percent additive)

    def add_flat(self, key, value):
        self.flat[key] = self.flat.get(key, 0.0) + value

    def add_pct(self, key, fraction):
        self.pct[key] = self.pct.get(key, 0.0) + fraction

    def add_mul(self, key, multiplier):
        self.mul[key] = self.mul.get(key, 1.0) * multiplier

    def f(self, key):
        return self.flat.get(key, 0.0)

    def p(self, key):
        return self.pct.get(key, 0.0)

    def m(self, key):
        return self.mul.get(key, 1.0)


class Unit:
    """A battlefield unit (operator, token, enemy or device)."""

    def __init__(self, unit_id, name, side, kind, base: Optional[BaseStats] = None):
        self.id = unit_id
        self.name = name
        self.side = side          # 'ally' | 'enemy'
        self.kind = kind          # 'op' | 'token' | 'enemy' | 'device'
        self.base = base or BaseStats()
        # Cultivation (fixed-level) independent multiplier, wired from scaling.py.
        self.cult_mul = {"atk": 1.0, "def": 1.0, "hp": 1.0}
        # Reversible burst-skill ATK multiplier, driven by battle/skills.py. Kept
        # separate from mods so a skill window can be removed exactly (the shared
        # mods 'atk' bucket mixes permanent bond/item/elite sources and has no
        # per-source undo). 1.0 means no skill active; a timed ATK-up skill sets
        # its multiplier while active and resets to 1.0 when the window ends.
        self.skill_atk_mul = 1.0
        self.mods = ModBucket()
        self.hp = self.base.max_hp
        self.alive = True
        self.deployed = False
        # Field position in (col=x, row=y) tile coordinates (floats allowed; the
        # owning tile is round()). Ground units default to ground placement.
        self.x = 0.0
        self.y = 0.0
        self.tile_r = 0
        self.tile_c = 0
        self.ground = kind != "device" and side == "ally"
        self.is_flying = False
        self.flags = {}
        # Block bookkeeping: an ally blocker lists held enemies; an enemy points
        # back at its blocker. block_weight only matters for enemies.
        self.blocking = []
        self.blocked_by = None
        self.block_weight = 1
        self.hidden = False
        self.moving = False
        # Attack cooldown in remaining seconds; 0 means ready to swing.
        self.atk_cd = 0.0
        # Real tile-based attack range as a set of (drow, dcol) world offsets
        # from the unit's own tile. None -> fall back to the legacy Euclidean
        # range_radius rule (kept for the first-cut synthetic tests). The
        # adapter fills this from operator_ranges.json with facing already baked
        # in, so the kernel stays a pure membership test with no facing logic.
        self.range_cells = None
        # Periodic physical AoE skill bursts (enemy skills, enemy_skills.json).
        # Each entry is a runtime dict: {cooldown, atk_scale, range_radius, _cd}
        # where _cd is the remaining seconds until the next burst. Empty for
        # normal units; the battle loop ticks it and hits every ally in radius.
        self.aoe_bursts = []
        self._dirty = True
        self._stats = None
        # Aggregated kill/damage accounting.
        self.account = {"dmg": 0.0, "kills": 0, "heal": 0.0, "taken": 0.0,
                        "attacks": 0}

    # -- modifier API (buff/equipment/bond layer writes here) --
    def mark_dirty(self):
        self._dirty = True

    def add_atk_flat(self, v):
        self.mods.add_flat("atk", v); self.mark_dirty()

    def add_atk_pct(self, fraction):
        """Direct-multiplication class: summed with sibling +ATK% terms."""
        self.mods.add_pct("atk", fraction); self.mark_dirty()

    def add_atk_mul(self, multiplier):
        """Independent 'raise to X%' multiplier (compounds)."""
        self.mods.add_mul("atk", multiplier); self.mark_dirty()

    def add_def_flat(self, v):
        self.mods.add_flat("def", v); self.mark_dirty()

    def add_def_pct(self, fraction):
        self.mods.add_pct("def", fraction); self.mark_dirty()

    def add_hp_flat(self, v):
        self.mods.add_flat("hp", v); self.mark_dirty()

    def add_hp_pct(self, fraction):
        self.mods.add_pct("hp", fraction); self.mark_dirty()

    def add_aspd(self, points):
        self.mods.add_flat("aspd", points); self.mark_dirty()

    def add_bat_flat(self, seconds):
        """Absolute BAT change in seconds (e.g. Dusk S3 base_attack_time +0.40).

        This is the correct channel for 'attack interval +X s' effects: it shifts
        BAT before the ASPD division, rather than multiplying the final interval.
        """
        self.mods.add_flat("bat", seconds); self.mark_dirty()

    def add_bat_pct(self, fraction):
        """Relative BAT percent change (summed, floored at -90%)."""
        self.mods.add_pct("bat", fraction); self.mark_dirty()

    def add_def_ignore_flat(self, v):
        self.mods.add_flat("def_ignore_flat", v); self.mark_dirty()

    def add_def_ignore_pct(self, fraction):
        self.mods.add_pct("def_ignore_pct", fraction); self.mark_dirty()

    def add_res_ignore_flat(self, v):
        self.mods.add_flat("res_ignore_flat", v); self.mark_dirty()

    def add_res_ignore_pct(self, fraction):
        self.mods.add_pct("res_ignore_pct", fraction); self.mark_dirty()

    @property
    def stats(self) -> Stats:
        if self._dirty:
            self.recalc()
        return self._stats

    def recalc(self):
        b = self.base
        m = self.mods
        cm = self.cult_mul

        atk = ((b.atk + m.f("atk")) * max(0.0, 1.0 + m.p("atk"))
               + m.final_add) * m.m("atk") * cm["atk"] * max(0.0, self.skill_atk_mul)
        defense = (b.defense + m.f("def")) * max(0.0, 1.0 + m.p("def")) \
            * m.m("def") * cm["def"]
        max_hp = (b.max_hp + m.f("hp")) * max(0.0, 1.0 + m.p("hp")) \
            * m.m("hp") * cm["hp"]
        res = _clamp((b.res + m.f("res")) * m.m("res"), 0.0, RES_CAP)

        aspd = _clamp(b.aspd + m.f("aspd"), ASPD_MIN, ASPD_MAX)
        # BAT: absolute flat shift first, then summed percent (floored at 10%).
        bat_pct = max(BAT_PCT_FLOOR, m.p("bat"))
        bat = max(0.0, b.base_bat + m.f("bat")) * max(BAT_PCT_ABS_FLOOR,
                                                      1.0 + bat_pct)
        interval = bat * 100.0 / aspd

        self._stats = Stats(
            atk=max(0.0, atk),
            defense=max(0.0, defense),
            max_hp=max(1.0, max_hp),
            res=res,
            aspd=aspd,
            bat=bat,
            interval=interval,
            block_cnt=max(0, round(b.block_cnt + m.f("block_cnt"))),
            move_speed=max(0.0, b.move_speed + m.f("move_speed")),
            range_radius=max(0.0, b.range_radius),
            def_ignore_flat=m.f("def_ignore_flat"),
            def_ignore_pct=_clamp(m.p("def_ignore_pct"), 0.0, 1.0),
            res_ignore_flat=m.f("res_ignore_flat"),
            res_ignore_pct=_clamp(m.p("res_ignore_pct"), 0.0, 1.0),
        )
        self._dirty = False
        return self._stats
