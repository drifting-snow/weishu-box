# -*- coding: utf-8 -*-
"""Lineup (team-composition) layer.

Curated archetype library in data/lineups.json: each lineup has an early/mid/late
build curve (population + concrete operators with shop tier), a combat/economy/
growth archetype, the enemy trait keys it counters, and its weaknesses.

Design constraints:
  * Default assumption is every bond/race is available; in-run bans are applied
    via `banned_bonds` / `available_operators`, not baked into the library.
  * Pure logic + one JSON load; no network, no vision. Easy to unit test.
  * This module recommends *compositions and build direction*. Per-shop single-card
    buying stays in engine.py; lineup is the cross-round plan layer above it.
"""
import json
import os
from typing import Dict, List, Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
LINEUPS_PATH = os.path.join(DATA_DIR, "lineups.json")
ENEMY_PATH = os.path.join(DATA_DIR, "enemy_traits.json")

# How strongly a countered / weak enemy key moves a lineup's recommendation.
COUNTER_WEIGHT = 10.0
WEAKNESS_PENALTY = 8.0
ARCHETYPE_LABEL = {"combat": "战斗型", "economy": "发育型", "growth": "成长型",
                  "flex": "万用挂件型"}


def load_lineups(path: str = LINEUPS_PATH) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["lineups"]


def load_enemy_types(path: str = ENEMY_PATH) -> Dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["enemy_types"]


def _bond_blocked(lineup: dict, banned_bonds: Optional[set]) -> bool:
    """A lineup is unusable if one of its core bonds is banned this run."""
    if not banned_bonds:
        return False
    return bool(set(lineup.get("core_bonds", [])) & set(banned_bonds))


def _operator_available(lineup: dict, available: Optional[set]) -> bool:
    """If an availability set is given (ban-pick), require the late-game core to
    still be obtainable. Empty/None means all operators available."""
    if not available:
        return True
    late_names = {u["name"] for u in lineup["stages"]["late"]["units"]}
    return bool(late_names & set(available))


def counter_fit(lineup: dict, enemy_types: List[str]) -> dict:
    """Score how well a lineup fits a given enemy picture.

    Returns signed score plus human-readable hits/weaknesses. Neutral (0) when no
    enemy picture is supplied, so lineup ranking degenerates to archetype order.
    """
    ets = set(enemy_types or [])
    if not ets:
        return {"score": 0.0, "hits": [], "weaknesses": [], "neutral": True}
    hits = sorted(ets & set(lineup.get("counters", [])))
    weaknesses = sorted(ets & set(lineup.get("weak", [])))
    score = COUNTER_WEIGHT * len(hits) - WEAKNESS_PENALTY * len(weaknesses)
    return {
        "score": round(score, 1),
        "hits": hits,
        "weaknesses": weaknesses,
        "neutral": False,
    }


def recommend_lineups(enemy_types: Optional[List[str]] = None,
                      banned_bonds: Optional[List[str]] = None,
                      available_operators: Optional[List[str]] = None,
                      path: str = LINEUPS_PATH) -> List[dict]:
    """Return lineups ranked for the situation, each annotated with fit + stages.

    Filtering: drop lineups whose core bond is banned or whose late core is fully
    unavailable. Ranking: counter fit first, then archetype priority
    (combat > growth > economy) so ties have a stable, sensible order.
    """
    lineups = load_lineups(path)
    banned = set(banned_bonds or [])
    available = set(available_operators or [])
    archetype_rank = {"combat": 0, "flex": 1, "growth": 2, "economy": 3}

    ranked = []
    for L in lineups:
        if _bond_blocked(L, banned):
            continue
        if not _operator_available(L, available):
            continue
        fit = counter_fit(L, enemy_types or [])
        ranked.append({
            "id": L["id"],
            "name": L["name"],
            "archetype": L["archetype"],
            "archetype_label": ARCHETYPE_LABEL.get(L["archetype"], L["archetype"]),
            "core_bonds": L.get("core_bonds", []),
            "fit_score": fit["score"],
            "counter_hits": fit["hits"],
            "weakness_hits": fit["weaknesses"],
            "neutral": fit["neutral"],
            "counter_why": L.get("counter_why", ""),
            "weak_why": L.get("weak_why", ""),
            "stages": L["stages"],
            "carry": L.get("carry", []),
            "tank": L.get("tank", []),
            "heal": L.get("heal", []),
            "key_tips": L.get("key_tips", []),
            "special_mechanic": L.get("special_mechanic"),
        })

    ranked.sort(key=lambda r: (-r["fit_score"], archetype_rank.get(r["archetype"], 9),
                               r["id"]))
    return ranked


def get_lineup(lineup_id: str, path: str = LINEUPS_PATH) -> Optional[dict]:
    for L in load_lineups(path):
        if L["id"] == lineup_id:
            return L
    return None


def stage_units(lineup_id: str, stage: str, path: str = LINEUPS_PATH) -> List[dict]:
    """Concrete operator list for one of early/mid/late."""
    L = get_lineup(lineup_id, path)
    if not L or stage not in L.get("stages", {}):
        return []
    return L["stages"][stage]["units"]
