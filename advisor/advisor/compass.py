# -*- coding: utf-8 -*-
"""Lineup compass: infer the curated lineup a run is building, from the board.

Why this exists
---------------
The curated lineup library (advisor/lineup.py + data/lineups.json, 13 archetypes
with early/mid/late units and core bonds) used to be an island: nothing in the
buy engine imported it. The engine scored each shop card only against the
current board's *local* bond counts, with no cross-round build direction, so
picks scattered across unrelated bonds ("bought cards feel solo, no synergy").

This module bridges that gap. It reads the owned board and names the archetype
being built, then tells the engine which shop cards belong to that plan so
on-picks outrank generic filler. It never decides purchases itself; it only
produces a plan + per-card synergy points that engine.py folds into its score.

Inference evidence, strongest first:
  * named overlap -- an owned operator is literally on the lineup's unit list;
  * core-bond coverage -- the board already activates one of its core bonds.
Confidence is gated so a single ambiguous unit cannot lock a direction, and an
empty / directionless board yields None (the engine then behaves exactly as
before). With no board evidence but an enemy picture, the top counter lineup is
suggested as a weak, explicitly-labelled fallback.

Pure stdlib + Dataset/lineup JSON. No OCR, deterministic, unit-testable.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .data import Dataset
from .lineup import load_lineups, recommend_lineups

# Evidence weights. A named unit beats mere bond coverage because bonds are
# shared across several lineups while a named unit is a concrete build signal.
NAMED_W = 3
CORE_W = 2

# Confidence gates.
STRONG_NAMED = 2     # >=2 named units on the plan -> committed direction
STRONG_CORE = 2      # >=2 core bonds already on board -> committed
WEAK_NAMED = 1       # exactly one named unit -> tentative

# Synergy points awarded to a shop operator that fits the active plan. Sized to
# re-rank picks inside a round (above the old generic +12 bond nudge, around the
# explicit target_bond +30) but below merge (100) and bond-one-away (60), so the
# compass steers direction without overriding hard merge/threshold priorities.
CARRY_PTS = 34.0     # named carry of the plan
MEMBER_PTS = 26.0    # any other named unit (tank/heal/control/...)
CORE_BOND_PTS = 18.0  # not on the named list but carries a core bond
WEAK_WEIGHT = 0.6    # tentative (single-clue) plans guide more gently


@dataclass
class LineupPlan:
    lineup_id: str
    name: str
    archetype: str
    core_bonds: List[str]
    unit_names: Set[str]
    role_map: Dict[str, List[str]]
    confidence: str                       # "strong" | "weak"
    source: str                           # "board" | "enemy_fallback"
    named_overlap: List[str]
    core_covered: List[str]
    score: int
    counters: List[str] = field(default_factory=list)
    weak: List[str] = field(default_factory=list)

    @property
    def weight(self) -> float:
        return 1.0 if self.confidence == "strong" else WEAK_WEIGHT

    def role_of(self, name: str) -> List[str]:
        return self.role_map.get(name, [])


def _index_lineup(L: dict) -> Tuple[Set[str], Dict[str, List[str]]]:
    """Flatten a lineup's staged units into (name set, name->roles)."""
    units: Set[str] = set()
    role_map: Dict[str, List[str]] = {}
    for stage in L.get("stages", {}).values():
        for u in stage.get("units", []):
            nm = u["name"]
            units.add(nm)
            role = u.get("role")
            if role and role not in role_map.setdefault(nm, []):
                role_map[nm].append(role)
    # Fold the explicit carry/tank/heal shortlists into the role map.
    for role in ("carry", "tank", "heal"):
        for nm in L.get(role, []) or []:
            if nm in units and role not in role_map.setdefault(nm, []):
                role_map[nm].append(role)
    return units, role_map


def _board_bonds(ds: Dataset, owned: Set[str]) -> Set[str]:
    bonds: Set[str] = set()
    for nm in owned:
        op = ds.operator(nm)
        if op:
            bonds.update(op.get("bonds", []))
    return bonds


def _make_plan(L: dict, confidence: str, source: str,
               named: List[str], core: List[str], score: int) -> LineupPlan:
    units, role_map = _index_lineup(L)
    return LineupPlan(
        lineup_id=L["id"], name=L["name"], archetype=L.get("archetype", ""),
        core_bonds=list(L.get("core_bonds", [])), unit_names=units,
        role_map=role_map, confidence=confidence, source=source,
        named_overlap=named, core_covered=core, score=score,
        counters=list(L.get("counters", [])), weak=list(L.get("weak", [])),
    )


def _enemy_fallback(st, lineups: List[dict]) -> Optional[LineupPlan]:
    """No board evidence: if an enemy picture exists, suggest its best counter
    lineup as a tentative direction. Otherwise there is no plan to steer by."""
    if not st.enemy_types:
        return None
    banned = set(getattr(st, "banned_bonds", None) or [])
    ranked = recommend_lineups(enemy_types=list(st.enemy_types),
                               banned_bonds=list(banned))
    if not ranked:
        return None
    top_id = ranked[0]["id"]
    L = next((x for x in lineups if x["id"] == top_id), None)
    if L is None:
        return None
    return _make_plan(L, "weak", "enemy_fallback", [], [], 0)


def infer_lineup(ds: Dataset, st, lineups: Optional[List[dict]] = None
                 ) -> Optional[LineupPlan]:
    """Name the lineup this GameState's board is building.

    Returns None when there is neither board evidence nor an enemy picture, so
    callers can keep their legacy behaviour untouched.
    """
    lineups = lineups if lineups is not None else load_lineups()
    owned = {u.name for u in st.board}
    banned_bonds = set(getattr(st, "banned_bonds", None) or [])
    if not owned:
        return _enemy_fallback(st, lineups)

    board_bonds = _board_bonds(ds, owned)
    best = None  # (score, n_named, n_core, payload...)
    for L in lineups:
        # A lineup whose core bond is banned cannot be the build direction.
        if set(L.get("core_bonds", [])) & banned_bonds:
            continue
        units, _role = _index_lineup(L)
        named = sorted(owned & units)
        core = sorted(set(L.get("core_bonds", [])) & board_bonds)
        score = len(named) * NAMED_W + len(core) * CORE_W
        key = (score, len(named), len(core))
        if best is None or key > best[0]:
            best = (key, L, named, core, score)

    if best is None or best[0][0] == 0:
        return _enemy_fallback(st, lineups)

    (score, n_named, n_core), L, named, core, raw_score = best
    if n_named >= STRONG_NAMED or n_core >= STRONG_CORE:
        confidence = "strong"
    elif n_named >= WEAK_NAMED:
        confidence = "weak"
    else:
        # Bond-only whisper with no named unit: too ambiguous to steer on.
        return _enemy_fallback(st, lineups)
    return _make_plan(L, confidence, "board", named, core, raw_score)


def on_plan_bonus(plan: Optional[LineupPlan], name: str,
                  bonds: List[str]) -> Tuple[float, Optional[str]]:
    """Synergy (points, reason) for a shop operator under the active plan.

    (0.0, None) when there is no plan or the card is off-plan, so the engine can
    add the result unconditionally. A named unit earns the member/carry score;
    a non-listed unit carrying a core bond earns the smaller bond score (these
    are mutually exclusive to avoid double counting).
    """
    if plan is None:
        return 0.0, None
    if name in plan.unit_names:
        roles = plan.role_of(name)
        if "carry" in roles:
            base, why = CARRY_PTS, "阵容核心carry·%s" % plan.name
        else:
            role_tag = "/".join(r for r in roles if r) or "成员"
            base, why = MEMBER_PTS, "阵容名单内%s·%s" % (role_tag, plan.name)
        return round(base * plan.weight, 1), why
    shared = sorted(set(bonds) & set(plan.core_bonds))
    if shared:
        base = CORE_BOND_PTS * plan.weight
        return round(base, 1), "凑%s核心羁绊(%s)" % (plan.name, "、".join(shared))
    return 0.0, None
