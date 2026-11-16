# -*- coding: utf-8 -*-
"""Robust episode / suite fitness for self-play hillclimb (P3 + P6 + P7).

Not only ``max_round_cleared``: reward intermediate clear progress and paper
margin proxies, and penalize leaks, unused rest gold, reservoir overflow /
incomplete clear, and cross-episode/card variance so noisy single-wave wins
don't dominate.

P7 (gradient fix): when most smoke cards wipe early, ``cleared`` alone is
flat. Weight already-logged ``clear_frac`` / ``clear_miss`` / overflow /
gold_waste / margin so knob changes move fitness even if max_round stays 0–2.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence


# Tunable weights (also registered lightly for documentation; hillclimb keeps
# them fixed so param search stays on advisor scoring knobs).
ROUND_WEIGHT = 10.0
LEAK_WEIGHT = 0.5
FAIL_LEAK_WEIGHT = 1.0
# P7: unused rest gold was nearly silent at 0.05; bump so spend/refresh knobs
# that leave different leftovers actually move fitness.
GOLD_WASTE_WEIGHT = 0.2
VARIANCE_WEIGHT = 0.35
# P6 pressure: reservoir overflow seconds + clear_frac miss (1 - killed/total).
OVERFLOW_WEIGHT = 0.35
CLEAR_MISS_WEIGHT = 1.5
# P7: explicit positive progress on Σ clear_frac (even on fail rounds) so
# near-miss boards beat total wipes without needing max_round_cleared > 0.
# Combined with CLEAR_MISS this yields effective ~+4.5 per unit clear_frac
# relative to a full miss (see docs/weishu-hillclimb-gradient-fix.md).
CLEAR_FRAC_WEIGHT = 3.0
# P7: paper clear_margin.margin proxy (tanh-clamped). Scoring knobs move this
# even when stub battle outcomes are identical.
MARGIN_WEIGHT = 1.25


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


def _max_overflow_seconds(pressure: Any) -> float:
    if not isinstance(pressure, dict) or not pressure:
        return 0.0
    best = 0.0
    for tile in pressure.values():
        if not isinstance(tile, dict):
            continue
        try:
            best = max(best, float(tile.get("overflow_seconds") or 0.0))
        except (TypeError, ValueError):
            continue
    return best


def _battle_result(row: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    battle = row.get("battle_sim") or {}
    if not isinstance(battle, dict):
        return None
    result = battle.get("result")
    return result if isinstance(result, dict) else None


def _row_overflow(row: Mapping[str, Any]) -> float:
    if row.get("max_overflow_s") is not None:
        try:
            return float(row["max_overflow_s"])
        except (TypeError, ValueError):
            pass
    res = row.get("reservoir")
    if isinstance(res, dict) and res.get("max_overflow_s") is not None:
        try:
            return float(res["max_overflow_s"])
        except (TypeError, ValueError):
            pass
    result = _battle_result(row)
    if result is None:
        return 0.0
    return _max_overflow_seconds(result.get("pressure"))


def _row_clear_frac(row: Mapping[str, Any]) -> Optional[float]:
    if row.get("clear_frac") is not None:
        try:
            return max(0.0, min(1.0, float(row["clear_frac"])))
        except (TypeError, ValueError):
            pass
    res = row.get("reservoir")
    if isinstance(res, dict) and res.get("clear_frac") is not None:
        try:
            return max(0.0, min(1.0, float(res["clear_frac"])))
        except (TypeError, ValueError):
            pass
    result = _battle_result(row)
    if result is None:
        return None
    try:
        total = int(result.get("total") or 0)
        killed = int(result.get("killed") or 0)
        leaked = int(result.get("leaked") or 0)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    resolved = max(killed + leaked, total)
    return max(0.0, min(1.0, killed / float(resolved)))


def _row_margin(row: Mapping[str, Any]) -> Optional[float]:
    """Paper / logged clear-margin proxy (may be negative)."""
    if row.get("margin") is not None:
        try:
            return float(row["margin"])
        except (TypeError, ValueError):
            pass
    cm = row.get("clear_margin")
    if isinstance(cm, dict) and cm.get("margin") is not None:
        try:
            return float(cm["margin"])
        except (TypeError, ValueError):
            pass
    return None


def _margin_proxy(margin: Optional[float]) -> float:
    """Bounded contribution so extreme paper margins don't dominate rounds."""
    if margin is None:
        return 0.0
    # tanh keeps ~[-1, 1] for typical margin magnitudes.
    return math.tanh(float(margin))


def score_episode(ep: Mapping[str, Any]) -> Dict[str, Any]:
    """Scalar fitness components for one episode result dict."""
    cleared = int(ep.get("max_round_cleared") or 0)
    log = list(ep.get("log") or [])
    total_leaked = 0
    fail_leaked = 0
    gold_waste = 0
    rounds_ok = 0
    overflow_s = 0.0
    clear_miss = 0.0
    clear_frac_sum = 0.0
    clear_frac_n = 0
    margin_proxy_sum = 0.0
    margin_n = 0
    for row in log:
        leaked = _row_leaked(row)
        total_leaked += leaked
        overflow_s += _row_overflow(row)
        frac = _row_clear_frac(row)
        if frac is not None:
            clear_miss += 1.0 - float(frac)
            clear_frac_sum += float(frac)
            clear_frac_n += 1
        m = _row_margin(row)
        if m is not None:
            margin_proxy_sum += _margin_proxy(m)
            margin_n += 1
        if row.get("ok"):
            rounds_ok += 1
            gold_waste += int(row.get("gold_end") or 0)
        else:
            fail_leaked = leaked
            # Fail-round leftover gold is also waste signal (spend vs freeze).
            gold_waste += int(row.get("gold_end") or 0)
    raw = (
        ROUND_WEIGHT * cleared
        + CLEAR_FRAC_WEIGHT * clear_frac_sum
        + MARGIN_WEIGHT * margin_proxy_sum
        - LEAK_WEIGHT * total_leaked
        - FAIL_LEAK_WEIGHT * fail_leaked
        - GOLD_WASTE_WEIGHT * gold_waste
        - OVERFLOW_WEIGHT * overflow_s
        - CLEAR_MISS_WEIGHT * clear_miss
    )
    return {
        "fitness": float(raw),
        "max_round_cleared": cleared,
        "rounds_ok": rounds_ok,
        "rounds_played": len(log),
        "total_leaked": int(total_leaked),
        "fail_leaked": int(fail_leaked),
        "gold_waste": int(gold_waste),
        "overflow_s": float(round(overflow_s, 4)),
        "clear_miss": float(round(clear_miss, 4)),
        "clear_frac_sum": float(round(clear_frac_sum, 4)),
        "clear_frac_rounds": int(clear_frac_n),
        "margin_proxy": float(round(margin_proxy_sum, 4)),
        "margin_rounds": int(margin_n),
        "weights": {
            "round": ROUND_WEIGHT,
            "clear_frac": CLEAR_FRAC_WEIGHT,
            "margin": MARGIN_WEIGHT,
            "leak": LEAK_WEIGHT,
            "fail_leak": FAIL_LEAK_WEIGHT,
            "gold_waste": GOLD_WASTE_WEIGHT,
            "overflow": OVERFLOW_WEIGHT,
            "clear_miss": CLEAR_MISS_WEIGHT,
            "variance": VARIANCE_WEIGHT,
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
    overflows = [float(r.get("overflow_s") or 0.0) for r in rows]
    clear_misses = [float(r.get("clear_miss") or 0.0) for r in rows]
    clear_fracs = [float(r.get("clear_frac_sum") or 0.0) for r in rows]
    margins = [float(r.get("margin_proxy") or 0.0) for r in rows]
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
        "mean_overflow_s": float(_mean(overflows)),
        "mean_clear_miss": float(_mean(clear_misses)),
        "mean_clear_frac_sum": float(_mean(clear_fracs)),
        "mean_margin_proxy": float(_mean(margins)),
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
