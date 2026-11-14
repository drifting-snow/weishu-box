# -*- coding: utf-8 -*-
"""Clean-room operator buff multipliers for stage-1 effective-DPS.

The base team DPS (operator_combat_metrics) is a bare E1/L55 panel: it ignores
elite promotion, bond (盟约) panel bonuses, bond per-stack attack rules, and
equipped items. This module computes those multipliers from act3 data so the
clear-margin estimate reflects the real board instead of a systematic lower bound.

Sources (all committed, MIT-clean data; no GPL code imported):
  * data/bond_panel_formulas.json  - PRTS 盟约记录 core/attached panel formulas
    (atk / hp / def / damage, additive_pct or total_pct, scoped bond/all/ranged)
  * data/bond_scaling.json         - per-operator "every N stacks +X% atk" rules
  * data/items_structured.json     - equipment stat_mods (atk_pct / aspd_*)

It deliberately does NOT import advisor.scaling (the retired act1/2 layer the
engine is guarded against); the small formula math is re-implemented here from
the same data. Only damage-affecting stats are returned; hp/def formulas are
read but not needed for the DPS estimate.

Everything degrades to neutral 1.0 when the optional inputs (bond_stacks,
equipment) are absent, so legacy states behave exactly as before.
"""
import json
import os
from typing import Dict, List, Optional, Tuple

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data")
_cache = {}


def _load(name):
    if name not in _cache:
        with open(os.path.join(DATA_DIR, name), encoding="utf-8") as fh:
            _cache[name] = json.load(fh)
    return _cache[name]


def active_bonds(ds, st) -> set:
    """Names of bonds currently activated by the board's distinct operators."""
    distinct: Dict[str, set] = {}
    for unit in st.board:
        op = ds.operator(unit.name)
        for b in (op["bonds"] if op else (unit.bonds or [])):
            distinct.setdefault(b, set()).add(unit.name)
    out = set()
    for bond, names in distinct.items():
        need = ds.bond_need(bond)
        if need and len(names) >= need:
            out.add(bond)
    return out


def _is_ranged(op) -> bool:
    # High-ground / ranged position. anti_air is a looser proxy; position is primary.
    if not op:
        return False
    return op.get("position") == "远程位" or bool(op.get("anti_air"))


def _panel_mult(rule: dict, stacks: int) -> float:
    """One bond-panel formula's multiplier at a stack count (clean-room math)."""
    pct = float(rule["base"]) + float(rule["per_stack"]) * int(stacks)
    if rule["form"] == "additive_pct":
        return 1.0 + pct / 100.0
    if rule["form"] == "total_pct":
        return pct / 100.0
    return 1.0


def _formula_applies(rule: dict, op_bonds, is_ranged: bool,
                     conditions_met: set) -> bool:
    scope = rule.get("scope")
    if scope == "ranged" and not is_ranged:
        return False
    if scope == "bond" and rule["bond"] not in op_bonds:
        return False
    # scope "all" applies to everyone.
    cond = rule.get("condition")
    if cond and cond not in conditions_met:
        return False
    return True


def _bond_panel_mult(ds, st, op_name, op, activated: set,
                     conditions_met: set) -> Tuple[float, List[str]]:
    formulas = _load("bond_panel_formulas.json")["formulas"]
    stacks_map = getattr(st, "bond_stacks", {}) or {}
    op_bonds = set(op.get("bonds", []) if op else [])
    ranged = _is_ranged(op)
    mult, notes = 1.0, []
    for rule in formulas:
        bond = rule["bond"]
        # only activated bonds apply; with no explicit stack count the base
        # (stack-0) panel bonus still counts, so stacks defaults to 0.
        if bond not in activated:
            continue
        if not _formula_applies(rule, op_bonds, ranged, conditions_met):
            continue
        if rule["stat"] not in ("atk", "damage"):  # hp/def do not change DPS
            continue
        stacks = int(stacks_map.get(bond, 0))
        m = _panel_mult(rule, stacks)
        mult *= m
        tag = ("@%d层" % stacks) if stacks else "(基础)"
        notes.append("%s%s x%.3f" % (bond, tag, m))
    return mult, notes


def _bond_scaling_mult(ds, st, op_name, activated: set) -> Tuple[float, List[str]]:
    rules = {o["name"]: o for o in _load("bond_scaling.json")["operators"]}
    entry = rules.get(op_name)
    if not entry:
        return 1.0, []
    stacks_map = getattr(st, "bond_stacks", {}) or {}
    scaling = entry.get("scaling", {})
    # advanced form is the promoted/end-game panel; fall back to basic.
    form = scaling.get("advanced") or scaling.get("basic")
    if not form or form["bond"] not in activated:
        return 1.0, []
    stacks = int(stacks_map.get(form["bond"], 0))
    if stacks <= 0:
        return 1.0, []  # per-stack rule has no stack-0 component
    ticks = stacks // int(form["stack_step"])
    if ticks <= 0:
        return 1.0, []
    mult = 1.0 + ticks * float(form["atk_pct_per_step"]) / 100.0
    return mult, ["%s逐层 x%.3f" % (form["bond"], mult)]


def _equipment_mult(ds, st, op_name) -> Tuple[float, float, List[str]]:
    """Return (atk_mult, aspd_mult) from equipped items' offensive stat_mods."""
    items = getattr(st, "equipment", {}) or {}
    names = items.get(op_name) or []
    if not names:
        return 1.0, 1.0, []
    atk_add = 0.0
    aspd_add_pct = 0.0
    used = []
    for nm in names:
        struct = ds.item_structured(nm)
        if not struct:
            continue
        mods = struct.get("stat_mods", {}) or {}
        if "atk_pct" in mods:
            atk_add += float(mods["atk_pct"])
        if "aspd_pct" in mods:
            aspd_add_pct += float(mods["aspd_pct"])
        if "aspd_flat" in mods:
            aspd_add_pct += float(mods["aspd_flat"])  # 1 aspd point ~= 1% attack speed
        if any(k in mods for k in ("atk_pct", "aspd_pct", "aspd_flat")):
            used.append(nm)
    return (1.0 + atk_add / 100.0, 1.0 + aspd_add_pct / 100.0, used)


def operator_damage_multiplier(ds, st, op_name: str,
                               conditions_met: Optional[set] = None):
    """Combined damage multiplier for one board operator.

    Returns a dict with atk_mult / aspd_mult / dps_mult and human notes. Neutral
    1.0 everywhere when the operator is unknown or no buff applies. Bond panel,
    per-stack bond rule, and equipment atk all multiply; aspd is folded into the
    final dps multiplier (DPS scales with both attack and attack speed).
    """
    op = ds.operator(op_name)
    activated = active_bonds(ds, st)
    conditions_met = set(conditions_met or [])
    # auto-satisfy the "carries equipment" condition when this unit has gear
    if (getattr(st, "equipment", {}) or {}).get(op_name):
        conditions_met.add("携带装备")

    atk_mult, notes = _bond_panel_mult(ds, st, op_name, op, activated, conditions_met)
    scale_mult, scale_notes = _bond_scaling_mult(ds, st, op_name, activated)
    atk_mult *= scale_mult
    notes += scale_notes

    eq_atk, eq_aspd, eq_notes = _equipment_mult(ds, st, op_name)
    atk_mult *= eq_atk
    if eq_notes:
        notes.append("装备%s x%.3f" % ("+".join(eq_notes), eq_atk * eq_aspd))

    return {
        "atk_mult": round(atk_mult, 4),
        "aspd_mult": round(eq_aspd, 4),
        "dps_mult": round(atk_mult * eq_aspd, 4),
        "activated_bonds": sorted(activated & set(op.get("bonds", []) if op else [])),
        "notes": notes,
    }
