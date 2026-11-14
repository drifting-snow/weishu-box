# -*- coding: utf-8 -*-
"""Runtime reader for the per-name special-counter extension layer.

The nine generic tactical categories are scored by advisor/counters.py. This
module adds a NARROW, name-keyed layer on top: only concrete enemies whose
special ability needs a counter their generic category does not express (see
data/enemy_special_cases.json, currently the ice on-death cold-explosion family
-> silence) trigger anything here.

It is deliberately pure and side-effect free so the decision engine can call it
as an additive situational bonus later without changing the core scoring path.
Unknown / unlisted names and generic_covered entries resolve to nothing.
"""
import json
import os
from typing import List, Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data")
SPECIAL_CASES_PATH = os.path.join(DATA_DIR, "enemy_special_cases.json")

_cache = None


def load_special_cases(path: str = SPECIAL_CASES_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _index(doc: dict) -> dict:
    return {c["name"]: c for c in doc.get("special_cases", [])
            if not c.get("generic_covered", False)}


def special_counter_demands(enemy_names: Optional[List[str]],
                            doc: Optional[dict] = None) -> List[dict]:
    """Map the wave's concrete enemy names to special counter demands.

    Returns a de-duplicated list (one per counter_tag) shaped like:
      {"counter_tag": "silence", "mechanic": "...", "enemies": [...],
       "counter_label": "...", "reasons": [per-enemy human text]}
    Empty for an empty/unknown picture or when every enemy is generically
    covered, so callers can treat "no demands" as a no-op additive term.
    """
    if not enemy_names:
        return []
    global _cache
    if doc is None:
        if _cache is None:
            _cache = load_special_cases()
        doc = _cache
    index = _index(doc)

    by_tag = {}
    for name in enemy_names:
        case = index.get(name)
        if not case:
            continue
        tag = case["counter_tag"]
        slot = by_tag.setdefault(tag, {
            "counter_tag": tag,
            "mechanic": case["primary_mechanic"],
            "counter_label": case["counter_label"],
            "enemies": [],
            "reasons": [],
        })
        if name not in slot["enemies"]:
            slot["enemies"].append(name)
        reason = "%s：%s" % (name, case["ability_label"])
        if reason not in slot["reasons"]:
            slot["reasons"].append(reason)
    return list(by_tag.values())


def has_special_counter(enemy_names: Optional[List[str]], counter_tag: str,
                        doc: Optional[dict] = None) -> bool:
    """Convenience predicate: does this wave demand a specific counter?"""
    return any(d["counter_tag"] == counter_tag
               for d in special_counter_demands(enemy_names, doc))
