# -*- coding: utf-8 -*-
"""Deterministic hard-rule layer.

Everything here is exact game math/constraints. The LLM never overrides these;
it only narrates choices the engine already validated.
"""
from .model import GameState, ShopCard, BoardUnit
from .data import Dataset
from . import economy as econ


class Rules:
    def __init__(self, ds: Dataset):
        self.ds = ds
        self.ec = ds.economy

    # ---- economy ----
    def current_upgrade_price(self, state: GameState, rounds_at_level: int) -> "int|None":
        """Initial price minus one per round held at this level, floored at 0."""
        init = self.ds.upgrade_price(state.dispatch_level, state.difficulty)
        if init is None:
            return None  # already max level
        return max(0, init - max(0, rounds_at_level))

    def can_afford(self, gold: int, cost: int) -> bool:
        return gold >= cost

    def refresh_cost(self) -> int:
        return self.ec["refresh_cost"]

    def buy_operator_cost(self) -> int:
        return self.ec["buy_operator_cost"]

    def card_buy_price(self, card: ShopCard) -> int:
        """Actual buy price for a shop operator: explicit card price wins,
        otherwise derive from shop tier plus 整备能力 overrides."""
        if card.price is not None:
            return int(card.price)
        op = self.ds.operator(card.name)
        if op is not None:
            return econ.buy_price(self.ds, op)
        return self.ec["buy_operator_cost"]

    def operator_sell_price(self, name: str, advanced: bool = False):
        op = self.ds.operator(name)
        if op is None:
            return self.ec.get("default_sell_price", 1)
        return econ.sell_price(self.ds, op, advanced=advanced)

    # ---- shop validity ----
    def violates_tier_gate(self, card: ShopCard, dispatch_level: int) -> bool:
        """Shop operators must not exceed dispatch level (free reward excepted)."""
        if card.kind != "operator" or card.tier is None:
            return False
        return card.tier > dispatch_level

    # ---- board / bonds ----
    def bond_counts(self, state: GameState) -> dict:
        """Distinct deployed/held operator names contributing to each bond."""
        counts = {}
        for u in state.board:
            op = self.ds.operator(u.name)
            bonds = op["bonds"] if op else (u.bonds or [])
            for b in bonds:
                counts.setdefault(b, set()).add(u.name)
        return {b: len(names) for b, names in counts.items()}

    def bond_status(self, state: GameState) -> list:
        """Per-bond activation status: have / need / active."""
        counts = self.bond_counts(state)
        out = []
        for name, have in counts.items():
            need = self.ds.bond_need(name)
            out.append({
                "bond": name, "have": have, "need": need,
                "active": bool(need and have >= need),
            })
        return sorted(out, key=lambda x: (x["active"], x["have"]), reverse=True)

    def merge_ready(self, state: GameState) -> list:
        """Operators holding >= the merge count (3) -> ready to promote to elite."""
        n = self.ec["merge_operator_count"]
        return [u.name for u in state.board if u.count >= n and not u.elite]

    # ---- items ----
    def item_cap_reached(self, unit: BoardUnit) -> bool:
        # items-per-unit is tracked outside BoardUnit for now; expose constant
        return False

    def hand_full(self, state: GameState) -> bool:
        held = sum(u.count for u in state.board)
        return held >= self.ec["max_hand"]
