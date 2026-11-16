# -*- coding: utf-8 -*-
"""One-dimensional random hillclimb over selfplay.params."""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from advisor.data import Dataset

from .episode import run_episode
from .params import PARAMS, apply_params, clamp_pair, restore_params, snapshot_params


def evaluate_params(
    values: Dict[str, float],
    *,
    episodes: int = 3,
    seed0: int = 0,
    regulation_level: int = 1,
    max_rounds: int = 8,
    ds: Optional[Dataset] = None,
) -> Dict[str, Any]:
    ds = ds or Dataset()
    prev = apply_params(clamp_pair(values))
    try:
        scores = []
        logs = []
        for i in range(episodes):
            ep = run_episode(
                ds=ds,
                regulation_level=regulation_level,
                max_rounds=max_rounds,
                seed=seed0 + i,
            )
            scores.append(int(ep["max_round_cleared"]))
            logs.append({"seed": seed0 + i, "max_round_cleared": ep["max_round_cleared"]})
        mean = sum(scores) / float(len(scores)) if scores else 0.0
        return {
            "params": dict(values),
            "scores": scores,
            "mean_max_round": mean,
            "episodes": logs,
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
) -> Dict[str, Any]:
    """Perturb one param ±step, keep the better mean max_round."""
    rng = rng or random.Random(seed0)
    ds = ds or Dataset()
    base = snapshot_params()
    spec = None
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
        regulation_level=regulation_level, max_rounds=max_rounds, ds=ds)
    cand_eval = evaluate_params(
        candidate, episodes=episodes, seed0=seed0,
        regulation_level=regulation_level, max_rounds=max_rounds, ds=ds)

    improved = cand_eval["mean_max_round"] > base_eval["mean_max_round"]
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
        "note": "ASSUMED shop_odds + ASSUMED income; not a full client sim",
    }
