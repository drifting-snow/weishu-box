# -*- coding: utf-8 -*-
"""Act3 "Guard Protocol: Regulation" enemy LEADER HP curve (self-owned).

Pure stdlib, no I/O, no third-party/GPL code. The coefficients are game facts
that were independently reverse-derived from the public PRTS user-measured
leader-HP table (regulation levels 1..20). All ten sampled leaders share ONE
relative coefficient (min == max across columns, reconstruction error 0.000%),
so this is a single global multiplier on each enemy's own level-1 base HP,
not a per-enemy table.

Exact closed form (fraction of the L1 base HP):
    L1 ............................. 1
    L2..L8  : +1/3 per level  -> L8  = 10/3
    L9..L14 : +5/6 per level  -> L14 = 25/3
    L15..L20: +25/27 per level-> L20 = 125/9

Coverage boundary (do not over-extend):
  * HP ONLY. Never apply this curve to ATK / DEF / RES.
  * ATK per-level scaling has no published act3 source: keep neutral and flag
    needs_review instead of inventing a coefficient.
  * DEF / RES are treated as static level-0 database values plus boolean
    traits (refraction / invisibility); no per-level multiplier exists in the
    measured data, so none is provided here.

Difficulty modes anchor to the same curve (verified identical coefficients):
  standard = L1, hard = L8, desperate = L14, ultimate = L20.
Quick simulation (jisu moni) = 0.8 * the L1 value, uniform across leaders.
"""
from fractions import Fraction

MIN_LEVEL = 1
MAX_LEVEL = 20

# (segment end level, additive step per level as an exact fraction of L1 base)
_SEGMENTS = ((8, Fraction(1, 3)),
             (14, Fraction(5, 6)),
             (20, Fraction(25, 27)))

# Difficulty mode -> regulation level anchor on the same curve.
DIFFICULTY_ANCHOR = {
    "standard": 1,    # biao zhun mo ni
    "hard": 8,        # xian jing mo ni
    "desperate": 14,  # jue jing mo ni
    "ultimate": 20,   # zhong ji mo ni
}

# Quick simulation is a uniform 0.8x of the L1 value.
QUICK_SIM_FACTOR = Fraction(4, 5)


def _build_table():
    table = {1: Fraction(1)}
    level = 1
    value = Fraction(1)
    for end, step in _SEGMENTS:
        while level < end:
            level += 1
            value += step
            table[level] = value
    return table


_HP_MULTIPLIER = _build_table()


def is_supported_level(level):
    """True for regulation levels 1..20."""
    try:
        return int(level) in _HP_MULTIPLIER
    except (TypeError, ValueError):
        return False


def regulation_hp_multiplier(level=1):
    """Relative HP multiplier for a regulation level.

    Returns 1.0 for an unknown / out-of-range level (neutral) rather than
    raising, so callers never crash on a missing level; validate explicitly
    with is_supported_level() when a hard guarantee is needed.
    """
    frac = _HP_MULTIPLIER.get(int(level)) if _safe_int(level) else None
    return 1.0 if frac is None else float(frac)


def regulation_hp(base_hp, level=1):
    """Scale a leader's level-1 base HP to a regulation level."""
    return float(base_hp) * regulation_hp_multiplier(level)


def difficulty_hp_multiplier(mode):
    """HP multiplier for a difficulty mode; neutral 1.0 for an unknown mode."""
    anchor = DIFFICULTY_ANCHOR.get(mode)
    return 1.0 if anchor is None else regulation_hp_multiplier(anchor)


def quick_sim_hp(base_hp):
    """Quick-simulation leader HP = 0.8 * the level-1 base."""
    return float(base_hp) * float(QUICK_SIM_FACTOR)


def multiplier_table():
    """Copy of the full L1..L20 multiplier table as floats (for inspection)."""
    return {lv: float(frac) for lv, frac in _HP_MULTIPLIER.items()}


def _safe_int(level):
    try:
        int(level)
        return True
    except (TypeError, ValueError):
        return False
