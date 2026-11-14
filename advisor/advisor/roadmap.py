# -*- coding: utf-8 -*-
"""Build roadmap: expose the FULL curated build curve and enemy-driven pivots.

The lineup compass (advisor/compass.py) only names which archetype a board is
building and steers single-card buys. This module goes further and answers the
planning questions the compass does not:

  * what is the whole composition -- the early (transition) / mid / late
    (completed) rosters, not just a couple of carry names;
  * where am I now, which planned units do I already own, and who should I chase
    next at the current dispatch level;
  * when the incoming enemy picture hits this lineup's documented weakness,
    should I slot in a tech card or pivot to a different lineup, and to which.

All composition facts already live in data/lineups.json (stages with pop/goal/
units, carry/tank/heal, counters/weak + human why-text). This module is pure
assembly over those facts plus the current GameState; it invents no operators
and does no combat math. Deterministic and stdlib-only, so it is unit-testable
without OCR.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

from .data import Dataset
from .lineup import load_lineups
from . import compass as compass_mod

# Dispatch-level -> which build stage the player is currently running.
# Low tiers only roll low-shop-tier operators, so the early roster is reachable
# first; mid/late units gate behind higher dispatch levels.
_STAGE_BY_LEVEL = {1: "early", 2: "early", 3: "mid", 4: "mid",
                   5: "late", 6: "late"}
_STAGE_ORDER = ("early", "mid", "late")

# Roles prioritized when picking the next unit to chase within a stage.
_ROLE_PRIORITY = {"carry": 0, "tank": 1, "heal": 2, "support": 3,
                  "control": 4}


def current_stage(dispatch_level: int) -> str:
    return _STAGE_BY_LEVEL.get(max(1, min(6, int(dispatch_level))), "early")


def _get_lineup(lineups: List[dict], lineup_id: str) -> Optional[dict]:
    for L in lineups:
        if L["id"] == lineup_id:
            return L
    return None


def _annotate_stage(stage: dict, owned: set) -> dict:
    """Add an `owned` flag to every planned unit without mutating the source."""
    units = []
    for u in stage.get("units", []):
        units.append({
            "name": u["name"], "tier": u.get("tier"),
            "role": u.get("role"), "note": u.get("note", ""),
            "owned": u["name"] in owned,
        })
    return {"pop": stage.get("pop"), "goal": stage.get("goal", ""),
            "units": units}


def _stage_chase_candidates(L: dict, stage_name: str, owned: set,
                            dispatch_level: int, *, econ_only: bool) -> List[tuple]:
    """Unowned, tier-reachable units in a stage. On-board chase excludes econ;
    off-board chase keeps only econ (场下经济件)."""
    stage = L["stages"].get(stage_name, {})
    candidates = []
    for u in stage.get("units", []):
        if u["name"] in owned:
            continue
        is_econ = u.get("role") == "econ"
        if econ_only != is_econ:
            continue
        tier = u.get("tier")
        if tier is not None and tier > dispatch_level:
            continue  # not rollable yet; it belongs to a later stage
        candidates.append((_ROLE_PRIORITY.get(u.get("role"), 9),
                           u.get("tier", 9), u["name"]))
    candidates.sort()
    return candidates


def next_targets(L: dict, stage_name: str, owned: set,
                 dispatch_level: int, limit: int = 4) -> List[str]:
    """On-board planned units for the current stage that are (a) not yet owned,
    (b) reachable at the current dispatch level (shop tier <= level), and
    (c) not off-board econ pieces. Ordered by role priority so carries first."""
    candidates = _stage_chase_candidates(
        L, stage_name, owned, dispatch_level, econ_only=False)
    return [name for _r, _t, name in candidates[:limit]]


def off_board_targets(L: dict, stage_name: str, owned: set,
                      dispatch_level: int, limit: int = 4) -> List[str]:
    """Off-board econ pieces for the current stage (场下经济挂件). Same ownership
    and dispatch-tier gates as next_targets; kept separate so the on-board chase
    list stays clean."""
    candidates = _stage_chase_candidates(
        L, stage_name, owned, dispatch_level, econ_only=True)
    return [name for _r, _t, name in candidates[:limit]]


def build_roadmap(ds: Dataset, st, plan,
                  lineups: Optional[List[dict]] = None) -> Optional[dict]:
    """Assemble the full build curve for the inferred plan, annotated with the
    player's current ownership. Returns None when there is no active plan."""
    if plan is None:
        return None
    lineups = lineups if lineups is not None else load_lineups()
    L = _get_lineup(lineups, plan.lineup_id)
    if L is None:
        return None

    owned = {u.name for u in st.board}
    stage_name = current_stage(st.dispatch_level)
    stages = {s: _annotate_stage(L["stages"][s], owned)
              for s in _STAGE_ORDER if s in L.get("stages", {})}

    # Cumulative early→mid→late repeats the same people across stages; ownership
    # totals must count unique operator names, not stage-entry rows.
    all_names = {u["name"] for s in stages.values() for u in s["units"]}
    owned_names = {u["name"] for s in stages.values()
                   for u in s["units"] if u["owned"]}
    owned_count = len(owned_names)
    total_named = len(all_names)

    return {
        "lineup_id": L["id"], "name": L["name"],
        "archetype": L.get("archetype", ""),
        "confidence": plan.confidence, "source": plan.source,
        "fantasy": L.get("fantasy", ""),
        "core_bonds": list(L.get("core_bonds", [])),
        "splash_bonds": list(L.get("splash_bonds", [])),
        "current_stage": stage_name,
        "ownership": {"owned": owned_count, "planned": total_named},
        "stages": stages,
        "next_targets": next_targets(L, stage_name, owned, st.dispatch_level),
        "off_board_targets": off_board_targets(
            L, stage_name, owned, st.dispatch_level),
        "roles": {k: list(L.get(k, []) or [])
                  for k in ("carry", "tank", "heal")},
        "key_tips": list(L.get("key_tips", [])),
    }


@dataclass
class PivotAdvice:
    should_pivot: bool
    weak_hit: List[str]
    weak_why: str
    alternatives: List[dict]
    verdict: str

    def as_dict(self) -> dict:
        return {
            "should_pivot": self.should_pivot,
            "weak_hit": self.weak_hit,
            "weak_why": self.weak_why,
            "alternatives": self.alternatives,
            "verdict": self.verdict,
        }


def evaluate_pivot(ds: Dataset, st, plan,
                   lineups: Optional[List[dict]] = None,
                   max_alternatives: int = 3) -> Optional[PivotAdvice]:
    """Enemy-driven switch advice. Fires only when the incoming enemy picture
    intersects the active lineup's documented `weak` keys.

    A weakness hit does NOT force a switch: the curated weak_why often describes
    a tech-card fix (e.g. add an anti-air unit), so we surface both the remedy
    text and, where they exist, lineups that directly counter the threat. The
    caller decides; this never rewrites the inferred plan on its own.
    """
    if plan is None or not st.enemy_types:
        return None
    lineups = lineups if lineups is not None else load_lineups()
    L = _get_lineup(lineups, plan.lineup_id)
    if L is None:
        return None

    enemies = set(st.enemy_types)
    weak_hit = sorted(enemies & set(L.get("weak", [])))
    if not weak_hit:
        return None

    banned_bonds = set(getattr(st, "banned_bonds", None) or [])
    alternatives = []
    for other in lineups:
        if other["id"] == plan.lineup_id:
            continue
        if set(other.get("core_bonds", [])) & banned_bonds:
            continue
        covers = sorted(enemies & set(other.get("counters", [])))
        if covers:
            alternatives.append({
                "id": other["id"], "name": other["name"],
                "archetype": other.get("archetype", ""),
                "covers": covers,
                "counter_why": other.get("counter_why", ""),
            })
    alternatives.sort(key=lambda a: (-len(a["covers"]), a["id"]))
    alternatives = alternatives[:max_alternatives]

    if alternatives:
        verdict = ("当前体系对 %s 处于劣势；可先按补救方案外挂，若该敌人是本波主力"
                   "建议转练下列克制体系" % "、".join(weak_hit))
        should = True
    else:
        verdict = ("当前体系对 %s 处于劣势，且库中无直接克制体系；优先按补救方案"
                   "外挂针对性干员" % "、".join(weak_hit))
        should = False

    return PivotAdvice(
        should_pivot=should, weak_hit=weak_hit,
        weak_why=L.get("weak_why", ""), alternatives=alternatives,
        verdict=verdict,
    )
