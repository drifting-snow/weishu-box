# -*- coding: utf-8 -*-
"""ASSUMED per-round gold grants for self-play scaffolding.

Official act3 rest-phase income / interest is NOT in data/economy.json
(unspent_carryover is false, but the grant table is unpublished here).
These numbers are tunable placeholders for Monte Carlo loops only — never
cite them as Hypergryph facts.
"""
from __future__ import annotations

# Flat early income with a mild ramp. Override via episode(income=...).
ASSUMED_ROUND_INCOME = {
    1: 10,
    2: 10,
    3: 11,
    4: 11,
    5: 12,
    6: 12,
    7: 13,
    8: 13,
    9: 14,
    10: 14,
    11: 15,
    12: 15,
    13: 16,
    14: 16,
    15: 16,
}

ASSUMED_INCOME_NOTE = (
    "ASSUMED self-play income only; not from official tables. "
    "Override with --income-flat or a custom map."
)


def gold_for_round(round_no: int, table=None, flat: int | None = None) -> int:
    if flat is not None:
        return int(flat)
    table = table or ASSUMED_ROUND_INCOME
    if round_no in table:
        return int(table[round_no])
    # Beyond table: hold last known value.
    if table:
        return int(table[max(table)])
    return 10
