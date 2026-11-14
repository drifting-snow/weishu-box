# -*- coding: utf-8 -*-
"""Seed session/run_env.json from NVIDIA Arknights opening shots (debug)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shell import run_env as rem  # noqa: E402


def main() -> int:
    from PIL import Image

    worker = ROOT / "shell" / "sidecar_worker.py"
    kernel = Path(os.environ.get("WEISHU_KERNEL_PATH", str(ROOT.parent / "advisor")))
    base = Path(os.environ.get("WEISHU_SHOTS_DIR", "shots"))
    shots = [
        ("contract", base / "单人-合约选择界面.png"),
        ("strategy", base / "单人-策略选择.png"),
        ("draft", base / "单人-自选选择.png"),
    ]
    py = kernel / ".venv" / "Scripts" / "python.exe"
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    p = subprocess.Popen(
        [str(py), str(worker)],
        cwd=str(kernel),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
        bufsize=1,
    )
    assert p.stdout and p.stdin
    print("ready", p.stdout.readline().strip())
    merged = rem.empty_run_env()
    rem.ensure_session_dir()
    for phase, spath in shots:
        dest = rem.SESSION_DIR / f"opening_{phase}.jpg"
        Image.open(spath).convert("RGB").save(dest, quality=90)
        if phase == "contract":
            Image.open(spath).convert("RGB").save(rem.LAST_SHOT_PATH, quality=90)
        p.stdin.write(
            json.dumps({"op": "opening", "path": str(spath)}, ensure_ascii=False) + "\n"
        )
        p.stdin.flush()
        d = json.loads(p.stdout.readline())
        if not d.get("ok"):
            print("FAIL", phase, d)
            continue
        parsed = d["result"]
        parsed["shot_path"] = str(dest)
        merged = rem.merge_phase(merged, parsed)
        print(
            "merged",
            phase,
            "enemies",
            merged.get("enemy_types"),
            "bans",
            merged.get("banned_operators"),
            "strat",
            merged.get("strategy_raw"),
        )
    path = rem.save_run_env(merged)
    print("SAVED", path)
    print("\n".join(rem.summary_lines(merged)))
    try:
        p.stdin.close()
        p.kill()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
