# -*- coding: utf-8 -*-
"""Minimal self-play / hillclimb scaffold for advisor param search.

Uses ASSUMED shop_odds (+ item_mix), ASSUMED gold_income min(3+r,12),
freeze carry across rests, and mode_stats blockCnt in battle. Not a full client.
"""
from .episode import run_episode
from .hillclimb import hillclimb_step
from .params import PARAMS, apply_params, snapshot_params

__all__ = [
    "PARAMS",
    "apply_params",
    "snapshot_params",
    "run_episode",
    "hillclimb_step",
]
