# -*- coding: utf-8 -*-
"""Bridge to weishu-advisor: warm sidecar first, CLI fallback. No advisor imports."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from .sidecar import AdvisorSidecar


class AdvisorBridge:
    def __init__(self, kernel_path: str, kernel_python: str):
        self.kernel_path = Path(kernel_path)
        self.kernel_python = kernel_python
        self._lock = False
        self._sidecar = AdvisorSidecar(kernel_path, kernel_python)
        self._sidecar_tried = False

    @property
    def busy(self) -> bool:
        return self._lock

    def ensure_warm(self) -> bool:
        """Start sidecar in background (OCR model preload)."""
        if self._sidecar.alive:
            return True
        return self._sidecar.start(timeout=120.0)

    def shutdown(self) -> None:
        self._sidecar.stop()

    def load_mock(self, path: Path) -> dict:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)

    def recommend_state(
        self,
        state: dict,
        *,
        board: Optional[Any] = None,
        enemy_types: str = "",
        rounds_at_level: int = 0,
        timeout: float = 60.0,
    ) -> dict:
        # State path is cheap; CLI is fine. Sidecar optional.
        if self._sidecar.alive:
            payload = {"op": "state", "state": state, "rounds_at_level": rounds_at_level}
            out = self._sidecar.request(payload, timeout=timeout)
            if out.get("ok"):
                return out
        with tempfile.TemporaryDirectory(prefix="weishu-box-") as td:
            td_path = Path(td)
            state_path = td_path / "state.json"
            out_path = td_path / "out.json"
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            cmd = [
                self.kernel_python,
                "-m",
                "advisor.cli",
                "--state",
                str(state_path),
                "--out",
                str(out_path),
            ]
            if board is not None:
                board_path = td_path / "board.json"
                board_path.write_text(
                    json.dumps(board, ensure_ascii=False), encoding="utf-8"
                )
                cmd.extend(["--board", str(board_path)])
            if enemy_types:
                cmd.extend(["--enemy-types", enemy_types])
            if rounds_at_level:
                cmd.extend(["--rounds-at-level", str(rounds_at_level)])
            return self._run_cli(cmd, out_path, timeout=timeout)

    def recommend_shot(
        self,
        shot_path: str,
        *,
        round_no: int,
        gold: int,
        dispatch_level: int,
        target_bond: str = "",
        difficulty: str = "standard",
        enemy_types: str = "",
        banned_operators: Optional[list] = None,
        banned_bonds: Optional[list] = None,
        core_bonds: Optional[list] = None,
        last_gold: Optional[int] = None,
        board: Optional[Any] = None,
        board_locked: bool = False,
        board_source: str = "",
        equipment: Optional[dict] = None,
        rounds_at_level: int = 0,
        regulation_level: Optional[int] = None,
        timeout: float = 60.0,
    ) -> dict:
        shot = Path(shot_path)
        if not shot.is_file():
            raise FileNotFoundError(f"shot not found: {shot}")

        # Prefer warm sidecar (reuses RapidOCR) — big win vs ~12s cold CLI.
        if not self._sidecar.alive:
            self.ensure_warm()
        if self._sidecar.alive:
            out = self._sidecar.recommend_shot(
                str(shot),
                round_no=round_no,
                gold=gold,
                dispatch_level=dispatch_level,
                target_bond=target_bond,
                difficulty=difficulty,
                enemy_types=enemy_types,
                banned_operators=banned_operators or [],
                banned_bonds=banned_bonds or [],
                core_bonds=core_bonds or [],
                last_gold=last_gold,
                board=board,
                board_locked=board_locked,
                board_source=board_source,
                equipment=equipment,
                rounds_at_level=rounds_at_level,
                regulation_level=regulation_level,
                timeout=timeout,
            )
            if out.get("ok"):
                return out
            # fall through to CLI on sidecar error

        with tempfile.TemporaryDirectory(prefix="weishu-box-") as td:
            td_path = Path(td)
            out_path = td_path / "out.json"
            cmd = [
                self.kernel_python,
                "-m",
                "advisor.cli",
                "--shot",
                str(shot),
                "--round",
                str(round_no),
                "--gold",
                str(gold),
                "--dispatch-level",
                str(dispatch_level),
                "--difficulty",
                difficulty or "standard",
                "--out",
                str(out_path),
            ]
            if target_bond:
                cmd.extend(["--target-bond", target_bond])
            if enemy_types:
                et = enemy_types if isinstance(enemy_types, str) else ",".join(enemy_types)
                cmd.extend(["--enemy-types", et])
            if banned_operators:
                cmd.extend(["--ban-operator", ",".join(banned_operators)])
            if banned_bonds:
                cmd.extend(["--ban-bond", ",".join(banned_bonds)])
            if board is not None:
                board_path = td_path / "board.json"
                board_path.write_text(
                    json.dumps(board, ensure_ascii=False), encoding="utf-8"
                )
                cmd.extend(["--board", str(board_path)])
            if rounds_at_level:
                cmd.extend(["--rounds-at-level", str(rounds_at_level)])
            return self._run_cli(cmd, out_path, timeout=timeout)

    def parse_opening(self, shot_path: str, timeout: float = 60.0) -> dict:
        if not self._sidecar.alive:
            self.ensure_warm()
        if not self._sidecar.alive:
            return {"ok": False, "error": "sidecar not ready for opening OCR"}
        return self._sidecar.parse_opening(shot_path, timeout=timeout)

    def parse_enemy_panel(self, shot_path: str, timeout: float = 45.0) -> dict:
        if not self._sidecar.alive:
            self.ensure_warm()
        if not self._sidecar.alive:
            return {"ok": False, "error": "sidecar not ready for enemy panel OCR"}
        return self._sidecar.parse_enemy_panel(shot_path, timeout=timeout)

    def board_scan(self, shot_path: str, timeout: float = 45.0) -> dict:
        if not self._sidecar.alive:
            self.ensure_warm()
        if not self._sidecar.alive:
            return {"ok": False, "error": "sidecar not ready for board_scan"}
        return self._sidecar.board_scan(shot_path, timeout=timeout)

    def panel_ocr(self, shot_path: str, timeout: float = 45.0) -> dict:
        if not self._sidecar.alive:
            self.ensure_warm()
        if not self._sidecar.alive:
            return {"ok": False, "error": "sidecar not ready for panel_ocr"}
        return self._sidecar.panel_ocr(shot_path, timeout=timeout)

    def _run_cli(self, cmd: list[str], out_path: Path, timeout: float) -> dict:
        if self._lock:
            raise RuntimeError("advisor request already in flight (lock)")
        self._lock = True
        t0 = time.perf_counter()
        try:
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            proc = subprocess.run(
                cmd,
                cwd=str(self.kernel_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)
            warnings: list[str] = []
            if proc.stderr.strip():
                warnings.append(proc.stderr.strip()[-2000:])
            if proc.returncode != 0:
                return {
                    "ok": False,
                    "error": f"CLI exit {proc.returncode}",
                    "stderr": proc.stderr.strip()[-2000:],
                    "stdout": proc.stdout.strip()[-1000:],
                    "latency_ms": latency_ms,
                    "warnings": warnings,
                }
            if not out_path.is_file():
                return {
                    "ok": False,
                    "error": "CLI succeeded but --out file missing",
                    "latency_ms": latency_ms,
                    "warnings": warnings,
                }
            with open(out_path, encoding="utf-8-sig") as f:
                result = json.load(f)
            return {
                "ok": True,
                "result": result,
                "latency_ms": latency_ms,
                "warnings": warnings,
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": f"CLI timeout after {timeout}s",
                "latency_ms": int((time.perf_counter() - t0) * 1000),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "latency_ms": int((time.perf_counter() - t0) * 1000),
            }
        finally:
            self._lock = False
