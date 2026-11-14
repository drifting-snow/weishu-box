# -*- coding: utf-8 -*-
"""Tests for the owned-board input layer (advisor/board_io.py).

Pure stdlib logic: no OCR model, no PIL, no screenshots. The real Dataset is
used so bonds/tier enrichment is checked against actual operator records.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from advisor.data import Dataset
from advisor.board_io import parse_board, load_board_file


class ParseBoardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = Dataset()
        # real Leithanien members present in the shipped dataset
        cls.lei = [o["name"] for o in cls.ds.operators
                   if "莱塔尼亚" in o.get("bonds", [])]
        cls.assertTrue_m = None
        assert len(cls.lei) >= 3, "need several Leithanien operators for tests"

    def test_plain_name_list(self):
        units, warn = parse_board(self.lei[:3], self.ds)
        self.assertEqual(len(units), 3)
        self.assertEqual(warn, [])
        self.assertEqual([u.name for u in units], self.lei[:3])
        # default count and dataset enrichment
        self.assertTrue(all(u.count == 1 for u in units))
        for u in units:
            self.assertIn("莱塔尼亚", u.bonds)
            self.assertIsNotNone(u.tier)

    def test_dict_entries_with_count_and_elite(self):
        raw = [
            {"name": self.lei[0], "count": 2},
            {"name": self.lei[1], "elite": True},
        ]
        units, warn = parse_board(raw, self.ds)
        self.assertEqual(warn, [])
        by = {u.name: u for u in units}
        self.assertEqual(by[self.lei[0]].count, 2)
        self.assertTrue(by[self.lei[1]].elite)
        self.assertEqual(by[self.lei[1]].count, 1)

    def test_wrapped_board_object(self):
        units, warn = parse_board({"board": [self.lei[0]]}, self.ds)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].name, self.lei[0])

    def test_same_name_rows_merge_counts(self):
        raw = [{"name": self.lei[0], "count": 1},
               {"name": self.lei[0], "count": 2}]
        units, warn = parse_board(raw, self.ds)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].count, 3)

    def test_unknown_name_skipped_with_warning(self):
        units, warn = parse_board(["不存在的干员XYZ", self.lei[0]], self.ds)
        self.assertEqual([u.name for u in units], [self.lei[0]])
        self.assertEqual(len(warn), 1)
        self.assertIn("不存在的干员XYZ", warn[0])

    def test_entry_missing_name_skipped(self):
        units, warn = parse_board([{"count": 1}, self.lei[1]], self.ds)
        self.assertEqual([u.name for u in units], [self.lei[1]])
        self.assertTrue(any("name" in w for w in warn))

    def test_explicit_bonds_override_dataset(self):
        raw = [{"name": self.lei[0], "bonds": ["自定义"]}]
        units, _ = parse_board(raw, self.ds)
        self.assertEqual(units[0].bonds, ["自定义"])

    def test_invalid_structure_raises(self):
        with self.assertRaises(ValueError):
            parse_board({"not_board": []}, self.ds)
        with self.assertRaises(ValueError):
            parse_board("just a string", self.ds)

    def test_load_board_file_roundtrip(self):
        obj = {"board": [{"name": self.lei[0], "count": 2}, self.lei[1]]}
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "board.json")
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(obj, fh, ensure_ascii=False)
            units, warn = load_board_file(path, self.ds)
        self.assertEqual(warn, [])
        self.assertEqual(len(units), 2)
        self.assertEqual(units[0].count, 2)


class CliBoardEndToEndTest(unittest.TestCase):
    """--board must reach the engine in --state mode (stdlib-only, no vision)."""

    def test_board_activates_bond_status_in_engine_output(self):
        ds = Dataset()
        lei = [o["name"] for o in ds.operators
               if "莱塔尼亚" in o.get("bonds", [])][:3]
        state = {
            "round": 3, "gold": 20, "dispatch_level": 3,
            "target_bond": "莱塔尼亚",
            "shop": [{"kind": "operator", "name": lei[2], "tier": 2, "price": 3}],
            "board": [],
        }
        with tempfile.TemporaryDirectory() as td:
            state_path = os.path.join(td, "state.json")
            board_path = os.path.join(td, "board.json")
            out_path = os.path.join(td, "out.json")
            with open(state_path, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(state, fh, ensure_ascii=False)
            with open(board_path, "w", encoding="utf-8", newline="\n") as fh:
                json.dump({"board": lei[:2]}, fh, ensure_ascii=False)
            cmd = [sys.executable, "-m", "advisor.cli",
                   "--state", state_path, "--board", board_path,
                   "--out", out_path]
            proc = subprocess.run(cmd, cwd=REPO_ROOT,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=120)
            self.assertEqual(proc.returncode, 0,
                             proc.stderr.decode("utf-8", "replace"))
            with open(out_path, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        # board now drives bond headcount: 莱塔尼亚 shows with have>=2
        bond = next(b for b in data["bond_status"] if b["bond"] == "莱塔尼亚")
        self.assertGreaterEqual(bond["have"], 2)
        # and the third member in the shop surfaces the summon activation reason
        buy = next(a for a in data["recommendations"]
                   if a["verb"] == "buy" and a["target"] == lei[2])
        self.assertIn("小节", buy["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
