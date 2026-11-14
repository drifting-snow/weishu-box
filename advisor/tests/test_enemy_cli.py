# -*- coding: utf-8 -*-
"""CLI wiring tests for --enemy-shot (stdlib-only; OCR is mocked).

The real OCR model is optional and exercised only by manual smoke tests. Here
advisor.cli._resolve_enemy_shot is patched so we verify the merge/echo logic
deterministically without rapidocr/PIL.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from advisor import cli


def _write_state(td, **over):
    state = {
        "round": 2, "gold": 10, "dispatch_level": 2,
        "target_bond": "莱塔尼亚", "shop": [], "board": [],
    }
    state.update(over)
    path = os.path.join(td, "state.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(state, fh, ensure_ascii=False)
    return path


class EnemyShotWiringTest(unittest.TestCase):
    def test_ocr_trait_keys_reach_engine_output(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = _write_state(td)
            out_path = os.path.join(td, "out.json")
            fake = (["stealth"], ["寻险水手"], ["[enemy] 寻险水手 -> INVISIBLE"])
            with mock.patch.object(cli, "_resolve_enemy_shot", return_value=fake):
                cli.run(state_path=state_path, enemy_shot_path="panel.png",
                        out_path=out_path)
            with open(out_path, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        self.assertEqual(data["state"]["enemy_types"], ["stealth"])
        self.assertEqual(data["state"]["enemy_names"], ["寻险水手"])

    def test_manual_and_ocr_enemy_types_merge_dedup(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = _write_state(td)
            out_path = os.path.join(td, "out.json")
            # OCR supplies stealth + a duplicate flying; manual gives flying.
            fake = (["stealth", "flying"], ["寻险水手", "源石虫"], [])
            with mock.patch.object(cli, "_resolve_enemy_shot", return_value=fake):
                cli.run(state_path=state_path, enemy_shot_path="panel.png",
                        enemy_types=["flying"], out_path=out_path)
            with open(out_path, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        # manual first, OCR supplements, flying de-duplicated
        self.assertEqual(data["state"]["enemy_types"], ["flying", "stealth"])
        # concrete names survive too, including an ordinary untyped filler enemy
        self.assertEqual(data["state"]["enemy_names"], ["寻险水手", "源石虫"])

    def test_enemy_shot_alone_builds_empty_state(self):
        # No --state/--shot: enemy panel alone still runs counter scoring.
        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "out.json")
            fake = (["flying"], ["猎狗pro"], [])
            with mock.patch.object(cli, "_resolve_enemy_shot", return_value=fake):
                cli.run(enemy_shot_path="panel.png", out_path=out_path)
            with open(out_path, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        self.assertEqual(data["state"]["enemy_types"], ["flying"])
        self.assertEqual(data["state"]["enemy_names"], ["猎狗pro"])
        self.assertIn("recommendations", data)

    def test_no_enemy_input_echoes_empty_list(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = _write_state(td)
            out_path = os.path.join(td, "out.json")
            cli.run(state_path=state_path, out_path=out_path)
            with open(out_path, encoding="utf-8") as fh:
                data = json.loads(fh.read())
        self.assertEqual(data["state"]["enemy_types"], [])
        self.assertEqual(data["state"]["enemy_names"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
