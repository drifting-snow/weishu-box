# -*- coding: utf-8 -*-
"""Unit tests for advisor/enemy_catalog.py (three-state name resolution).

Pure-logic tests with injectable tactical catalog + full name index, so they
are independent of the exact shipped generated data. A few smoke tests pin the
real files built by tools/build_enemy_catalog.py. No OCR / PIL here.
"""
import json
import os
import tempfile
import unittest

from advisor.enemy_catalog import (
    load_enemy_catalog, load_enemy_name_index, resolve_enemy, resolve_enemies,
    validate_catalog,
)

# Tactical catalog (only typed enemies).
CATALOG = {
    "_meta": {"category_bridge": {
        "FLY": "flying", "INVISIBLE": "stealth",
        "DOT": "sustained", "REBORN": "revival"}},
    "enemies": {
        "寻险水手": {
            "enemy_ids": ["enemy_10043_sailor"], "ac_types": ["INVISIBLE"],
            "trait_keys": ["stealth"], "rank": "NORMAL", "is_flying": False,
            "apply_way": "MELEE", "sources": ["training"],
            "inherited_type": False, "needs_review": False,
        },
        "双核掠食者": {
            "enemy_ids": ["enemy_x"], "ac_types": ["DOT", "REBORN"],
            "trait_keys": ["sustained", "revival"], "rank": "ELITE",
            "is_flying": False, "apply_way": "MELEE", "sources": ["training"],
            "inherited_type": False, "needs_review": False,
        },
        "复核飞怪": {
            "enemy_ids": ["enemy_y"], "ac_types": ["FLY"],
            "trait_keys": ["flying"], "rank": "NORMAL", "is_flying": True,
            "apply_way": "ALL", "sources": ["special"],
            "inherited_type": False, "needs_review": True,
        },
    },
}

# Full name index: tactical enemies + ordinary untyped filler (源石虫).
NAME_INDEX = {
    "_meta": {"counts": {"unique_names": 4, "with_tactical_type": 3}},
    "names": {
        "寻险水手": {"enemy_ids": ["enemy_10043_sailor"], "rank": "NORMAL",
                  "is_flying": False, "tactical_types": ["INVISIBLE"]},
        "双核掠食者": {"enemy_ids": ["enemy_x"], "rank": "ELITE",
                   "is_flying": False, "tactical_types": ["DOT", "REBORN"]},
        "复核飞怪": {"enemy_ids": ["enemy_y"], "rank": "NORMAL",
                  "is_flying": True, "tactical_types": ["FLY"]},
        "源石虫": {"enemy_ids": ["enemy_1007_slime"], "rank": "NORMAL",
                "is_flying": False, "tactical_types": []},
    },
}


def _write(payload):
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    return path


class ResolveOneTest(unittest.TestCase):
    def setUp(self):
        self.cat_path = _write(CATALOG)
        self.idx_path = _write(NAME_INDEX)
        self.catalog = load_enemy_catalog(self.cat_path)
        self.name_index = load_enemy_name_index(self.idx_path)

    def tearDown(self):
        os.unlink(self.cat_path)
        os.unlink(self.idx_path)

    def test_tactical_enemy_resolves_trait_keys(self):
        r = resolve_enemy("寻险水手", self.catalog, self.name_index)
        self.assertEqual(r["status"], "tactical")
        self.assertTrue(r["recognized"] and r["matched"])
        self.assertEqual(r["ac_types"], ["INVISIBLE"])
        self.assertEqual(r["ac_type"], "INVISIBLE")
        self.assertEqual(r["trait_keys"], ["stealth"])
        self.assertIsNone(r["warning"])

    def test_multi_type_keeps_all_keys(self):
        r = resolve_enemy("双核掠食者", self.catalog, self.name_index)
        self.assertEqual(r["ac_types"], ["DOT", "REBORN"])
        self.assertEqual(r["trait_keys"], ["sustained", "revival"])

    def test_ocr_truncated_name_still_snaps(self):
        r = resolve_enemy("险水手", self.catalog, self.name_index)
        self.assertEqual(r["status"], "tactical")
        self.assertEqual(r["name"], "寻险水手")
        self.assertEqual(r["trait_keys"], ["stealth"])

    def test_ordinary_filler_is_untyped_silent(self):
        # 源石虫 is a known official enemy with no tactical type.
        r = resolve_enemy("源石虫", self.catalog, self.name_index)
        self.assertTrue(r["recognized"])
        self.assertEqual(r["status"], "untyped")
        self.assertEqual(r["trait_keys"], [])
        self.assertIsNone(r["warning"])  # not an error

    def test_low_confidence_short_truncation_refused(self):
        # '石虫' vs 源石虫 similarity is 0.8, below the conservative bar (and
        # the real full index contains many 源石虫 variants), so the matcher
        # refuses to guess -> unknown, not a possibly-wrong untyped snap.
        r = resolve_enemy("石虫", self.catalog, self.name_index)
        self.assertEqual(r["status"], "unknown")
        self.assertEqual(r["trait_keys"], [])

    def test_truly_unknown_flagged(self):
        r = resolve_enemy("不存在的新怪", self.catalog, self.name_index)
        self.assertEqual(r["status"], "unknown")
        self.assertFalse(r["recognized"])
        self.assertEqual(r["trait_keys"], [])
        self.assertIn("无此名称", r["warning"])

    def test_empty_input(self):
        r = resolve_enemy("   ", self.catalog, self.name_index)
        self.assertEqual(r["status"], "unknown")
        self.assertIsNotNone(r["warning"])

    def test_needs_review_surfaces_warning(self):
        r = resolve_enemy("复核飞怪", self.catalog, self.name_index)
        self.assertTrue(r["needs_review"])
        self.assertIn("needs_review", r["warning"])


class ResolveBatchTest(unittest.TestCase):
    def setUp(self):
        self.cat_path = _write(CATALOG)
        self.idx_path = _write(NAME_INDEX)
        self.catalog = load_enemy_catalog(self.cat_path)
        self.name_index = load_enemy_name_index(self.idx_path)

    def tearDown(self):
        os.unlink(self.cat_path)
        os.unlink(self.idx_path)

    def test_dedupes_trait_keys(self):
        r = resolve_enemies(["寻险水手", "险水手"], self.catalog, self.name_index)
        self.assertEqual(r["trait_keys"], ["stealth"])
        self.assertEqual(r["unknown"], [])

    def test_untyped_not_counted_as_unknown(self):
        r = resolve_enemies(["源石虫", "寻险水手"], self.catalog, self.name_index)
        self.assertEqual(r["trait_keys"], ["stealth"])
        self.assertEqual(r["unknown"], [])  # filler is recognized, not unknown
        statuses = {x["name"]: x["status"] for x in r["resolutions"]}
        self.assertEqual(statuses["源石虫"], "untyped")

    def test_only_real_unknown_collected(self):
        r = resolve_enemies(["源石虫", "神秘新怪"], self.catalog, self.name_index)
        self.assertEqual(r["trait_keys"], [])
        self.assertEqual(r["unknown"], ["神秘新怪"])

    def test_names_preserve_recognized_canonical_names(self):
        # tactical + ordinary filler both surface; unknown text is excluded.
        r = resolve_enemies(["寻险水手", "源石虫", "神秘新怪"],
                            self.catalog, self.name_index)
        self.assertEqual(r["names"], ["寻险水手", "源石虫"])

    def test_names_dedup_preserve_order(self):
        r = resolve_enemies(["寻险水手", "险水手", "寻险水手"],
                            self.catalog, self.name_index)
        self.assertEqual(r["names"], ["寻险水手"])


class ValidateCatalogTest(unittest.TestCase):
    def test_clean_pair_passes(self):
        cp, ip = _write(CATALOG), _write(NAME_INDEX)
        try:
            self.assertEqual(
                validate_catalog(load_enemy_catalog(cp), load_enemy_name_index(ip)),
                [])
        finally:
            os.unlink(cp); os.unlink(ip)

    def test_index_missing_tactical_entry_flagged(self):
        bad_cat = json.loads(json.dumps(CATALOG))
        del bad_cat["enemies"]["复核飞怪"]  # index still marks it FLY-typed
        cp, ip = _write(bad_cat), _write(NAME_INDEX)
        try:
            problems = validate_catalog(load_enemy_catalog(cp),
                                        load_enemy_name_index(ip))
            self.assertTrue(any("复核飞怪" in p and "缺失" in p for p in problems))
        finally:
            os.unlink(cp); os.unlink(ip)

    def test_actype_trait_misalignment_flagged(self):
        bad = json.loads(json.dumps(CATALOG))
        bad["enemies"]["寻险水手"]["trait_keys"] = ["flying"]
        cp, ip = _write(bad), _write(NAME_INDEX)
        try:
            problems = validate_catalog(load_enemy_catalog(cp),
                                        load_enemy_name_index(ip))
            self.assertTrue(any("不一致" in p for p in problems))
        finally:
            os.unlink(cp); os.unlink(ip)


class ShippedDataTest(unittest.TestCase):
    """Pin the files generated from the official act3 autochess tables."""

    def test_shipped_pair_consistent(self):
        self.assertEqual(validate_catalog(), [])

    def test_known_stealth_enemy(self):
        r = resolve_enemy("寻险水手")
        self.assertEqual(r["status"], "tactical")
        self.assertEqual(r["trait_keys"], ["stealth"])

    def test_ordinary_filler_untyped(self):
        r = resolve_enemy("源石虫")
        self.assertEqual(r["status"], "untyped")
        self.assertEqual(r["trait_keys"], [])

    def test_all_nine_trait_types_present(self):
        cat = load_enemy_catalog()
        used = set()
        for e in cat["enemies"].values():
            used.update(e["trait_keys"])
        self.assertEqual(used, {
            "special", "flying", "multi_hit", "elemental", "sustained",
            "stealth", "refraction", "lethal", "revival"})

    def test_name_index_covers_tactical_catalog(self):
        cat = load_enemy_catalog()
        idx = load_enemy_name_index()
        for name in cat["enemies"]:
            self.assertIn(name, idx["names"])
            self.assertTrue(idx["names"][name]["tactical_types"])


if __name__ == "__main__":
    unittest.main()
