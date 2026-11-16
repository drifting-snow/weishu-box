# -*- coding: utf-8 -*-
"""Adapter: feed real act3 data into the clean-room battle kernel.

Stage 2.1. The kernel in advisor/battle/ only ran on synthetic SpawnSpecs and
hand-built units. This module is the pure translation layer that wires the
decision layer's real data into it, without touching any GPL source:

  enemies : data/act3_waves.json level_stems.spawns[]  -> SpawnSpec + enemy Unit
            HP scaled by advisor.regulation_hp; def/res/motion come straight
            from the unpacked spawn row (100% coverage, no enemy_stats join
            needed for the stats the first-cut kernel consumes).
  allies  : GameState.board + operator_combat_metrics + advisor.buffs -> Unit
            atk/interval from the panel, bond/item/elite multipliers applied
            through the kernel's own ModBucket, so attack cadence stays exact.

Honest first-cut approximations (returned in `approximations`, never hidden):
  * Block count is a coarse profession default (PROFESSION_*); per-operator
    block data is not yet wired. Attack RANGE now uses the real range grids.
  * Multiple routes are folded onto a single lane so contact blocking can fire;
    per-route travel-distance differences are not modelled yet.
  * Enemies attack from the derived enemy_attack table (atk / interval / reach /
    applyWay). The unpacked table has no normal-attack phys/arts type, so enemy
    hits are modelled as physical; enemy skill bursts are not driven.
  * Skill bursts, DP, projectiles, healing and boss mechanics are not driven.

Scoring: engine.recommend runs simulate then clear_margin.apply_reservoir_pressure
so killed/leaked/pressure.overflow_seconds adjust the effective clear-margin band.
This module still only builds and runs a Battle; it does not score cards itself.
"""
import json
import os
from typing import Dict, List, Optional

from . import battle as kernel
from .battle import Battle
from .constants import MOVE_SCALE
from .unit import Unit, BaseStats
from .wave import SpawnSpec
from . import damage as kdamage

from .. import buffs
from .. import regulation_hp as rhp
from .. import clear_margin

# adapter.py lives in advisor/battle/, so three dirname calls reach the
# project root before the data/ directory (the kernel sits one level deeper
# than the advisor/*.py modules, which only need two).
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
ENEMY_STATS_PATH = os.path.join(DATA_DIR, "enemy_stats.json")
ENEMY_ATTACK_PATH = os.path.join(DATA_DIR, "enemy_attack.json")
ENEMY_SKILLS_PATH = os.path.join(DATA_DIR, "enemy_skills.json")

# ---- Coarse profession mapping (explicit approximation; no range_table) ----
# Damage family for the kernel's damage trunk.
PROFESSION_FAMILY = {
    "术师": kdamage.ARTS_T,
    "辅助": kdamage.ARTS_T,   # most casters/suppliers deal arts until typed data lands
}
# Contact block capacity by profession. Ranged high-ground units do not block.
PROFESSION_BLOCK = {
    "重装": 3,
    "近卫": 1,
    "先锋": 1,
    "特种": 1,
}

# Single-lane deployment geometry (rows/cols mirror the kernel default).
LANE_ROW = 6
MELEE_COL = 13
RANGED_COL = 10

RANGES_PATH = os.path.join(DATA_DIR, "operator_ranges.json")
SKILLS_PATH = os.path.join(DATA_DIR, "operator_skills.json")
_ranges_cache: Optional[dict] = "unloaded"
_skills_cache: Optional[dict] = "unloaded"


def _operator_ranges() -> dict:
    """Load derived operator range grids (empty dict if the artifact is absent)."""
    global _ranges_cache
    if _ranges_cache != "unloaded":
        return _ranges_cache
    try:
        with open(RANGES_PATH, encoding="utf-8") as fh:
            _ranges_cache = json.load(fh).get("operators", {})
    except FileNotFoundError:
        _ranges_cache = {}
    return _ranges_cache


def _world_range_cells(name: str) -> Optional[set]:
    """Mirror the official forward-facing grid into single-lane world offsets.

    Official range cells are (row, col) with col+ pointing toward the red gate.
    In our one-lane world the red gate sits at the low-x side while allies are
    placed at higher x, so an enemy ahead lies on the ally's NEGATIVE col side.
    We therefore map (r, c) -> (r, -c); row is the cross-lane axis and is kept.
    Returns None when no real grid exists so the kernel falls back to its
    Euclidean range_radius rule instead of fabricating a shape.
    """
    rec = _operator_ranges().get(name)
    if not rec or not rec.get("range_cells"):
        return None
    return {(int(r), -int(c)) for r, c in rec["range_cells"]}


def _operator_skills() -> dict:
    """Load derived burst-skill table (operator name -> record), {} if absent."""
    global _skills_cache
    if _skills_cache != "unloaded":
        return _skills_cache
    try:
        with open(SKILLS_PATH, encoding="utf-8") as fh:
            _skills_cache = json.load(fh).get("operators", {})
    except FileNotFoundError:
        _skills_cache = {}
    return _skills_cache

_enemy_attack_cache: Optional[dict] = "unloaded"


def _enemy_attack_index() -> dict:
    """Load the derived enemy_attack table (enemy_id -> full attack record).

    Tolerates a missing artifact by returning {} so callers degrade to the
    non-attacking first cut instead of crashing.
    """
    global _enemy_attack_cache
    if _enemy_attack_cache != "unloaded":
        return _enemy_attack_cache
    try:
        with open(ENEMY_ATTACK_PATH, encoding="utf-8") as fh:
            _enemy_attack_cache = json.load(fh).get("enemies", {})
    except FileNotFoundError:
        _enemy_attack_cache = {}
    return _enemy_attack_cache


_enemy_skill_cache: Optional[dict] = "unloaded"


def _enemy_skill_index() -> dict:
    """Load derived enemy skill bursts (enemy_id -> record), {} if absent."""
    global _enemy_skill_cache
    if _enemy_skill_cache != "unloaded":
        return _enemy_skill_cache
    try:
        with open(ENEMY_SKILLS_PATH, encoding="utf-8") as fh:
            _enemy_skill_cache = json.load(fh).get("enemies", {})
    except FileNotFoundError:
        _enemy_skill_cache = {}
    return _enemy_skill_cache


def _hp_multiplier(st) -> float:
    level = getattr(st, "regulation_level", None)
    return rhp.regulation_hp_multiplier(level) if isinstance(level, int) else 1.0


def spawns_to_specs(level: dict) -> List[SpawnSpec]:
    """Translate one level's spawn rows into kernel SpawnSpec lines."""
    specs = []
    for sp in level.get("spawns", []):
        specs.append(SpawnSpec(
            start_time=float(sp["first_spawn_t"]),
            enemy_key=sp["enemy_id"],
            count=int(sp["count"]),
            interval=float(sp.get("interval", 0.0)),
            route_index=int(sp.get("route_index", 0)),
            travel_time=float(sp.get("travel_t", 0.0)),
        ))
    return specs


def _spawn_lookup(level: dict) -> Dict[str, dict]:
    return {sp["enemy_id"]: sp for sp in level.get("spawns", [])}


def make_enemy_factory(level: dict, hp_mult: float, attack_index: dict,
                       needs_review: List[str], skill_index: dict = None):
    """Build the kernel spawn factory from real spawn rows + attack table."""
    lookup = _spawn_lookup(level)

    def factory(enemy_key, ev):
        sp = lookup.get(enemy_key)
        if sp is None:
            needs_review.append("spawn row missing for %s" % enemy_key)
            return None
        atk_rec = attack_index.get(enemy_key) or {}
        if not atk_rec:
            needs_review.append("no attack table entry for %s; non-attacking" % enemy_key)
        atk = float(atk_rec.get("atk", 0.0) or 0.0)
        bat = float(atk_rec.get("base_attack_time", 1.0) or 1.0)
        base = BaseStats(
            atk=atk,
            defense=float(sp.get("level0_def", 0.0)),
            max_hp=float(sp["level0_hp"]) * hp_mult,
            res=float(sp.get("level0_res", 0.0)),
            base_bat=bat,
            move_speed=float(sp.get("move_speed", 0.0)),
        )
        unit = Unit("e_%s_%d" % (enemy_key, ev.seq), sp.get("enemy_name", enemy_key),
                    "enemy", "enemy", base)
        unit.is_flying = (sp.get("motion") == "FLY")
        unit.ground = not unit.is_flying
        # Enemy attack behaviour from the derived official table.
        unit.deals_damage = bool(atk_rec.get("deals_damage", False))
        unit.enemy_range = float(atk_rec.get("range_radius", 0.0) or 0.0)
        # Official table has no phys/arts normal-attack type; assume physical
        # (the assumption is recorded in enemy_attack _meta.needs_review).
        unit.damage_family = kdamage.PHYS
        # Enemies enter on the single modelled lane; red gate at x = 0.
        unit.x = 0.0
        unit.y = float(LANE_ROW)
        # Periodic AoE skill bursts (phys or arts family from enemy_skills.json).
        skill_rec = skill_index.get(enemy_key)
        if skill_rec and skill_rec.get("bursts"):
            unit.aoe_bursts = [
                {"cooldown": float(b["cooldown"]),
                 "atk_scale": float(b["atk_scale"]),
                 "range_radius": float(b["range_radius"]),
                 "damage_family": b.get("damage_family", "phys"),
                 "_cd": float(b.get("initial_cooldown", 0.0))}
                for b in skill_rec["bursts"]
            ]
        return unit

    return factory


def board_to_allies(st, ds, metrics, needs_review: List[str]) -> List[Unit]:
    """Translate board operators into kernel ally Units with real buffs."""
    allies = []
    for bu in st.board:
        rec = metrics.get(bu.name)
        if not rec:
            needs_review.append("no combat metrics for operator %s" % bu.name)
            continue
        block = (rec.get("elite") if getattr(bu, "elite", False) else None) \
            or rec.get("initial") or {}
        if not block:
            needs_review.append("no panel for operator %s" % bu.name)
            continue
        interval = block.get("attack_interval")
        atk = block.get("atk_with_trust")
        if not isinstance(interval, (int, float)) or not isinstance(atk, (int, float)):
            needs_review.append("incomplete panel for operator %s" % bu.name)
            continue

        op = ds.operator(bu.name)
        prof = (op or {}).get("prof", "")
        is_ranged = (op or {}).get("position") == "远程位"
        family = PROFESSION_FAMILY.get(prof, kdamage.PHYS)
        block_cnt = 0 if is_ranged else PROFESSION_BLOCK.get(prof, 1)

        # Real tile-based range (facing already mirrored to world offsets).
        # Fall back to the coarse Euclidean radius only when the derived range
        # artifact is absent for this operator, and flag it for review.
        range_rec = _operator_ranges().get(bu.name)
        world_cells = _world_range_cells(bu.name)
        if world_cells is None:
            needs_review.append("no real range grid for %s; Euclidean fallback" % bu.name)
            radius = 3.0 if is_ranged else 1.0
        else:
            radius = float(range_rec.get("forward_reach", 1) or 0)

        eff_hp = block.get("effective_hp") or {}
        base = BaseStats(
            atk=float(atk),
            defense=float(eff_hp.get("def", 0.0) or 0.0),
            max_hp=float(eff_hp.get("raw_hp", 1.0) or 1.0),
            res=float(eff_hp.get("res", 0.0) or 0.0),
            base_bat=float(interval),
            block_cnt=block_cnt,
            range_radius=radius,
        )
        unit = Unit("op_%s" % bu.name, bu.name, "ally", "op", base)
        unit.damage_family = family
        unit.ground = not is_ranged
        unit.block_fly = bool((op or {}).get("anti_air"))
        # None keeps the kernel on its legacy Euclidean rule (see above).
        unit.range_cells = world_cells

        # Apply bond / per-stack / equipment / elite scaling via the kernel's
        # own modifier buckets so the BAT/ASPD interval rule stays authoritative.
        mult = buffs.operator_damage_multiplier(ds, st, bu.name)
        if mult["atk_mult"] != 1.0:
            unit.add_atk_mul(float(mult["atk_mult"]))
        aspd_mult = float(mult["aspd_mult"])
        if aspd_mult != 1.0:
            unit.add_aspd((aspd_mult - 1.0) * 100.0)
        allies.append(unit)
    return allies


def _deploy_allies(battle: Battle, allies: List[Unit]):
    """Place blockers on the lane front and ranged units behind them."""
    melee = [u for u in allies if u.ground]
    ranged = [u for u in allies if not u.ground]
    # Stack melee blockers along the lane row, distinct tiles so occupancy holds.
    for i, u in enumerate(melee):
        battle.add_ally(u, LANE_ROW, MELEE_COL + i)
    for i, u in enumerate(ranged):
        battle.add_ally(u, LANE_ROW, max(1, RANGED_COL - i))


def build_battle(st, ds, profiles=None, metrics=None, doc: Optional[dict] = None):
    """Assemble a ready-to-run Battle from a GameState, or None if unresolved."""
    from .. import effdps
    if not st.board:
        return None
    mode = clear_margin.resolve_mode(st)
    if mode is None:
        return None
    doc = doc or clear_margin.load_waves()
    stem = clear_margin.resolve_level_stem(doc, mode, st.round)
    if stem is None:
        return None
    level = doc.get("level_stems", {}).get(stem)
    if not level or not level.get("spawns"):
        return None

    if metrics is None:
        metrics = effdps.load_combat_metrics()
    if profiles is None:
        profiles = effdps.load_damage_profiles()

    needs_review: List[str] = []
    approximations: List[str] = []
    hp_mult = _hp_multiplier(st)

    # Guard the single movement constant against drifting between the two
    # modules: every observed level currently uses moveMultiplier == MOVE_SCALE.
    mm = float(level.get("move_multiplier", MOVE_SCALE))
    if abs(mm - MOVE_SCALE) > 1e-9:
        approximations.append(
            "level move_multiplier %.3f != kernel MOVE_SCALE %.3f; kernel "
            "constant used" % (mm, MOVE_SCALE))
    approximations.append("routes folded to a single lane (per-route distance "
                          "ignored)")
    approximations.append("attack range uses real operator_ranges grids, "
                          "facing mirrored toward the red gate (orientation "
                          "pending in-game verification)")
    approximations.append("block count uses coarse profession defaults, not "
                          "per-operator block data")
    approximations.append("enemy attacks are real (atk/interval/reach) but "
                          "assumed physical; the unpacked table has no phys/arts "
                          "normal-hit type, and enemy skill bursts are not driven")

    specs = spawns_to_specs(level)
    attack_index = _enemy_attack_index()
    skill_index = _enemy_skill_index()
    battle = Battle(rows=12, cols=20,
                    time_limit=float(level.get("clear_window_t", 60.0)) + 1.0,
                    scheduler=kernel.WaveScheduler(specs))
    battle.set_spawn_factory(make_enemy_factory(level, hp_mult, attack_index,
                                                needs_review, skill_index))
    battle.set_front_capacity(sum(int(s.count) for s in specs))

    allies = board_to_allies(st, ds, metrics, needs_review)
    if not allies:
        return None
    _deploy_allies(battle, allies)
    # Attach deterministic timed burst skills (auto-recover SP). Operators whose
    # skills are DoT/control/attack-recovery have no burst_skill and keep doing
    # plain basic attacks, exactly as the data builder classified them.
    skill_index = _operator_skills()
    attached = 0
    for u in allies:
        spec = (skill_index.get(u.name) or {}).get("burst_skill")
        if spec:
            battle.attach_skill(u, spec)
            attached += 1
    approximations.append("ally burst skills: %d/%d board ops drive a timed "
                          "ATK-up skill (auto SP); DoT/control/attack-recovery "
                          "skills not modelled" % (attached, len(allies)))
    return {
        "battle": battle,
        "stem": stem,
        "mode": mode,
        "hp_multiplier": round(hp_mult, 4),
        "approximations": approximations,
        "needs_review": needs_review,
    }


def simulate(st, ds, profiles=None, metrics=None, doc: Optional[dict] = None,
             max_seconds: float = 3600.0):
    """Run the discrete simulation and return a battle_sim record.

    Consumed by clear_margin.apply_reservoir_pressure (蓄水池 → effective margin).
    """
    assembled = build_battle(st, ds, profiles, metrics, doc)
    if assembled is None:
        return None
    battle = assembled.pop("battle")
    result = battle.run(max_seconds=max_seconds)
    ally_accounting = [
        {"name": u.name, "attacks": u.account.get("attacks", 0),
         "kills": u.account.get("kills", 0), "dmg": round(u.account.get("dmg", 0.0), 1)}
        for u in battle.allies
    ]
    return {
        "mode": assembled["mode"],
        "level_stem": assembled["stem"],
        "hp_multiplier": assembled["hp_multiplier"],
        "result": result,
        "allies": ally_accounting,
        "skill_cycles": battle.skill_driver.snapshot(),
        "approximations": assembled["approximations"],
        "needs_review": assembled["needs_review"],
    }
