# -*- coding: utf-8 -*-
"""Manage a warm weishu-advisor sidecar process (reuse RapidOCR)."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

WORKER = Path(__file__).resolve().parent / "sidecar_worker.py"


class AdvisorSidecar:
    def __init__(self, kernel_path: str, kernel_python: str):
        self.kernel_path = Path(kernel_path)
        self.kernel_python = kernel_python
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._ready = False

    @property
    def alive(self) -> bool:
        return bool(self._proc and self._proc.poll() is None and self._ready)

    def start(self, timeout: float = 90.0) -> bool:
        with self._lock:
            if self.alive:
                return True
            self.stop_unlocked()
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env["PYTHONUNBUFFERED"] = "1"
            try:
                self._proc = subprocess.Popen(
                    [self.kernel_python, str(WORKER)],
                    cwd=str(self.kernel_path),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    bufsize=1,
                )
            except Exception:
                self._proc = None
                return False
            # Wait for ready line
            assert self._proc.stdout is not None
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < timeout:
                line = self._proc.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("ready") or msg.get("ok"):
                    self._ready = True
                    return True
            self.stop_unlocked()
            return False

    def stop(self) -> None:
        with self._lock:
            self.stop_unlocked()

    def stop_unlocked(self) -> None:
        self._ready = False
        proc = self._proc
        self._proc = None
        if not proc:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def request(self, payload: dict, timeout: float = 60.0) -> dict:
        with self._lock:
            if not self.alive:
                if not self.start():
                    return {"ok": False, "error": "sidecar failed to start"}
            assert self._proc and self._proc.stdin and self._proc.stdout
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            try:
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
            except Exception as e:
                self.stop_unlocked()
                return {"ok": False, "error": f"sidecar write failed: {e}"}

            # Read one response line (worker is single-threaded)
            self._proc.stdout.flush()
            # Use a simple timed read via polling
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < timeout:
                if self._proc.poll() is not None:
                    err = ""
                    try:
                        err = (self._proc.stderr.read() or "")[-1000:]
                    except Exception:
                        pass
                    self.stop_unlocked()
                    return {"ok": False, "error": f"sidecar exited: {err}"}
                # readline blocks — rely on worker always answering
                try:
                    resp_line = self._proc.stdout.readline()
                except Exception as e:
                    self.stop_unlocked()
                    return {"ok": False, "error": f"sidecar read failed: {e}"}
                if not resp_line:
                    self.stop_unlocked()
                    return {"ok": False, "error": "sidecar EOF"}
                try:
                    return json.loads(resp_line)
                except json.JSONDecodeError:
                    continue
            return {"ok": False, "error": f"sidecar timeout after {timeout}s"}

    def recommend_shot(self, shot_path: str, **kwargs: Any) -> dict:
        req = {
            "op": "shot",
            "path": shot_path,
            "round": kwargs.get("round_no", 1),
            "gold": kwargs.get("gold", 0),
            "dispatch_level": kwargs.get("dispatch_level", 1),
            "target_bond": kwargs.get("target_bond") or None,
            "difficulty": kwargs.get("difficulty") or "standard",
            "enemy_types": [],
            "banned_operators": list(kwargs.get("banned_operators") or []),
            "banned_bonds": list(kwargs.get("banned_bonds") or []),
            "core_bonds": list(kwargs.get("core_bonds") or []),
            "board": kwargs.get("board") or [],
            "rounds_at_level": kwargs.get("rounds_at_level") or 0,
        }
        if kwargs.get("regulation_level") is not None:
            try:
                req["regulation_level"] = int(kwargs["regulation_level"])
            except (TypeError, ValueError):
                pass
        if kwargs.get("last_gold") is not None:
            req["last_gold"] = kwargs["last_gold"]
        if kwargs.get("enemy_types"):
            # bridge passes comma string sometimes
            et = kwargs["enemy_types"]
            req["enemy_types"] = et.split(",") if isinstance(et, str) else list(et)
        if kwargs.get("board") is not None:
            req["board"] = kwargs["board"]
        if kwargs.get("board_locked"):
            req["board_locked"] = True
            req["board_source"] = kwargs.get("board_source") or "click_panel"
        if kwargs.get("equipment"):
            req["equipment"] = kwargs["equipment"]
        return self.request(req, timeout=float(kwargs.get("timeout") or 60))

    def recommend_lineups_only(self, payload: dict, timeout: float = 30.0) -> dict:
        req = {"op": "lineups", **(payload or {})}
        return self.request(req, timeout=timeout)

    def parse_opening(self, shot_path: str, timeout: float = 60.0) -> dict:
        return self.request(
            {"op": "opening", "path": shot_path},
            timeout=timeout,
        )

    def parse_enemy_panel(self, shot_path: str, timeout: float = 45.0) -> dict:
        return self.request(
            {"op": "enemy_panel", "path": shot_path},
            timeout=timeout,
        )

    def board_scan(self, shot_path: str, timeout: float = 45.0) -> dict:
        return self.request(
            {"op": "board_scan", "path": shot_path},
            timeout=timeout,
        )

    def panel_ocr(self, shot_path: str, timeout: float = 45.0) -> dict:
        return self.request(
            {"op": "panel_ocr", "path": shot_path},
            timeout=timeout,
        )
