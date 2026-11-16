# -*- coding: utf-8 -*-
"""One-dimensional random hillclimb over selfplay.params."""
from __future__ import annotations

import random
from typing import Any, Dict, Optional

from advisor.data import Dataset

from .episode import run_episode
from .eval_harness import evaluate_on_cards
from .objective import aggregate_scores, better, score_episode
from .params import PARAMS, apply_params, clamp_pair, restore_params, snapshot_params


def evaluate_params(
    values: Dict[str, float],
    *,
    episodes: int = 3,
    seed0: int = 0,
    regulation_level: int = 1,
    max_rounds: int = 8,
    ds: Optional[Dataset] = None,
    suite: Optional[str] = None,
) -> Dict[str, Any]:
    """Score a param vector.

    If ``suite`` is set, uses fixed eval cards (P3 harness). Otherwise runs
    ``episodes`` sequential seeds from ``seed0`` with the robust objective.
    """
    ds = ds or Dataset()
    if suite:
        out = evaluate_on_cards(values, suite=suite, ds=ds)
        return {
            "params": dict(values),
            "suite": suite,
            "fitness": out["fitness"],
            "mean_fitness": out["mean_fitness"],
            "std_fitness": out["std_fitness"],
            "mean_max_round": out["mean_max_round"],
            "mean_leaked": out["mean_leaked"],
            "scores": [c.get("max_round_cleared") for c in out.get("cards") or []],
            "cards": out.get("cards"),
            "mode": "eval_cards",
        }

    prev = apply_params(clamp_pair(values))
    try:
        scored = []
        logs = []
        for i in range(episodes):
            ep = run_episode(
                ds=ds,
                regulation_level=regulation_level,
                max_rounds=max_rounds,
                seed=seed0 + i,
            )
            s = score_episode(ep)
            scored.append(s)
            logs.append({
                "seed": seed0 + i,
                "max_round_cleared": s["max_round_cleared"],
                "fitness": s["fitness"],
                "total_leaked": s["total_leaked"],
            })
        agg = aggregate_scores(scored)
        return {
            "params": dict(values),
            "scores": [int(s["max_round_cleared"]) for s in scored],
            "mean_max_round": agg["mean_max_round"],
            "fitness": agg["fitness"],
            "mean_fitness": agg["mean_fitness"],
            "std_fitness": agg["std_fitness"],
            "mean_leaked": agg["mean_leaked"],
            "episodes": logs,
            "mode": "seed_sweep",
        }
    finally:
        restore_params(prev)


def hillclimb_step(
    *,
    episodes: int = 3,
    seed0: int = 0,
    regulation_level: int = 1,
    max_rounds: int = 8,
    param_key: Optional[str] = None,
    rng: Optional[random.Random] = None,
    ds: Optional[Dataset] = None,
    suite: Optional[str] = "smoke",
) -> Dict[str, Any]:
    """Perturb one param ±step; keep the better robust fitness.

    Default ``suite='smoke'`` uses fixed eval cards. Pass ``suite=None`` for
    the legacy sequential seed sweep.
    """
    rng = rng or random.Random(seed0)
    ds = ds or Dataset()
    base = snapshot_params()
    if param_key:
        spec = next(p for p in PARAMS if p.key == param_key)
    else:
        spec = rng.choice(PARAMS)

    delta = spec.step * rng.choice((-1, 1))
    candidate = dict(base)
    candidate[spec.key] = float(base[spec.key]) + delta
    candidate = clamp_pair(candidate)

    base_eval = evaluate_params(
        base, episodes=episodes, seed0=seed0,
        regulation_level=regulation_level, max_rounds=max_rounds,
        ds=ds, suite=suite)
    cand_eval = evaluate_params(
        candidate, episodes=episodes, seed0=seed0,
        regulation_level=regulation_level, max_rounds=max_rounds,
        ds=ds, suite=suite)

    improved = better(cand_eval, base_eval)
    if improved:
        apply_params({spec.key: candidate[spec.key]})
        kept = candidate
    else:
        kept = base

    return {
        "param": spec.key,
        "delta": delta,
        "base": base_eval,
        "candidate": cand_eval,
        "improved": improved,
        "kept": kept,
        "suite": suite,
        "note": (
            "ASSUMED shop_odds/income/item_mix; fitness uses round/leak/"
            "gold_waste + variance penalty; not a full client sim"
        ),
    }
