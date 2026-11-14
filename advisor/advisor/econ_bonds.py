# -*- coding: utf-8 -*-
"""Economy-bond (经济羁绊) buy logic.

The three attached bonds 远见 / 奇迹 / 投资人 are economy engines rather than
combat payoffs, and all three explicitly activate from the reserve zone too
("整备区的干员也可用于激活盟约"), so they are worth holding even off-field.

Layer 1 (this module) is static and does NOT track bond stacks. It values:
  - whether buying this operator reaches the bond's activation headcount, and
  - how many rounds remain for the engine to pay off (the payback window).

The stack milestones (远见 80/150, 奇迹 100, 投资人 100) need a bond_stacks
field and are deliberately deferred to layer 2.

Base weights rank direct gold over probability/amplifier engines, matching the
agreed priority 远见 > 奇迹 ~ 投资人. Stdlib only, deterministic.
"""
from .item_economy import DEFAULT_TOTAL_ROUNDS
from . import stack_feasibility as sf

# bond name -> economy engine profile. `need` must match bonds.json activation
# headcount (asserted in tests). Weights are buy-score points at full timing.
ECON_BONDS = {
    "远见": {
        "need": 2,
        "engine": "gold_generation",
        "label": "产钱引擎",
        "base_weight": 18.0,
        "why": "整备区也可激活；每10层+2资金，80/150层远见干员买价-1/-1",
    },
    "奇迹": {
        "need": 2,
        "engine": "refresh_economy",
        "label": "刷新经济",
        "base_weight": 14.0,
        "why": "整备区也可激活；刷新概率免费，100层保底一名当前等级干员",
    },
    "投资人": {
        "need": 3,
        "engine": "on_acquire_amplifier",
        "label": "获得时放大器",
        "base_weight": 14.0,
        "why": "整备区也可激活；获得时特质触发×2，100层×3，放大免费招募/装备",
    },
}

# An engine needs ~a full window to be worth full price; beyond 8 rounds left it
# saturates, and it decays to zero on the final rest phase (cannot pay off).
FULL_PAYOFF_WINDOW = 8.0
# A not-yet-active engine still gets partial credit, scaled by progress, so the
# advisor values building toward one (the "future score" axis) — but cheaper.
LOCKED_FACTOR = 0.5


def timing_factor(current_round: int, total_rounds: int = DEFAULT_TOTAL_ROUNDS) -> float:
    """Fraction of full engine value given the remaining payback window."""
    window = max(0, total_rounds - current_round)
    return round(min(1.0, window / FULL_PAYOFF_WINDOW), 3)


def _feasibility(bond, cache):
    """Cached 0..1 growability factor for an economy bond."""
    if bond not in cache:
        cache[bond] = sf.feasibility_factor(bond)
    return cache[bond]


def econ_bond_value(ds, operator, state, bond_counts) -> dict:
    """Economy-bond contribution of buying `operator` right now.

    bond_counts: current distinct-operator count per bond on the board (from
    Rules.bond_counts). The prospective count adds this card unless a same-named
    operator is already held (then it contributes no new distinct member).
    Returns {score, timing_factor, active, locked, dead_window}.
    """
    name = operator.get("name", "")
    already_owned = any(u.name == name for u in state.board)
    tf = timing_factor(state.round)

    score = 0.0
    active, locked = [], []
    feas_cache = {}
    for bond in operator.get("bonds", []):
        spec = ECON_BONDS.get(bond)
        if not spec:
            continue
        have = bond_counts.get(bond, 0)
        prospective = have + (0 if already_owned else 1)
        need = spec["need"]
        if tf <= 0.0:
            # no rest phase remains for the engine to trigger
            locked.append({"bond": bond, "missing": max(0, need - prospective),
                           "label": spec["label"], "why": spec["why"],
                           "no_window": True})
            continue
        feas = _feasibility(bond, feas_cache)
        if prospective >= need:
            gained = round(spec["base_weight"] * tf * feas, 1)
            score += gained
            active.append({"bond": bond, "label": spec["label"],
                           "weight": gained, "feasibility": feas, "why": spec["why"]})
        else:
            progress = min(1.0, prospective / need)
            gained = round(spec["base_weight"] * tf * feas * progress * LOCKED_FACTOR, 1)
            score += gained
            locked.append({"bond": bond, "missing": need - prospective,
                           "label": spec["label"], "weight": gained,
                           "feasibility": feas, "why": spec["why"], "no_window": False})

    return {
        "score": round(score, 1),
        "timing_factor": tf,
        "active": active,
        "locked": locked,
        "dead_window": tf <= 0.0,
    }
