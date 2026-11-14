# -*- coding: utf-8 -*-
"""Data model for a single shop/rest-phase snapshot.

The vision layer (or manual input / a future LLM) produces a GameState.
The decision engine only reads this structure, so recognition and strategy
stay fully decoupled and independently testable.
"""
from dataclasses import dataclass, field, asdict
from typing import List, Optional

DIFFICULTIES = ("standard", "hard_abyss", "speed")


@dataclass
class ShopCard:
    """One slot in the dispatch center (shop)."""
    kind: str                      # "operator" | "item"
    name: str                      # recognized operator / item name
    tier: Optional[int] = None     # shop tier 1..6 (operator) or item tier
    price: Optional[int] = None
    bond: Optional[str] = None     # primary bond shown, if any
    raw: Optional[dict] = None     # original recognition payload / confidence


@dataclass
class BoardUnit:
    """An operator already owned (on field or in reserve)."""
    name: str
    count: int = 1                 # copies held toward the 3-copy merge
    elite: bool = False            # promoted (精锐) form
    tier: Optional[int] = None
    bonds: List[str] = field(default_factory=list)


@dataclass
class GameState:
    round: int = 1
    gold: int = 0
    dispatch_level: int = 1        # 调度中心等级 1..6
    difficulty: str = "standard"   # one of DIFFICULTIES
    # Act3 "Guard Protocol: Regulation" level 1..20, chosen at run start
    # (OCR-readable before the ban/bond pick). DISTINCT from dispatch_level
    # (the shop tier 1..6): this one selects the leader-HP multiplier curve
    # (regulation_hp) and maps to battleDataDict mode_single_<L>. None when
    # unknown, in which case clear-margin falls back to the difficulty mode and
    # applies no HP multiplier. Backward compatible (older states omit it).
    regulation_level: Optional[int] = None
    target_bond: Optional[str] = None   # user-declared build direction, if any
    shop: List[ShopCard] = field(default_factory=list)
    board: List[BoardUnit] = field(default_factory=list)
    frozen: bool = False
    # RunProfile enemy picture: keys from data/enemy_traits.json (e.g.
    # ["stealth", "flying"]). Empty/neutral -> counter scoring contributes 0.
    enemy_types: List[str] = field(default_factory=list)
    # Canonical enemy NAMES recognized from the magnifier panel, kept in OCR
    # top-to-bottom order (de-duplicated). enemy_types is the compressed trait
    # view used by today's scoring; enemy_names preserves the concrete wave so
    # per-enemy stats (data/enemy_stats.json) and special-ability counters can
    # drive in-run adjustments later. Recognized ordinary filler is included;
    # unrecognized OCR text never reaches here (it is logged upstream).
    enemy_names: List[str] = field(default_factory=list)
    # In-run draft bans. Banned operators are never recommended as buys; banned
    # bonds remove lineups built on them (compass/lineup layer) rather than
    # vetoing every card that merely shares the bond. Both default empty, so
    # existing states behave exactly as before.
    banned_operators: List[str] = field(default_factory=list)
    banned_bonds: List[str] = field(default_factory=list)
    # Optional in-run buff inputs (default empty -> neutral, backward compatible).
    # bond_stacks: activated bond name -> current stack count, from the future
    #   board ledger/OCR. When absent, an activated bond still contributes its
    #   stack-0 base panel bonus; per-stack growth stays 0 until provided.
    bond_stacks: dict = field(default_factory=dict)
    # equipment: operator name -> list of equipped item names. Not derivable
    #   from the shop OCR yet; when empty, item atk buffs are simply not applied.
    equipment: dict = field(default_factory=dict)
    note: str = ""

    def to_dict(self):
        return asdict(self)


def state_from_dict(obj: dict) -> GameState:
    shop = [ShopCard(**c) for c in obj.get("shop", [])]
    board = [BoardUnit(**b) for b in obj.get("board", [])]
    return GameState(
        round=obj.get("round", 1),
        gold=obj.get("gold", 0),
        dispatch_level=obj.get("dispatch_level", 1),
        difficulty=obj.get("difficulty", "standard"),
        regulation_level=obj.get("regulation_level"),
        target_bond=obj.get("target_bond"),
        shop=shop, board=board,
        frozen=obj.get("frozen", False),
        enemy_types=obj.get("enemy_types", []),
        enemy_names=obj.get("enemy_names", []),
        banned_operators=obj.get("banned_operators", []),
        banned_bonds=obj.get("banned_bonds", []),
        bond_stacks=obj.get("bond_stacks", {}) or {},
        equipment=obj.get("equipment", {}) or {},
        note=obj.get("note", ""),
    )
