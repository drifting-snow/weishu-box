# -*- coding: utf-8 -*-
"""Minimal self-play / hillclimb scaffold for advisor param search.

Uses ASSUMED community shop_odds.tier_probs and an explicit ASSUMED income
schedule (not official). Not a full Guard Protocol client simulation.
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
