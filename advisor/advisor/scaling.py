# -*- coding: utf-8 -*-
"""Standalone scaling/multiplier layer (pure logic, no I/O, engine-independent).

Two in-mode scaling effects that the fixed-level panels (stage A/B) do not
include are handled here as explicit multipliers, kept completely separate from
the decision engine (advisor/engine.py never imports this module):

  1. Enemy scaling with protocol (dispatch) level.
  2. Operator panel scaling with bond stacks (+ account-practice bonus).

Design rule: only published numbers are hard-coded. Where the local wiki gives
no per-level value, the layer exposes an explicit, documented configuration slot
that defaults to neutral (1.0 / +0) instead of inventing a coefficient, so any
future measured value can be dropped in without touching call sites or tests of
the neutral path.

Sources (see README / dataset docs 07, 08):
  * DISPATCH_LEVEL_COEFF  : BWiki mechanism doc 08, AC-SP-1..20 difficulty table.
  * ALLIANCE_COEFF        : doc 08, four alliance (co-op) difficulties.
  * ACCOUNT_PRACTICE_BONUS: doc 07, extra % from the player's own account growth.
  * bond attack rules     : data/bond_scaling.json (parsed 作战能力 entries).

NOTE on enemy resistance: the local wiki does NOT publish a per-level resistance
table (only total difficulty coefficient and operator-side "ignore X RES").
Enemy RES growth is therefore a configuration slot (ENEMY_RES_DELTA), neutral by
default and clearly marked pending measured data -- never a fabricated curve.
"""

# --- Enemy side -----------------------------------------------------------

# Protocol (independent simulation) level 1..20 -> total enemy coefficient.
# From doc 08 "规程等级 1–20" table (some levels share a coefficient).
DISPATCH_LEVEL_COEFF = {
    1: 1.00, 2: 1.05, 3: 1.10, 4: 1.15, 5: 1.20,
    6: 1.25, 7: 1.30, 8: 1.30, 9: 1.35, 10: 1.35,
    11: 1.40, 12: 1.40, 13: 1.45, 14: 1.45,
    15: 1.50, 16: 1.50, 17: 1.50, 18: 1.50, 19: 1.50, 20: 1.50,
}

# Alliance (co-op) difficulty -> total enemy coefficient (doc 08 section 3).
ALLIANCE_COEFF = {
    "standard": 1.00,   # 标准
    "hard_abyss": 1.20, # 险境
    "desperate": 1.35,  # 绝境
    "ultimate": 1.50,   # 终极
}

# Enemy per-level RES/DEF growth. NOT published in the local wiki -> neutral
# placeholder keyed by dispatch level. Fill with measured values when available;
# every level absent here resolves to 0 via enemy_resistance_delta().
# Shape: {level: additive_resistance_points}. Intentionally empty by default.
ENEMY_RES_DELTA = {}
ENEMY_DEF_DELTA = {}

# Difficulty coefficient applies to enemy HP/ATK (the published axis). Kept as a
# single multiplier; resistance/defense deltas are additive points handled above.
def enemy_difficulty_coeff(dispatch_level=1, alliance=None):
    """Total enemy stat coefficient for a protocol level / alliance difficulty."""
    if alliance is not None and alliance in ALLIANCE_COEFF:
        return ALLIANCE_COEFF[alliance]
    return DISPATCH_LEVEL_COEFF.get(int(dispatch_level), 1.0)


def enemy_resistance_delta(dispatch_level=1, table=None):
    """Additive enemy RES points at a level. 0 until measured data is supplied."""
    src = ENEMY_RES_DELTA if table is None else table
    return src.get(int(dispatch_level), 0)


def enemy_defense_delta(dispatch_level=1, table=None):
    """Additive enemy DEF points at a level. 0 until measured data is supplied."""
    src = ENEMY_DEF_DELTA if table is None else table
    return src.get(int(dispatch_level), 0)


def scale_enemy(base_hp, base_atk, dispatch_level=1, alliance=None,
                res_delta_table=None, def_delta_table=None):
    """Apply published difficulty coefficient + optional additive DEF/RES.

    Returns a dict; RES/DEF deltas default to 0 (no published per-level table).
    """
    coeff = enemy_difficulty_coeff(dispatch_level, alliance)
    return {
        "hp": round(base_hp * coeff, 2),
        "atk": round(base_atk * coeff, 2),
        "difficulty_coeff": coeff,
        "res_delta": enemy_resistance_delta(dispatch_level, res_delta_table),
        "def_delta": enemy_defense_delta(dispatch_level, def_delta_table),
    }


# --- Operator side --------------------------------------------------------

# Account-practice extra bonus (doc 07): additive % to ATK/DEF/HP by the owner's
# own account growth. Mode fixes the in-mode level and trust at 100%; this table
# is the residual account-side bonus, applied additively as a multiplier.
# Key -> (atk%, def%, hp%)
ACCOUNT_PRACTICE_BONUS = {
    "e1_lvl1":          (5, 0, 0),    # 精一 Lv.1
    "e1_lvl1_trust":    (5, 5, 0),    # 精一 Lv.1 (满信赖另一档)
    "e2_lvl1":          (10, 5, 5),   # 精二 Lv.1
    "e2_lvl60":         (10, 10, 10),# 精二 Lv.60
}


def account_practice_multiplier(tier="e2_lvl60"):
    """(atk_mult, def_mult, hp_mult) from the account-practice bonus table."""
    atk_pct, def_pct, hp_pct = ACCOUNT_PRACTICE_BONUS.get(
        tier, (0, 0, 0))
    return (1 + atk_pct / 100.0, 1 + def_pct / 100.0, 1 + hp_pct / 100.0)


def bond_attack_multiplier(rule, active_stacks, form="advanced"):
    """ATK multiplier from a bond_scaling rule at a given active stack count.

    rule is the per-operator {"basic": {...}, "advanced": {...}} view, each with
    stack_step and atk_pct_per_step. Missing form -> neutral 1.0.
    multiplier = 1 + (stacks // step) * pct/100.
    """
    if not rule:
        return 1.0
    view = rule.get(form) or rule.get("basic")
    if not view:
        return 1.0
    step = max(int(view["stack_step"]), 1)
    pct = float(view["atk_pct_per_step"])
    ticks = int(active_stacks) // step
    return round(1.0 + ticks * pct / 100.0, 6)


# --- Core/attached bond panel formulas (PRTS, linear in stacks) ----------
# Loaded by the caller from data/bond_panel_formulas.json; kept out of this
# pure module so the numbers stay data-driven and source-cited.

def panel_multiplier_from_formula(rule, stacks):
    """Multiplier for one bond-panel formula at a stack count.

    additive_pct: effect is +(base + per_stack*stacks)% -> 1 + pct/100.
    total_pct   : effect is "raise to (base+..)%"      -> pct/100.
    """
    pct = float(rule["base"]) + float(rule["per_stack"]) * int(stacks)
    if rule["form"] == "additive_pct":
        return 1.0 + pct / 100.0
    if rule["form"] == "total_pct":
        return pct / 100.0
    return 1.0


def _formula_applies(rule, operator_bonds, is_ranged, conditions_met):
    scope = rule.get("scope")
    if scope == "all":
        pass
    elif scope == "ranged":
        if not is_ranged:
            return False
    elif scope == "bond":
        if rule["bond"] not in operator_bonds:
            return False
    cond = rule.get("condition")
    if cond and cond not in conditions_met:
        return False  # conditional buff (equip/skill window/cold) not assumed
    return True


def bond_panel_multipliers(formulas, active_stacks, operator_bonds,
                           is_ranged=False, conditions_met=None):
    """Combine every applicable bond-panel formula into atk/def/hp/damage mult.

    formulas       : the "formulas" list from bond_panel_formulas.json
    active_stacks  : {bond_name: stack_count} for ACTIVATED bonds only
    operator_bonds : bond names this operator belongs to
    is_ranged      : high-ground (ranged) operator, for scope="ranged"
    conditions_met : set of condition strings currently satisfied; conditional
                     rules are skipped unless their condition is declared.

    Per PRTS, bond stat bonuses are direct MULTIPLIERS, so applicable rules on
    the same stat multiply together. Returns neutral 1.0 where nothing applies.
    """
    conditions_met = conditions_met or set()
    mult = {"atk": 1.0, "def": 1.0, "hp": 1.0, "damage": 1.0}
    applied, skipped = [], []
    for rule in formulas:
        bond = rule["bond"]
        if bond not in active_stacks:
            continue
        if not _formula_applies(rule, operator_bonds, is_ranged, conditions_met):
            skipped.append(bond + ":" + str(rule.get("stat")))
            continue
        m = panel_multiplier_from_formula(rule, active_stacks[bond])
        stat = rule["stat"]
        targets = ("atk", "hp") if stat == "atk_hp" else (stat,)
        for t in targets:
            if t in mult:
                mult[t] *= m
        applied.append("%s:%s=%.4f" % (bond, stat, m))
    return {
        "atk_multiplier": round(mult["atk"], 6),
        "def_multiplier": round(mult["def"], 6),
        "hp_multiplier": round(mult["hp"], 6),
        "damage_multiplier": round(mult["damage"], 6),
        "applied": applied, "skipped_conditional": skipped,
    }


def scale_operator_panel(base_atk, base_def=0, base_hp=0, bond_rule=None,
                         active_stacks=0, form="advanced",
                         account_tier=None):
    """Apply bond attack multiplier + optional account-practice bonus.

    Bond scaling only has a published ATK rule in the local wiki, so DEF/HP bond
    multipliers stay 1.0; account-practice bonus can raise all three when a tier
    is supplied. Pure function, returns the adjusted panel (no mutation).
    """
    atk_mult = bond_attack_multiplier(bond_rule, active_stacks, form)
    def_mult = hp_mult = 1.0
    if account_tier:
        a, d, h = account_practice_multiplier(account_tier)
        atk_mult *= a
        def_mult, hp_mult = d, h
    return {
        "atk": round(base_atk * atk_mult, 2),
        "def": round(base_def * def_mult, 2),
        "hp": round(base_hp * hp_mult, 2),
        "atk_multiplier": round(atk_mult, 6),
        "def_multiplier": round(def_mult, 6),
        "hp_multiplier": round(hp_mult, 6),
    }
