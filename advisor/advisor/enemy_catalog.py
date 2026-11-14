# -*- coding: utf-8 -*-
"""Resolve concrete enemy names (OCR'd from the magnifier panel) to tactical
trait keys consumed by advisor/counters.py.

Two generated data files work together (both rebuilt from the official
unpacked tables by tools/build_enemy_catalog.py):

  data/enemy_names.json   -- ALL ~1.8k official enemy names (ordinary filler
                             included), used to recognize OCR text.
  data/enemy_catalog.json -- only the enemies carrying an official in-mode
                             tactical type (the 9 training categories), mapped
                             to our enemy_traits.json trait keys.

That split gives a clean three-state resolution:
  tactical : a known enemy that has tactical type(s) -> contributes trait keys
  untyped  : a known ordinary enemy with no tactical type (e.g. 源石虫) ->
             recognized, contributes nothing, silent (this is normal filler)
  unknown  : name absent from the official index -> new-season enemy or OCR
             garbage; surfaced so a human can notice and/or rebuild the data

Names are fuzzy-snapped through the same matcher as the shop OCR. Pure stdlib
at import time; vision OCR stays in vision/ and is optional.
"""
import json
import os
from typing import List, Optional

from .counters import load_enemy_types
from vision.match_text import match_one

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CATALOG_PATH = os.path.join(DATA_DIR, "enemy_catalog.json")
NAME_INDEX_PATH = os.path.join(DATA_DIR, "enemy_names.json")


def load_enemy_catalog(path: str = CATALOG_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_enemy_name_index(path: str = NAME_INDEX_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _known_trait_keys() -> set:
    return set(load_enemy_types().keys())


def resolve_enemy(ocr_name: str, catalog: Optional[dict] = None,
                  name_index: Optional[dict] = None,
                  correction: Optional[dict] = None) -> dict:
    """Snap one OCR'd enemy name to its official record and tactical type.

    Never raises on an unrecognized name. Returns a three-state result:
    status is "tactical", "untyped" (known ordinary enemy), or "unknown".
    """
    catalog = catalog or load_enemy_catalog()
    name_index = name_index or load_enemy_name_index()
    all_names = list(name_index.get("names", {}).keys())
    raw = (ocr_name or "").strip()
    result = {
        "input": raw, "name": None, "recognized": False, "matched": False,
        "status": "unknown", "trait_keys": [], "ac_types": [], "ac_type": None,
        "rank": None, "is_flying": False, "needs_review": False,
        "warning": None,
    }
    if not raw:
        result["warning"] = "empty enemy name"
        return result

    # Conservative snap: the 1.8k-name index has many near names (x/组长/α), so
    # the aggressive substring rule used for the small shop dictionary would
    # cross-fire here. The matcher enforces a high similarity bar plus a
    # uniqueness gap: single glyphs are refused and crowded near-name races
    # return None (-> unknown) rather than a confident wrong guess.
    canonical = match_one(raw, all_names, correction, conservative=True)
    if canonical is None:
        result["warning"] = "官方敌人索引无此名称（新敌人或 OCR 误识）：%r" % raw
        return result

    idx_entry = name_index["names"][canonical]
    result["recognized"] = True
    result["name"] = canonical
    result["rank"] = idx_entry.get("rank")
    result["is_flying"] = bool(idx_entry.get("is_flying", False))

    tac_types = list(idx_entry.get("tactical_types", []))
    if not tac_types:
        # Known ordinary filler enemy: no tactical counter, silently neutral.
        result["status"] = "untyped"
        return result

    # Tactical enemy: pull the validated trait keys from the tactical catalog.
    tac_entry = catalog.get("enemies", {}).get(canonical)
    valid = _known_trait_keys()
    if tac_entry:
        keys = [k for k in tac_entry.get("trait_keys", []) if k in valid]
        bad = [k for k in tac_entry.get("trait_keys", []) if k not in valid]
        ac_types = list(tac_entry.get("ac_types", tac_types))
        result["needs_review"] = bool(tac_entry.get("needs_review", False))
        result["warning"] = ("名录条目 %s 含未知 trait key：%s" % (canonical, bad)) if bad else None
    else:
        # Fallback: derive from the name index via the bridge (catalog rebuild lag).
        bridge = catalog.get("_meta", {}).get("category_bridge", {})
        ac_types = tac_types
        keys = []
        for t in tac_types:
            tk = bridge.get(t)
            if tk and tk in valid and tk not in keys:
                keys.append(tk)
    result.update({
        "status": "tactical", "matched": True, "trait_keys": keys,
        "ac_types": ac_types, "ac_type": ac_types[0] if ac_types else None,
    })
    if result["needs_review"] and not result["warning"]:
        result["warning"] = "该敌人分类标记 needs_review，建议游戏内复核"
    return result


def resolve_enemies(ocr_names: List[str], catalog: Optional[dict] = None,
                    name_index: Optional[dict] = None,
                    correction: Optional[dict] = None) -> dict:
    """Resolve OCR'd enemy names, aggregating tactical trait keys.

    trait_keys: de-duplicated tactical keys across the wave.
    resolutions: per-name three-state results.
    unknown: names absent from the official index (untyped filler is NOT here).
    """
    catalog = catalog or load_enemy_catalog()
    name_index = name_index or load_enemy_name_index()
    resolutions, unknown, keys, names = [], [], [], []
    for raw in ocr_names:
        r = resolve_enemy(raw, catalog, name_index, correction)
        resolutions.append(r)
        if r["status"] == "unknown":
            unknown.append(r["input"])
        for k in r["trait_keys"]:
            if k not in keys:
                keys.append(k)
        # Preserve every RECOGNIZED canonical name (tactical or ordinary
        # filler) in OCR order, de-duplicated; unknown OCR text is excluded
        # since it has no canonical name. This is the concrete-wave view that
        # complements the compressed trait_keys.
        if r.get("name") and r["name"] not in names:
            names.append(r["name"])
    return {
        "trait_keys": keys,
        "names": names,
        "resolutions": resolutions,
        "unknown": unknown,
    }


def validate_catalog(catalog: Optional[dict] = None,
                     name_index: Optional[dict] = None) -> List[str]:
    """Offline consistency check; returns a list of human-readable problems."""
    catalog = catalog or load_enemy_catalog()
    name_index = name_index or load_enemy_name_index()
    problems = []
    valid_keys = _known_trait_keys()
    bridge = catalog.get("_meta", {}).get("category_bridge", {})
    names = name_index.get("names", {})

    for name, entry in catalog.get("enemies", {}).items():
        ac_types = entry.get("ac_types", [])
        trait_keys = entry.get("trait_keys", [])
        if not entry.get("enemy_ids"):
            problems.append("%s: 缺少 enemy_ids 溯源" % name)
        for ac in ac_types:
            if ac not in bridge:
                problems.append("%s: ac_type %r 不在 category_bridge" % (name, ac))
        for k in trait_keys:
            if k not in valid_keys:
                problems.append("%s: trait key %r 不在 enemy_traits.json" % (name, k))
        mapped = [bridge.get(ac) for ac in ac_types]
        mapped_dedup = [k for k in dict.fromkeys(mapped) if k is not None]
        if mapped_dedup != trait_keys:
            problems.append("%s: ac_types%r 与 trait_keys%r 不一致" %
                            (name, ac_types, trait_keys))
        # every tactical-catalog name must exist in the full index and be typed
        idx = names.get(name)
        if idx is None:
            problems.append("%s: 战术名录有此名但全量索引缺失" % name)
        elif not idx.get("tactical_types"):
            problems.append("%s: 战术名录有类型但全量索引 tactical_types 为空" % name)

    # reverse: index says typed but catalog lacks the entry
    for name, idx in names.items():
        if idx.get("tactical_types") and name not in catalog.get("enemies", {}):
            problems.append("%s: 全量索引标记有战术类型但战术名录缺失" % name)
    return problems
