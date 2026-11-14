# -*- coding: utf-8 -*-
"""Gate-0 team capability-gap detection (deterministic booleans, no simulation).

The existing counters.counter_score answers "how well does THIS ONE card counter
the wave's enemy types" and adds points to every vaguely relevant card, even
when the team already has the answer covered. This module answers a different,
team-level question: "is there a capability the current BOARD completely lacks,
that this wave actually requires?" It only fires on a true blind spot.

Three curated, deterministic gaps are recognized (stage 0 of the in-run
adaptive plan; deliberately coarse -- frame-level combat math comes later):

  anti_air  : a flying wave and nobody on the board can hit air.
  refraction: a refraction wave (high DEF / low RES) and the board has neither
              an arts dealer nor armor-pierce/true-damage, i.e. zero way
              through the mitigation.
  silence   : a per-name special ability from data/enemy_special_cases.json
              (ice on-death cold-explosion family) demands silence, and nobody
              on the board provides it. Driven by concrete enemy NAMES, not the
              generic stealth/revival categories (those are already scored by
              counter_score), so this does not double-count.

Everything here is inert unless an enemy picture is set, and a gap is reported
only while uncovered, so once the board gains the capability the bonus switches
itself off. No main-engine scoring lives here; callers turn open gaps into an
additive, priority-ordered, hard-capped situational bonus (not raw +N per gap).
"""
from typing import List, Optional

from . import special_counters as spc

# Points for closing a currently-open gap. Primary awards the highest-priority
# gap only; secondary gaps add a smaller bump, then a hard cap keeps the total
# below bond-one-away (60) / merge (100) so multi-gap never stacks unboundedly
# past bond-ish magnitude (raw +15×N was retired).
GAP_BONUS = 15.0          # backward-compat alias = primary award
GAP_BONUS_PRIMARY = 15.0
GAP_BONUS_SECONDARY = 8.0
GAP_BONUS_CAP = 28.0      # hard ceiling; < bond-threshold (60)

# Lower number = higher priority when several gaps are open on one card.
GAP_PRIORITY = {
    "silence": 0,       # named special ability — miss it and the wave spikes
    "refraction": 1,    # zero damage path through mitigation
    "anti_air": 2,      # flying wave with no air answer
}

# Human label + the enemy-side reason for each gap, keyed by a stable gap id.
GAP_LABELS = {
    "anti_air": "缺对空手段",
    "refraction": "缺穿透折射的输出(法系/穿甲/真伤)",
    "silence": "缺沉默手段阻止特殊能力",
}


def _gap_bonus_for_filled(filled):
    """Priority-ordered, hard-capped bonus for the gaps a card closes.

    Returns (score, reasons). Empty ``filled`` -> (0.0, []).
    """
    if not filled:
        return 0.0, []
    ordered = sorted(
        filled,
        key=lambda g: GAP_PRIORITY.get(g["gap"], 99),
    )
    score = GAP_BONUS_PRIMARY
    if len(ordered) > 1:
        score += GAP_BONUS_SECONDARY * (len(ordered) - 1)
    score = min(score, GAP_BONUS_CAP)
    reasons = ["补缺·%s" % g["label"] for g in ordered]
    return score, reasons


def _board_operators(ds, st):
    """Resolved operator records for board units; skip names we cannot resolve."""
    out = []
    for unit in st.board:
        op = ds.operator(unit.name)
        if op:
            out.append(op)
    return out


def _has_anti_air(op) -> bool:
    return bool(op.get("anti_air"))


def _is_arts_dealer(op) -> bool:
    # Gate-0 conservative boolean: 术师 are the guaranteed arts damage source.
    # Per-skill melee arts (e.g. Lord 狼魂) is intentionally not counted here;
    # stage-1 continuous effDps handles those subtler cases.
    return op.get("prof") == "术师"


def _has_pierce_or_true(op) -> bool:
    tags = op.get("mechanic_tags", []) or []
    return "def_pierce" in tags or "true_damage" in tags


def _has_silence(op) -> bool:
    return "silence" in (op.get("mechanic_tags", []) or [])


def detect_team_gaps(ds, st) -> List[dict]:
    """Return the capability gaps this wave exposes on the current board.

    Each gap: {"gap", "label", "enemy_reasons": [str], "board_providers": [str]}.
    board_providers lists the board units already covering it (empty => open).
    An empty list means "no gap": callers treat that as a no-op additive term.
    """
    gaps = []
    enemy_types = set(st.enemy_types or [])
    if not enemy_types and not (st.enemy_names or []):
        return gaps

    board_ops = _board_operators(ds, st)

    # --- anti-air: flying wave with no air-capable operator on the board ---
    if "flying" in enemy_types:
        providers = [op["name"] for op in board_ops if _has_anti_air(op)]
        if not providers:
            gaps.append({
                "gap": "anti_air",
                "label": GAP_LABELS["anti_air"],
                "enemy_reasons": ["本波含飞行敌人，而场上无人能对空"],
                "board_providers": [],
            })

    # --- refraction: no arts AND no pierce/true-damage answer on the board ---
    if "refraction" in enemy_types:
        providers = [op["name"] for op in board_ops
                     if _is_arts_dealer(op) or _has_pierce_or_true(op)]
        if not providers:
            gaps.append({
                "gap": "refraction",
                "label": GAP_LABELS["refraction"],
                "enemy_reasons": ["折射敌人高防低抗，场上既无法系也无穿甲/真伤"],
                "board_providers": [],
            })

    # --- silence: a named special ability demands it and nobody silences ---
    demands = spc.special_counter_demands(st.enemy_names or [])
    silence_demands = [d for d in demands if d["counter_tag"] == "silence"]
    if silence_demands:
        providers = [op["name"] for op in board_ops if _has_silence(op)]
        if not providers:
            reasons = []
            for d in silence_demands:
                reasons.extend(d["reasons"])
            gaps.append({
                "gap": "silence",
                "label": GAP_LABELS["silence"],
                "enemy_reasons": reasons,
                "board_providers": [],
            })

    return gaps


def open_gap_ids(gaps: Optional[List[dict]]) -> set:
    return {g["gap"] for g in gaps}


def operator_fills_gap(ds, name: str, gap_id: str) -> bool:
    """Does this operator card provide the capability that closes gap_id?"""
    op = ds.operator(name)
    if not op:
        return False
    if gap_id == "anti_air":
        return _has_anti_air(op)
    if gap_id == "refraction":
        return _is_arts_dealer(op) or _has_pierce_or_true(op)
    if gap_id == "silence":
        return _has_silence(op)
    return False


def item_fills_gap(ds, name: str, gap_id: str) -> bool:
    """Does this equipment card provide the capability that closes gap_id?

    Currently only silence has an in-mode equipment answer (奥术法阵). Reads the
    parsed structured mechanics first, then falls back to the raw-item keyword
    rule shared with counters.item_counter_tag.
    """
    if gap_id != "silence":
        return False
    structured = ds.item_structured(name)
    if structured and "silence" in (structured.get("mechanics") or []):
        return True
    from .counters import item_counter_tag
    raw = ds.item(name)
    return bool(raw and item_counter_tag(raw) == "silence")


def operator_gap_bonus(ds, name: str, gaps: Optional[List[dict]]):
    """Additive bonus + human reasons for an operator card against open gaps."""
    ids = open_gap_ids(gaps)
    if not ids:
        return 0.0, []
    filled = [g for g in gaps if operator_fills_gap(ds, name, g["gap"])]
    return _gap_bonus_for_filled(filled)


def item_gap_bonus(ds, name: str, gaps: Optional[List[dict]]):
    """Additive bonus + human reasons for an equipment card against open gaps."""
    ids = open_gap_ids(gaps)
    if not ids:
        return 0.0, []
    filled = [g for g in gaps if item_fills_gap(ds, name, g["gap"])]
    return _gap_bonus_for_filled(filled)
