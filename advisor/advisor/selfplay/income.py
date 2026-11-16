# -*- coding: utf-8 -*-
"""Per-round gold for self-play from community ASSUMED ``data/gold_income.json``.

Formula (default): ``income(r) = min(3 + r, income_cap)`` with ``income_cap=12``.
R1–R3 (4/5/6) are community-verified; R4+ and the cap remain ASSUMED.

No TFT-style interest: unspent gold must be cleared at rest end
(``interest.base=false``, ``economy.unspent_carryover=false``). Episode assigns
``st.gold = gold_for_round(r)`` at each rest start (replace, do not add).
"""
from __future__ import annotations

import json
import os
from typing import Dict, Mapping, Optional

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
GOLD_INCOME_PATH = os.path.join(DATA_DIR, "gold_income.json")

_cache: Optional[dict] = None


def load_gold_income(path: str = GOLD_INCOME_PATH) -> dict:
    global _cache
    if path == GOLD_INCOME_PATH and _cache is not None:
        return _cache
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if path == GOLD_INCOME_PATH:
        _cache = doc
    return doc


def clear_gold_income_cache() -> None:
    global _cache
    _cache = None


def income_formula(round_no: int, doc: Optional[Mapping] = None) -> int:
    """Community ASSUMED: min(3 + r, income_cap)."""
    doc = doc or load_gold_income()
    cap = int(doc.get("income_cap") or 12)
    r = int(round_no)
    if r < 1:
        return 0
    return min(3 + r, cap)


def table_for_mode(doc: Optional[Mapping] = None,
                   mode: str = "standard_or_protocol") -> Dict[int, int]:
    """Materialized round→gold map (index 0 unused in JSON)."""
    doc = doc or load_gold_income()
    block = (doc.get("by_mode") or {}).get(mode) or {}
    arr = block.get("gold_by_round")
    out: Dict[int, int] = {}
    if not isinstance(arr, list):
        return out
    for i, v in enumerate(arr):
        if i == 0:
            continue
        if v is None:
            continue
        out[i] = int(v)
    return out


def gold_for_round(
    round_no: int,
    table: Optional[Mapping[int, int]] = None,
    flat: Optional[int] = None,
    *,
    doc: Optional[Mapping] = None,
    prefer_formula: bool = True,
) -> int:
    """Gold granted at the start of rest for ``round_no``.

    Priority: ``flat`` override → explicit ``table`` → formula / JSON table.
    Default uses the ASSUMED formula so cap/verified rows stay consistent.
    """
    if flat is not None:
        return int(flat)
    if table is not None:
        if round_no in table:
            return int(table[round_no])
        if table:
            return int(table[max(table)])
        return income_formula(round_no, doc)

    doc = doc or load_gold_income()
    if prefer_formula:
        return income_formula(round_no, doc)

    built = table_for_mode(doc)
    if round_no in built:
        return int(built[round_no])
    return income_formula(round_no, doc)


def income_disclaimer(doc: Optional[Mapping] = None) -> str:
    doc = doc or load_gold_income()
    return (
        "gold_income ASSUMED=%s official=%s formula=%s cap=%s verified_through_r%s"
        % (
            doc.get("assumed"),
            doc.get("official"),
            doc.get("formula"),
            doc.get("income_cap"),
            doc.get("verified_through_round"),
        )
    )


ASSUMED_INCOME_NOTE = (
    "ASSUMED community gold_income.json: min(3+r,12); "
    "R1–R3 verified, R4+ assumed; no interest / unspent clears at rest end."
)


def _assumed_round_income() -> Dict[int, int]:
    """Materialized table for callers that want a dict (lazy)."""
    return table_for_mode()


# Eager snapshot for ``from income import ASSUMED_ROUND_INCOME`` style imports.
ASSUMED_ROUND_INCOME: Dict[int, int] = table_for_mode()
