# -*- coding: utf-8 -*-
"""Board (owned-operator) input layer.

The decision engine needs the owned board to count bond headcount, detect
3-copy merges and drive milestone scoring (e.g. the Leithanien summon line).
The shop-band OCR only reads the *shop*, so the board enters through a separate
channel. This module is that single entry point:

  * today: a hand-written board JSON (--board board.json);
  * later: the board/chessboard OCR will emit the same List[BoardUnit] shape.

Keeping one parser means the vision output and the manual file share validation
and dataset enrichment. Pure stdlib, no OCR/PIL dependency, fully deterministic.

Accepted input shapes (all tolerant):
  ["地灵", "复奏"]
  [{"name": "地灵", "count": 2}, {"name": "复奏"}]
  {"board": ["地灵", "复奏"]}

Unknown names are NOT fabricated into units: they are skipped and returned in
`warnings` so the caller can surface them. Known names get their bonds/tier
enriched from the dataset even when the hand file omits them.
"""
import json
from typing import List, Tuple

from .data import Dataset
from .model import BoardUnit


def load_board_file(path: str, ds: Dataset) -> Tuple[List[BoardUnit], List[str]]:
    """Read a board JSON file and parse it into validated BoardUnits."""
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return parse_board(raw, ds)


def parse_board(raw, ds: Dataset) -> Tuple[List[BoardUnit], List[str]]:
    """Map any accepted board input shape to (BoardUnits, warnings).

    Same-name entries are merged by summing count. Dataset-known names are
    enriched with bonds/tier; unknown names are skipped with a warning.
    """
    if isinstance(raw, dict) and "board" in raw:
        raw = raw["board"]
    if not isinstance(raw, list):
        raise ValueError("board input must be a list or {'board': [...]} object")

    warnings: List[str] = []
    # name -> accumulated fields, so duplicate hand-file rows merge cleanly.
    merged = {}
    order = []
    for entry in raw:
        name, count, elite, tier, bonds = _unpack_entry(entry)
        if not name:
            warnings.append("跳过缺少 name 的阵容条目: %r" % (entry,))
            continue
        op = ds.operator(name)
        if op is None:
            warnings.append("未知干员名，已跳过（不在 operators.json）: %s" % name)
            continue
        if name not in merged:
            order.append(name)
            merged[name] = {
                "count": 0, "elite": False, "tier": None, "bonds": None,
            }
        slot = merged[name]
        slot["count"] += max(1, int(count or 1))
        # any elite row promotes the merged unit; explicit data wins once.
        slot["elite"] = slot["elite"] or bool(elite)
        if tier is not None:
            slot["tier"] = int(tier)
        if bonds:
            slot["bonds"] = list(bonds)

    units: List[BoardUnit] = []
    for name in order:
        slot = merged[name]
        op = ds.operator(name)
        # Enrich from the dataset unless the hand file overrode the field.
        bonds = slot["bonds"] if slot["bonds"] is not None else list(op.get("bonds", []))
        tier = slot["tier"] if slot["tier"] is not None else op.get("shop_tier")
        units.append(BoardUnit(
            name=name, count=slot["count"], elite=slot["elite"],
            tier=tier, bonds=bonds,
        ))
    return units, warnings


def _unpack_entry(entry):
    """Normalize one row (string or dict) to (name, count, elite, tier, bonds)."""
    if isinstance(entry, str):
        return entry, 1, False, None, None
    if isinstance(entry, dict):
        return (
            entry.get("name"),
            entry.get("count", 1),
            entry.get("elite", False),
            entry.get("tier"),
            entry.get("bonds"),
        )
    return None, 1, False, None, None
