# -*- coding: utf-8 -*-
"""CLI encoding regression: stdout/--out must be valid UTF-8 with real Chinese.

Reproduces the Windows GBK/cp936 console mojibake bug by running the CLI in a
subprocess with NO UTF-8 env overrides (the default user environment). The CLI
must itself reconfigure stdio to UTF-8. Uses --state so it runs on stdlib-only
Python without the optional vision stack.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A minimal GameState with a Chinese operator name; engine tolerates unknowns.
STATE_OBJ = {
    "round": 3,
    "gold": 10,
    "dispatch_level": 2,
    "difficulty": "standard",
    "shop": [
        {"kind": "operator", "name": "真理", "tier": 2, "price": 3},
        {"kind": "item", "name": "坚守盾牌", "tier": 1, "price": 1},
    ],
    "board": [],
}


def _clean_env():
    env = dict(os.environ)
    # Force the legacy/default code path; do not inherit any UTF-8 opt-in.
    env.pop("PYTHONIOENCODING", None)
    env.pop("PYTHONUTF8", None)
    return env


class CliEncodingTest(unittest.TestCase):
    def _run(self, *extra_args):
        with tempfile.TemporaryDirectory() as td:
            state_path = os.path.join(td, "state.json")
            with open(state_path, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(STATE_OBJ, fh, ensure_ascii=False)
            cmd = [sys.executable, "-m", "advisor.cli",
                   "--state", state_path] + list(extra_args)
            proc = subprocess.run(
                cmd, cwd=REPO_ROOT, env=_clean_env(),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            return proc

    def test_stdout_is_strict_utf8_with_unescaped_chinese(self):
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        # Must decode as strict UTF-8 (this fails under cp936 mojibake output).
        text = proc.stdout.decode("utf-8", errors="strict")
        data = json.loads(text)
        self.assertIn("recommendations", data)
        # ensure_ascii=False means real CJK characters survive, not \uXXXX.
        self.assertTrue(any(ord(ch) > 127 for ch in text),
                        "expected unescaped non-ASCII (Chinese) in output")
        joined = json.dumps(data, ensure_ascii=False)
        self.assertTrue(any("一" <= ch <= "鿿" for ch in joined))

    def test_out_file_is_utf8_json(self):
        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "result.json")
            proc = self._run("--out", out_path)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
            with open(out_path, "rb") as fh:
                raw = fh.read()
            # No UTF-8 BOM.
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            data = json.loads(raw.decode("utf-8", errors="strict"))
            self.assertIn("recommendations", data)


if __name__ == "__main__":
    unittest.main()
