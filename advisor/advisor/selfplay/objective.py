# -*- coding: utf-8 -*-
"""Robust episode / suite fitness for self-play hillclimb (P3).

Not only ``max_round_cleared``: penalize leaks, unused rest gold, and
cross-episode/card variance so noisy single-wave wins don't dominate.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


# Tunable weights (also registered lightly for documentation; hillclimb v0
# keeps them fixed so param search stays on advisor scoring knobs).
ROUND_WEIGHT = 10.0
LEAK_WEIGHT = 0.5
FAIL_LEAK_WEIGHT = 1.0
GOLD_WASTE_WEIGHT = 0.05
VARIANCE_WEIGHT = 0.35


def _row_leaked(row: Mapping[str, Any]) -> int:
    if row.get("leaked") is not None:
        try:
            return int(row["leaked"])
        except (TypeError, ValueError):
            pass
    battle = row.get("battle_sim") or {}
    result = battle.get("result") if isinstance(battle, dict) else None
    if isinstance(result, dict) and result.get("leaked") is not None:
        try:
            return int(result["leaked"])
        except (TypeError, ValueError):
            return 0
    return 0


def score_episode(ep: Mapping[str, Any]) -> Dict[str, Any]:
    """Scalar fitness components for one episode result dict."""
    cleared = int(ep.get("max_round_cleared") or 0)
    log = list(ep.get("log") or [])
    total_leaked = 0
    fail_leaked = 0
    gold_waste = 0
    rounds_ok = 0
    for row in log:
        leaked = _row_leaked(row)
        total_leaked += leaked
        if row.get("ok"):
            rounds_ok += 1
            gold_waste += int(row.get("gold_end") or 0)
        else:
            fail_leaked = leaked
    raw = (
        ROUND_WEIGHT * cleared
        - LEAK_WEIGHT * total_leaked
        - FAIL_LEAK_WEIGHT * fail_leaked
        - GOLD_WASTE_WEIGHT * gold_waste
    )
    return {
        "fitness": float(raw),
        "max_round_cleared": cleared,
        "rounds_ok": rounds_ok,
        "rounds_played": len(log),
        "total_leaked": int(total_leaked),
        "fail_leaked": int(fail_leaked),
        "gold_waste": int(gold_waste),
        "weights": {
            "round": ROUND_WEIGHT,
            "leak": LEAK_WEIGHT,
            "fail_leak": FAIL_LEAK_WEIGHT,
            "gold_waste": GOLD_WASTE_WEIGHT,
        },
    }


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / float(len(xs)) if xs else 0.0


def _population_std(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / float(len(xs)))


def aggregate_scores(
    episode_scores: Iterable[Mapping[str, Any]],
    *,
    variance_weight: float = VARIANCE_WEIGHT,
) -> Dict[str, Any]:
    """Suite fitness: mean episode fitness minus variance penalty."""
    rows = list(episode_scores)
    fits = [float(r.get("fitness") or 0.0) for r in rows]
    rounds = [int(r.get("max_round_cleared") or 0) for r in rows]
    leaks = [int(r.get("total_leaked") or 0) for r in rows]
    mean_fit = _mean(fits)
    std_fit = _population_std(fits)
    fitness = mean_fit - float(variance_weight) * std_fit
    return {
        "fitness": float(fitness),
        "mean_fitness": float(mean_fit),
        "std_fitness": float(std_fit),
        "variance_weight": float(variance_weight),
        "mean_max_round": float(_mean([float(x) for x in rounds])),
        "mean_leaked": float(_mean([float(x) for x in leaks])),
        "n": len(rows),
        "episodes": rows,
    }


def better(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Whether aggregate ``a`` beats ``b`` (primary fitness, then mean round)."""
    fa = float(a.get("fitness") or 0.0)
    fb = float(b.get("fitness") or 0.0)
    if fa != fb:
        return fa > fb
    return float(a.get("mean_max_round") or 0.0) > float(b.get("mean_max_round") or 0.0)
