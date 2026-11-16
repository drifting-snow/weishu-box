# -*- coding: utf-8 -*-
"""Minimal self-play / hillclimb scaffold for advisor param search.

Uses ASSUMED shop_odds (+ confirmed dedicated item slot / ASSUMED which-item,
structure-confirmed merge_reward), ASSUMED gold income, freeze carry,
mode_stats blockCnt, ε-greedy action sampling, placement heuristic, P3
fixed-seed eval cards + robust fitness, and P6 expanded knobs / reservoir
pressure terms. Not a full client.
"""
from .episode import run_episode
from .eval_harness import evaluate_on_cards, list_cards
from .hillclimb import hillclimb_step
from .objective import score_episode
from .params import PARAMS, apply_params, list_params, snapshot_params

__all__ = [
    "PARAMS",
    "apply_params",
    "list_params",
    "snapshot_params",
    "run_episode",
    "hillclimb_step",
    "score_episode",
    "evaluate_on_cards",
    "list_cards",
]
