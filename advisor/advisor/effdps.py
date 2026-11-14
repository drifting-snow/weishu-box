# -*- coding: utf-8 -*-
"""Effective-DPS (armor fit) for shop decisions, backed by REAL enemy stats.

History: this module used to discount physical/arts dealers through three
guessed resistance BANDS per tactical category (BAND_DEF/BAND_RES). Those were
semantic guesses, not measurements, and the official level-0 enemy stats proved
them wrong in both directions -- notably refraction enemies are HIGH-def /
LOW-res (worst def 1100, worst res 20), the reverse of the old "low def / high
res -> use physical" band.

Current design (no fabricated enemy numbers):
  data/enemy_stats.json (built from the official unpacked enemy_database.json by
  our own tools/build_enemy_stats.py) holds every enemy's real level-0 def/res
  plus a per-trait-category worst-case aggregate. GameState only carries the
  wave's trait categories, so we resolve the picture to the tankiest real def /
  res reachable under those categories (the same "must hold against the worst
  enemy" rule the old bands tried to express, now from measured values).

  The mitigation factor is computed with the continuous stage-B formulas instead
  of a discrete matrix column, so def above the matrix's 1000 sampling cap is
  handled correctly (it simply lands on the 5% minimum-damage floor):
      physical : physical_hit(atk, def) / physical_hit(atk, 0)
      arts     : arts_hit(atk, res)     / arts_hit(atk, 0)   # = 1 - res/100
      true     : 1.0 ; healing -> None (not armor-fit).

DEF/RES are static level-0 values (no per-regulation-level multiplier is
published); enemy HP is scaled separately in advisor/regulation_hp.py.
"""
import json
import os

from . import damage_calc as dc

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data")

# Clamp the factor to the game's 5% minimum-damage floor so a hopeless mismatch
# is still a small positive number, never zero/negative.
MIN_FACTOR = dc.MIN_DAMAGE_RATIO

_enemy_stats_cache = None


def _load(name):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def load_damage_profiles():
    return {o["name"]: o for o in _load("operator_damage_profiles.json")["operators"]}


def load_combat_metrics():
    return {o["name"]: o for o in _load("operator_combat_metrics.json")["operators"]}


def _enemy_stats():
    global _enemy_stats_cache
    if _enemy_stats_cache is None:
        _enemy_stats_cache = _load("enemy_stats.json")
    return _enemy_stats_cache


def enemy_resistance(enemy_types):
    """Worst-case real (def, res) across the wave's trait categories.

    Takes the maximum real def and res reachable under any category in the
    picture, so the fit score holds against the tankiest enemy that can spawn.
    Returns None when there is no usable enemy picture (caller stays armor-
    neutral rather than guessing).
    """
    if not enemy_types:
        return None
    worst = _enemy_stats().get("category_worst", {})
    worst_def = 0
    worst_res = 0.0
    seen = False
    for key in enemy_types:
        cat = worst.get(key)
        if not cat:
            continue
        seen = True
        worst_def = max(worst_def, cat["worst_def"])
        worst_res = max(worst_res, cat["worst_res"])
    if not seen:
        return None
    return worst_def, worst_res


def _representative_skill(profiles_by_name, name):
    """Pick the skill profile whose matrix represents this operator.

    14 operators mix physical/arts/true across skills, so the first skill is not
    always representative. Prefer the first matrix-bearing skill whose damage
    family matches the operator's baseline_damage_type (138/141 match); fall
    back to the first matrix-bearing skill, then None. A true-damage skill
    carries an axis=='none' matrix and is returned for the caller to treat as
    factor 1.0.
    """
    op = profiles_by_name.get(name)
    if not op:
        return None
    initial = op.get("initial", {})
    skills = initial.get("skill_profiles", [])
    baseline = initial.get("baseline_damage_type")
    fallback = None
    for sp in skills:
        mat = sp.get("damage_matrix")
        if not mat or mat.get("axis") not in ("defense", "resistance", "none"):
            continue
        if fallback is None:
            fallback = sp
        if baseline and sp.get("damage_type") == baseline:
            return sp
    return fallback


def mitigation_factor(profiles_by_name, name, resistance):
    """Fraction of raw damage retained against the real (def, res) picture.

    Returns a float in [MIN_FACTOR, 1.0], or None for heal / no data (caller
    treats None as armor-neutral).
    """
    if resistance is None:
        return None
    sp = _representative_skill(profiles_by_name, name)
    if sp is None:
        return None
    damage_type = sp.get("damage_type")
    mat = sp.get("damage_matrix", {})
    atk = sp.get("skill_attack_power")

    if damage_type == "true" or mat.get("axis") == "none":
        return 1.0
    if damage_type == "heal" or not isinstance(atk, (int, float)) or atk <= 0:
        return None

    if mat.get("axis") == "defense":
        defense = resistance[0]
        factor = dc.physical_hit(atk, defense) / dc.physical_hit(atk, 0)
    elif mat.get("axis") == "resistance":
        res = resistance[1]
        factor = dc.arts_hit(atk, res) / dc.arts_hit(atk, 0)
    else:
        return None
    return max(MIN_FACTOR, min(1.0, factor))


def raw_dps(metrics_by_name, name):
    """Base (unmitigated) DPS from combat metrics, or None if unavailable."""
    op = metrics_by_name.get(name)
    if not op:
        return None
    dps = op.get("initial", {}).get("base_dps")
    return float(dps) if isinstance(dps, (int, float)) and dps > 0 else None


def effective_dps(profiles_by_name, metrics_by_name, name, enemy_types):
    """(eff_dps, factor, raw) for an operator against this enemy picture.

    Any component may be None when data is missing; callers must handle None
    gracefully (armor-neutral scoring rather than a fabricated number).
    """
    resistance = enemy_resistance(enemy_types)
    factor = mitigation_factor(profiles_by_name, name, resistance)
    raw = raw_dps(metrics_by_name, name)
    if factor is None or raw is None:
        return None, factor, raw
    return round(raw * factor, 2), factor, raw
