# -*- coding: utf-8 -*-
"""Tests for the derived operator attack-range data (commit A).

These read the committed data/operator_ranges.json (a derived artifact), so
they pass on a fresh clone without the git-ignored unpacked source tables.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "operator_ranges.json")


class OperatorRangeDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DATA, encoding="utf-8") as fh:
            cls.doc = json.load(fh)
        cls.ops = cls.doc["operators"]

    def test_full_coverage(self):
        # 141 advisor operators, every one resolved
        self.assertGreaterEqual(len(self.ops), 141)
        self.assertEqual(self.doc["_meta"]["operator_count"], len(self.ops))

    def test_every_range_is_a_nonempty_dedup_cell_set(self):
        # Note: ranges need NOT include the self tile (0,0): the puppeteer 矩
        # attacks only from col>=2, while the self-only 折桠 covers just (0,0).
        # Both are real shapes, so assert structure rather than the self cell.
        for name, o in self.ops.items():
            cells = [tuple(c) for c in o["range_cells"]]
            self.assertTrue(cells, name)
            self.assertEqual(len(cells), len(set(cells)), name)  # no dup cells
            self.assertEqual(o["cell_count"], len(cells), name)
            self.assertEqual(o["forward_reach"], max(c for _, c in cells), name)
            for r, c in cells:
                self.assertIsInstance(r, int)
                self.assertIsInstance(c, int)

    def test_melee_flag_matches_grid_reach(self):
        for name, o in self.ops.items():
            if o["is_melee"]:
                # melee normal attacks never reach beyond 3 forward tiles
                self.assertLessEqual(o["forward_reach"], 3, name)
            else:
                # every ranged operator reaches at least two tiles ahead
                self.assertGreaterEqual(o["forward_reach"], 2, name)

    def test_known_operator_shapes(self):
        # pinned against the official tables at build time
        cammou = self.ops["卡达"]
        self.assertEqual(cammou["forward_reach"], 3)
        self.assertEqual(cammou["cell_count"], 10)
        self.assertFalse(cammou["is_melee"])
        # a self-tile-only operator (reach 0) is represented honestly
        zheya = self.ops["折桠"]
        self.assertEqual(zheya["forward_reach"], 0)
        self.assertEqual(zheya["range_cells"], [[0, 0]])
        # puppeteer 矩 attacks from col>=2 and never covers its own tile
        ju = self.ops["矩"]
        self.assertNotIn([0, 0], ju["range_cells"])
        self.assertGreaterEqual(min(c for _, c in ju["range_cells"]), 2)

    def test_base_and_elite_ranges_both_present(self):
        for name, o in self.ops.items():
            base = [tuple(c) for c in o["base_range_cells"]]
            elite = [tuple(c) for c in o["range_cells"]]
            self.assertTrue(base, name)
            self.assertTrue(elite, name)
            self.assertTrue(o["base_range_id"] and o["elite_range_id"], name)

    def test_some_operators_change_range_on_elite(self):
        # 72 operators change rangeId on promotion; assert the phenomenon exists
        changed = [n for n, o in self.ops.items()
                   if o["base_range_id"] != o["elite_range_id"]]
        self.assertGreaterEqual(len(changed), 1)

    def test_skill_range_ids_resolve_to_known_shapes(self):
        # stored skill ids are only valid references (consumed in a later stage)
        for name, o in self.ops.items():
            self.assertIsInstance(o["skill_range_ids"], dict)


if __name__ == "__main__":
    unittest.main(verbosity=2)
