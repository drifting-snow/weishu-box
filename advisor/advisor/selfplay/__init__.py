# -*- coding: utf-8 -*-
"""Minimal self-play / hillclimb scaffold for advisor param search.

Uses ASSUMED shop_odds (+ item_mix), ASSUMED gold_income min(3+r,12),
freeze carry, mode_stats blockCnt, and P3 fixed-seed eval cards + robust
fitness (round / leak / gold waste / variance). Not a full client sim.
"""
from .episode import run_episode
from .eval_harness import evaluate_on_cards, list_cards
from .hillclimb import hillclimb_step
from .objective import score_episode
from .params import PARAMS, apply_params, snapshot_params

__all__ = [
    "PARAMS",
    "apply_params",
    "snapshot_params",
    "run_episode",
    "hillclimb_step",
    "score_episode",
    "evaluate_on_cards",
    "list_cards",
]
