# -*- coding: utf-8 -*-
"""One-dimensional / multi-step random hillclimb over selfplay.params."""
from __future__ import annotations

import random
import time
from typing import Any, Dict, List, Optional, Tuple

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
            "gold_waste/overflow/clear_miss + variance penalty; "
            "P6 expanded knobs; not a full client sim"
        ),
    }


def _propose_candidate(
    base: Dict[str, float],
    rng: random.Random,
    *,
    step_scale: int = 4,
    n_params: int = 1,
    range_jump_prob: float = 0.35,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Perturb 1..n_params with scaled ±steps or fractional range jumps.

    Unit ±step landscapes on current smoke cards are flat; larger / multi-dim
    moves are the default for a fast 2–3 min round.
    """
    k = max(1, min(int(n_params), len(PARAMS)))
    specs = rng.sample(list(PARAMS), k=k)
    candidate = dict(base)
    deltas: Dict[str, float] = {}
    scale = max(1, int(step_scale))
    for spec in specs:
        cur = float(base[spec.key])
        if rng.random() < float(range_jump_prob):
            frac = rng.uniform(0.15, 0.55)
            delta = (float(spec.hi) - float(spec.lo)) * frac * rng.choice((-1.0, 1.0))
        else:
            mult = rng.randint(1, scale)
            delta = float(spec.step) * float(mult) * rng.choice((-1.0, 1.0))
        candidate[spec.key] = cur + delta
        deltas[spec.key] = delta
    return clamp_pair(candidate), deltas


def hillclimb_round(
    *,
    steps: int = 32,
    seconds: float = 150.0,
    hard_wall_s: float = 180.0,
    step_scale: int = 6,
    n_params: int = 2,
    range_jump_prob: float = 0.4,
    seed0: int = 0,
    episodes: int = 3,
    regulation_level: int = 1,
    max_rounds: int = 8,
    suite: Optional[str] = "smoke",
    rng: Optional[random.Random] = None,
    ds: Optional[Dataset] = None,
    eval_before_after: bool = True,
) -> Dict[str, Any]:
    """In-process multi-step climb with wall-clock abort (smoke-oriented).

    Caches the current fitness so each proposal only needs one candidate eval.
    Accepts persist in-process via ``apply_params``. Includes optional
    before/after suite evals inside the measured wall. Aborts if the hard wall
    (default 180 s) would be exceeded before the next proposal or after-eval.
    """
    rng = rng or random.Random(seed0)
    ds = ds or Dataset()
    t0 = time.perf_counter()
    defaults = snapshot_params()
    current = dict(defaults)
    step_log: List[Dict[str, Any]] = []
    accepted = 0
    aborted = None

    def elapsed() -> float:
        return time.perf_counter() - t0

    def remaining_hard() -> float:
        return float(hard_wall_s) - elapsed()

    before = None
    current_fit: Optional[Dict[str, Any]] = None
    if eval_before_after:
        if remaining_hard() <= 0.5:
            aborted = "hard_wall_before_baseline"
        else:
            before = evaluate_params(
                current, episodes=episodes, seed0=seed0,
                regulation_level=regulation_level, max_rounds=max_rounds,
                ds=ds, suite=suite)
            current_fit = before
    else:
        current_fit = evaluate_params(
            current, episodes=episodes, seed0=seed0,
            regulation_level=regulation_level, max_rounds=max_rounds,
            ds=ds, suite=suite)

    if aborted is None and current_fit is not None:
        # Soft climb budget leaves a little room for after-eval.
        climb_deadline = min(
            float(seconds),
            float(hard_wall_s) - (0.9 if eval_before_after else 0.1),
        )
        for i in range(max(0, int(steps))):
            if elapsed() >= climb_deadline or remaining_hard() < 0.85:
                aborted = "wall_during_climb"
                break
            candidate, deltas = _propose_candidate(
                current, rng,
                step_scale=step_scale,
                n_params=rng.randint(1, max(1, int(n_params))),
                range_jump_prob=range_jump_prob,
            )
            # Skip no-ops after clamp.
            if all(abs(float(candidate[k]) - float(current[k])) < 1e-12
                   for k in candidate):
                step_log.append({
                    "i": i, "deltas": deltas, "skipped": "noop_clamp",
                    "improved": False, "wall_s": round(elapsed(), 3),
                })
                continue
            cand_eval = evaluate_params(
                candidate, episodes=episodes, seed0=seed0,
                regulation_level=regulation_level, max_rounds=max_rounds,
                ds=ds, suite=suite)
            improved = better(cand_eval, current_fit)
            row = {
                "i": i,
                "deltas": {k: round(float(v), 6) for k, v in deltas.items()},
                "candidate_fitness": cand_eval["fitness"],
                "base_fitness": current_fit["fitness"],
                "improved": bool(improved),
                "wall_s": round(elapsed(), 3),
            }
            if improved:
                apply_params({k: candidate[k] for k in deltas})
                current = snapshot_params()
                current_fit = cand_eval
                accepted += 1
                row["kept_keys"] = sorted(deltas.keys())
            step_log.append(row)
            if remaining_hard() <= 0:
                aborted = "hard_wall_exceeded"
                break

    after = None
    if eval_before_after and aborted not in ("hard_wall_before_baseline",):
        if remaining_hard() <= 0:
            aborted = aborted or "hard_wall_before_after_eval"
        else:
            after = evaluate_params(
                snapshot_params(), episodes=episodes, seed0=seed0,
                regulation_level=regulation_level, max_rounds=max_rounds,
                ds=ds, suite=suite)

    wall_s = elapsed()
    if wall_s > float(hard_wall_s) and aborted is None:
        aborted = "hard_wall_exceeded"

    best = snapshot_params()
    knobs_delta = {
        k: round(float(best[k]) - float(defaults[k]), 6)
        for k in best
        if abs(float(best[k]) - float(defaults[k])) > 1e-12
    }
    fit_before = None if before is None else float(before["fitness"])
    fit_after = None if after is None else float(after["fitness"])
    fit_current = None if current_fit is None else float(current_fit["fitness"])
    return {
        "suite": suite,
        "steps_requested": int(steps),
        "steps_ran": len([r for r in step_log if not r.get("skipped")]),
        "steps_logged": len(step_log),
        "accepted": accepted,
        "step_scale": int(step_scale),
        "n_params_max": int(n_params),
        "seconds_budget": float(seconds),
        "hard_wall_s": float(hard_wall_s),
        "wall_s": round(wall_s, 3),
        "aborted": aborted,
        "over_hard_wall": wall_s > float(hard_wall_s),
        "fitness_before": fit_before,
        "fitness_after": fit_after if fit_after is not None else fit_current,
        "fitness_delta": (
            None if fit_before is None or (fit_after is None and fit_current is None)
            else round((fit_after if fit_after is not None else fit_current) - fit_before, 6)
        ),
        "ref_smoke_fitness": -1.973,
        "defaults": defaults,
        "best_knobs": best,
        "knobs_delta": knobs_delta,
        "before": before,
        "after": after,
        "steps": step_log,
        "note": (
            "ASSUMED shop_odds/income/item_mix; fast multi-step round "
            "(scaled ±steps / range jumps / multi-param); smoke-oriented; "
            "not a client win-rate claim"
        ),
    }
