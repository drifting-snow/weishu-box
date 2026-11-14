# -*- coding: utf-8 -*-
"""Damage settlement trunk (clean-room).

Wraps the proven stage-B formulas in advisor/damage_calc.py and adds the two
layers the reference pipeline applies around mitigation:
  - penetration: fixed ignore first, then percent ignore;
  - target taken-multipliers (fragile / type-specific vulnerability).

Pure functions only; no HP mutation, no RNG, no hooks. Callers own HP bookkeeping.
"""

from ..damage_calc import MIN_DAMAGE_RATIO, RES_CAP
from ..damage_type import PHYSICAL, ARTS, TRUE, HEAL

# Damage family identifiers used inside the battle kernel.
PHYS = "phys"
ARTS_T = "arts"
TRUE_T = "true"

_FAMILY = {PHYSICAL: PHYS, ARTS: ARTS_T, TRUE: TRUE_T, HEAL: None}


def family_of(damage_type):
    """Map a stage-B damage_type label to the kernel family (None for heal)."""
    return _FAMILY.get(damage_type)


def mitigate(amount, family, target_stats, src_stats=None):
    """Mitigate one hit of pre-mitigation `amount`.

    target_stats / src_stats are battle.unit.Stats aggregated snapshots.
    Penetration order: subtract fixed ignore, then apply percent ignore.
    """
    amount = float(amount)
    floor = amount * MIN_DAMAGE_RATIO
    src = src_stats

    if family == PHYS:
        d = target_stats.defense
        if src is not None:
            d = max(0.0, d - src.def_ignore_flat) * (1.0 - src.def_ignore_pct)
        return max(amount - d, floor)

    if family == ARTS_T:
        r = target_stats.res
        if src is not None:
            r = max(0.0, r - src.res_ignore_flat) * (1.0 - src.res_ignore_pct)
        r = min(max(r, 0.0), RES_CAP)
        # Arts also keeps the 5% minimum-damage floor.
        return max(amount * (1.0 - r / 100.0), floor)

    if family == TRUE_T:
        return amount

    # Unknown / heal: no mitigation at this layer.
    return amount


def apply_taken_multipliers(base, family, target):
    """Multiply by the target's generic and type-specific taken multipliers.

    `target` may carry plain attributes dmg_taken_mul / phys_taken_mul /
    arts_taken_mul / true_taken_mul (default 1.0). Kept off Stats for now so the
    first cut stays lean; buff layer can attach them to the Unit later.
    """
    generic = float(getattr(target, "dmg_taken_mul", 1.0) or 1.0)
    if family == PHYS:
        typed = float(getattr(target, "phys_taken_mul", 1.0) or 1.0)
    elif family == ARTS_T:
        typed = float(getattr(target, "arts_taken_mul", 1.0) or 1.0)
    elif family == TRUE_T:
        typed = float(getattr(target, "true_taken_mul", 1.0) or 1.0)
    else:
        typed = 1.0
    return base * generic * typed


def deal_hit(source, target, amount, family):
    """Full trunk: mitigate -> taken multipliers -> HP bookkeeping.

    Returns the HP actually removed (0 if the target is not damageable). Source
    may be None for sourceless damage; then no penetration is applied.
    """
    if target is None or not getattr(target, "alive", False) \
            or not getattr(target, "deployed", True):
        return 0.0
    src_stats = source.stats if source is not None else None
    base = mitigate(amount, family, target.stats, src_stats)
    final = apply_taken_multipliers(base, family, target)
    final = max(0.0, final)
    if final <= 0:
        return 0.0
    target.hp -= final
    target.account["taken"] = target.account.get("taken", 0.0) + final
    if source is not None:
        source.account["dmg"] = source.account.get("dmg", 0.0) + final
        source.account["attacks"] = source.account.get("attacks", 0) + 1
    if target.hp <= 0:
        target.hp = 0
        target.alive = False
        if source is not None:
            source.account["kills"] = source.account.get("kills", 0) + 1
    return final
