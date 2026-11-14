# -*- coding: utf-8 -*-
"""Stdlib tests for the trigger-timing extractor that recovers the angle-bracket
tags clean() drops. Run: python -m unittest tests.test_parse_timing -v"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, ROOT)


def load():
    with open(os.path.join(DATA, "operator_timing.json"), encoding="utf-8") as f:
        return json.load(f)


class TimingExtractionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = load()
        cls.by = cls.d["by_operator"]

    def test_extractor_runs_deterministically(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "parse_timing.py")],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(load()["records"], self.d["records"])

    def test_nine_timing_tags_covered(self):
        self.assertEqual(set(self.d["_meta"]["timing_tags"]), {
            "休整期结束时", "进入休整期时", "休整期开始时", "获得时", "售出时",
            "刷新时", "开启技能时", "战斗开始时", "战斗结束时"})

    def test_mowang_is_end_of_rest(self):
        # the case that exposed the systematic clean() data loss
        self.assertIn("魔王", self.by)
        for form, tags in self.by["魔王"].items():
            self.assertEqual(tags, ["休整期结束时"])

    def test_xiren_is_on_acquire(self):
        self.assertEqual(self.by["锡人"]["基础"], ["获得时"])

    def test_dual_timing_operator(self):
        # 寒檀 carries both rest-start and rest-end tags
        self.assertEqual(set(self.by["寒檀"]["基础"]),
                         {"休整期开始时", "休整期结束时"})

    def test_battle_end_timing(self):
        self.assertEqual(self.by["夜莺"]["基础"], ["战斗结束时"])

    def test_refresh_timing(self):
        self.assertEqual(self.by["复奏"]["基础"], ["刷新时"])

    def test_no_html_left_in_traits(self):
        for rec in self.d["records"]:
            self.assertNotIn("<span", rec["trait"])
            self.assertNotIn("<div", rec["trait"])

    def test_operator_count_matches_probe(self):
        # 72 operators carry at least one explicit trigger-timing tag
        self.assertEqual(self.d["_meta"]["operator_count"], len(self.by))
        self.assertGreaterEqual(len(self.by), 70)


if __name__ == "__main__":
    unittest.main(verbosity=2)
