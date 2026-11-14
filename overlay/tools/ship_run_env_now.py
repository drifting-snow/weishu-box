# -*- coding: utf-8 -*-
"""Minimal ship check: OCR 1/3 ref → session/run_env.json."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image
from shell import run_env as rem


REF = Path(os.environ.get("WEISHU_REF_SHOT", "shots/contract_1_3_ref.png"))
KERNEL = Path(os.environ.get("WEISHU_KERNEL_PATH", str(ROOT.parent / "advisor")))
WORKER = ROOT / "shell" / "sidecar_worker.py"


def main() -> int:
    py = KERNEL / ".venv" / "Scripts" / "python.exe"
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    p = subprocess.Popen(
        [str(py), str(WORKER)],
        cwd=str(KERNEL),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
        bufsize=1,
    )
    assert p.stdout and p.stdin
    print(p.stdout.readline().strip())
    rem.ensure_session_dir()
    Image.open(REF).convert("RGB").save(rem.LAST_SHOT_PATH, quality=90)
    p.stdin.write(json.dumps({"op": "opening", "path": str(REF)}, ensure_ascii=False) + "\n")
    p.stdin.flush()
    d = json.loads(p.stdout.readline())
    if not d.get("ok"):
        print("FAIL", d)
        return 1
    parsed = d["result"]
    parsed["shot_path"] = str(rem.LAST_SHOT_PATH)
    merged = rem.merge_phase(rem.empty_run_env(), parsed)
    path = rem.save_run_env(merged)
    print("SAVED", path)
    for line in rem.summary_lines(merged):
        print(line)
    try:
        p.stdin.close()
        p.kill()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
