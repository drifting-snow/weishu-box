# -*- coding: utf-8 -*-
"""ASSUMED shop roll tier-probability loader.

Reads data/shop_roll_odds.json — fan-derived copy-weighted priors. Used by the
engine refresh EV term (``Advisor._score_refresh``); still marked assumed /
non-official. Official Hypergryph has not published these weights.
"""
from __future__ import annotations

import json
import os
from typing import Dict, Mapping, Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data")
SHOP_ROLL_ODDS_PATH = os.path.join(DATA_DIR, "shop_roll_odds.json")

_cache: Optional[dict] = None

VALID_SEASONS = ("guicheng", "mengyue")


def load_shop_roll_odds(path: str = SHOP_ROLL_ODDS_PATH) -> dict:
    """Load the ASSUMED shop roll odds document (cached for the default path)."""
    global _cache
    if path == SHOP_ROLL_ODDS_PATH and _cache is not None:
        return _cache
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if path == SHOP_ROLL_ODDS_PATH:
        _cache = doc
    return doc


def clear_shop_roll_odds_cache() -> None:
    """Drop the module-level cache (tests / hot-reload)."""
    global _cache
    _cache = None


def tier_probs(level: int,
               season: str = "guicheng",
               doc: Optional[Mapping] = None) -> Dict[str, float]:
    """Return {tier_str: fraction} for a dispatch level under a season table.

    ``season`` is ``\"guicheng\"`` (规程, default) or ``\"mengyue\"`` (盟约).
    Only tiers that can appear at that level are present; fractions sum ≈ 1.
    Raises ``KeyError`` / ``ValueError`` on unknown season or level.
    """
    if season not in VALID_SEASONS:
        raise ValueError(
            "season must be one of %s, got %r" % (VALID_SEASONS, season))
    if doc is None:
        doc = load_shop_roll_odds()
    table = doc["tables"][season]["dispatch_level"]
    key = str(int(level))
    if key not in table:
        raise KeyError("no dispatch_level %s in season %s" % (key, season))
    return {str(t): float(p) for t, p in table[key].items()}
