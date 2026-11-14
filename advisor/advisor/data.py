# -*- coding: utf-8 -*-
"""Load the versioned JSON dataset built by tools/build_data.py."""
import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _load(name):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
        return json.load(f)


class Dataset:
    def __init__(self):
        self.operators = _load("operators.json")
        self.bonds = _load("bonds.json")
        self.items = _load("items.json")
        self.economy = _load("economy.json")
        self.meta = _load("meta.json")
        self._op_by_name = {o["name"]: o for o in self.operators}
        self._item_by_name = {i["name"]: i for i in self.items}
        # structured equipment effects are produced by tools/parse_items.py;
        # tolerate an older build that has not generated the file yet.
        try:
            structured = _load("items_structured.json")["items"]
            self._item_structured = {x["name"]: x for x in structured}
        except FileNotFoundError:
            self._item_structured = {}
        # operator combat power (precise base stats + relative buff tiers),
        # produced by tools/parse_power.py; tolerate an older build.
        try:
            power = _load("operator_power.json")["operators"]
            self._op_power = {x["name"]: x for x in power}
        except FileNotFoundError:
            self._op_power = {}
        self._bond_by_name = {}
        for grp in ("core", "attached"):
            for b in self.bonds[grp]:
                self._bond_by_name[b["name"]] = b

    def operator(self, name):
        return self._op_by_name.get(name)

    def item(self, name):
        return self._item_by_name.get(name)

    def item_structured(self, name):
        """Structured effect record for an item, or None if not parsed yet."""
        return self._item_structured.get(name)

    def operator_power(self, name):
        """Base-stat + buff-tier power record for an operator, or None."""
        return self._op_power.get(name)

    def bond(self, name):
        return self._bond_by_name.get(name)

    def upgrade_price(self, level, difficulty):
        table = self.economy["upgrade_price"].get(
            difficulty, self.economy["upgrade_price"]["standard"])
        return table.get(str(level), table.get(level))

    def slots(self, level, difficulty):
        table = self.economy["slots"].get(difficulty, self.economy["slots"]["standard"])
        return table.get(str(level), table.get(level))

    def bond_need(self, name):
        b = self.bond(name)
        return int(b["need"]) if b and str(b["need"]).isdigit() else None
