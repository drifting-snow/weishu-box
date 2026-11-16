# -*- coding: utf-8 -*-
"""Minimal self-play / hillclimb scaffold for advisor param search.

Uses ASSUMED community shop_odds.tier_probs and ASSUMED gold_income.json
(formula min(3+r,12); unspent clears at rest end). Not a full client sim.
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
