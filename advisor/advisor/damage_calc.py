# -*- coding: utf-8 -*-
"""Stage-B damage settlement, break-armor line and tier matrix (pure logic).

Arknights damage formulas (public game mechanics, applied to the exact fixed-
level panels):

Physical per-hit (before any defense ignore):
    raw   = ATK - DEF
    final = max(raw, ATK * 0.05)          # 5% minimum-damage floor
So the "break-armor line" is the DEF at which the floor starts binding, i.e.
    DEF >= 0.95 * ATK  -> minimum damage; break point DEF_break = 0.95 * ATK.
The half-damage point is where ATK - DEF = 0.5 * ATK -> DEF_half = 0.5 * ATK.

Arts per-hit:
    final = ATK * (1 - RES/100), RES clamped to [0, 95]
    half-damage resistance is simply RES = 50.

True damage:
    final = ATK                          # ignores DEF and RES.

Healing is not reduced by DEF/RES and is reported separately (HPS already
computed in stage A).

Elemental damage is a secondary status handled in stage C; here it only rides
along as a flag, never folded into the physical/arts hit.
"""

from .damage_type import PHYSICAL, ARTS, TRUE, HEAL

# Standard sampling tiers chosen to cover the full ArkDPS slider range (0..1000
# DEF; RES capped at 95 in game). Kept in one place so validation can align.
DEF_TIERS = (0, 100, 200, 300, 400, 500, 600, 800, 1000)
RES_TIERS = (0, 10, 20, 30, 40, 50, 60, 70, 90)

MIN_DAMAGE_RATIO = 0.05
RES_CAP = 95.0


def physical_hit(atk, defense):
    """Physical damage of one hit after mitigation and the 5% floor."""
    floor = atk * MIN_DAMAGE_RATIO
    return max(atk - defense, floor)


def arts_hit(atk, resistance):
    """Arts damage of one hit; RES clamped to the game cap."""
    res = min(max(resistance, 0.0), RES_CAP)
    return atk * (1.0 - res / 100.0)


def true_hit(atk):
    """True damage ignores both DEF and RES."""
    return float(atk)


def hit_damage(atk, damage_type, defense=0, resistance=0):
    """Dispatch to the right per-hit formula; heal/unknown return None."""
    if damage_type == PHYSICAL:
        return physical_hit(atk, defense)
    if damage_type == ARTS:
        return arts_hit(atk, resistance)
    if damage_type == TRUE:
        return true_hit(atk)
    return None  # HEAL or unresolved -> not a damage number


def physical_break_lines(atk):
    """DEF thresholds: half-damage point and minimum-damage (break) point."""
    return {
        "half_damage_def": round(0.5 * atk, 2),
        "min_damage_def": round(0.95 * atk, 2),
        "min_damage_value": round(atk * MIN_DAMAGE_RATIO, 2),
    }


def arts_half_resistance():
    """RES at which arts damage is halved (constant 50)."""
    return 50


def damage_matrix(atk, damage_type, hit_count=1, targets=1):
    """Per-hit damage across the standard DEF/RES tiers for the damage family.

    Returns a dict keyed by the relevant axis. Physical sweeps DEF, arts sweeps
    RES, true is a single constant. Multiplied by hit_count*targets to express
    one full skill action's total at every tier.
    """
    mult = max(hit_count, 1) * max(targets, 1)
    if damage_type == PHYSICAL:
        rows = {str(d): round(physical_hit(atk, d) * mult, 2) for d in DEF_TIERS}
        return {"axis": "defense", "tiers": list(DEF_TIERS), "per_action_damage": rows,
                "break_lines": physical_break_lines(atk)}
    if damage_type == ARTS:
        rows = {str(r): round(arts_hit(atk, r) * mult, 2) for r in RES_TIERS}
        return {"axis": "resistance", "tiers": list(RES_TIERS), "per_action_damage": rows,
                "half_damage_resistance": arts_half_resistance()}
    if damage_type == TRUE:
        return {"axis": "none", "tiers": [],
                "per_action_damage": {"0": round(true_hit(atk) * mult, 2)}}
    return None
