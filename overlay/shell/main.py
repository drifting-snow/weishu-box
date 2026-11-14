# -*- coding: utf-8 -*-
"""Overlay shell: small panel only on launch. Read-only; no auto-click.

Glow frames use a Win32 color-key layered window (lazy), NOT a second
WebView2 — fullscreen WebView2 transparent often paints opaque white.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
import threading
import time
from pathlib import Path

import webview

from .advisor_bridge import AdvisorBridge
from .capture_live import grab_primary, grab_primary_to_temp
from .config import ROOT, load_config
from .glow_overlay import GlowOverlay
from .advice_filter import filter_advice
from .shop_layout import resolve_highlight, resolve_lineup_highlight
from . import run_env as run_env_mod
from . import op_log as op_log_mod
from . import win32_util as w32

WINDOW_TITLE = "卫戍盒子 · 参谋"
ROSTER_TITLE = "卫戍盒子 · 阵容"
UI_DIR = Path(__file__).resolve().parent / "ui"
MOCK_PATH = ROOT / "mock" / "recommend_demo.json"

_analyze_lock = threading.Lock()


def _primary_screen_size() -> tuple[int, int]:
    user32 = ctypes.windll.user32
    return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))


def _soften_process_priority() -> None:
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x00004000)
    except Exception:
        pass


def _enable_dpi_awareness() -> None:
    """Per-monitor v2 so 2560×1440 fractions map to physical pixels."""
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class Api:
    def __init__(self, cfg: dict, bridge: AdvisorBridge, holder: dict, glow: GlowOverlay):
        self.cfg = cfg
        self.bridge = bridge
        self._holder = holder
        self._glow = glow
        self._hwnd: int | None = None
        self._visible = True
        self._interact = True
        self._alpha = int(float(cfg.get("opacity", 0.88)) * 255)
        self._last_frames: list[dict] = []
        self._chrome_stop = threading.Event()
        self._chrome_thread: threading.Thread | None = None
        self._last_gold: int | None = None
        self._last_board: list = []
        self._last_equipment: dict = {}
        self._board_source: str | None = None
        self._last_shop: list = []
        self._last_dispatch: int = 1
        self._last_capture_w: int | None = None
        self._lineup_sel: dict = {"id": None, "stage": "mid", "names": []}
        # Restore 「读阵容」cache across panel restarts (not cold auto-OCR).
        try:
            cached = run_env_mod.load_board_cache()
            if cached.get("board") and cached.get("source") == "click_panel":
                self._last_board = list(cached.get("board") or [])
                self._last_equipment = dict(cached.get("equipment") or {})
                self._board_source = "click_panel"
        except Exception:
            pass
        # Auto OCR: never armed on cold launch (freeze pref).
        self._auto_armed = False
        self._auto_stop = threading.Event()
        self._auto_thread: threading.Thread | None = None
        self._auto_meta: dict = dict(cfg.get("defaults") or {})
        self._auto_last_shop_fp: str | None = None
        self._auto_fail_streak = 0
        self._auto_skip_reason: str | None = None
        self._auto_cycles = 0

    def _panel(self):
        return self._holder.get("panel")

    def _roster(self):
        return self._holder.get("roster")

    def get_defaults(self) -> dict:
        d = dict(self.cfg.get("defaults") or {})
        env = run_env_mod.load_run_env()
        if env.get("target_bond") and not d.get("target_bond"):
            d["target_bond"] = env["target_bond"]
        d["run_env_path"] = str(run_env_mod.RUN_ENV_PATH)
        d["run_env_summary"] = run_env_mod.summary_lines(env)
        paths = op_log_mod.match_paths()
        d["op_log_match_id"] = paths.get("match_id")
        d["op_log_dir"] = paths.get("dir")
        return d

    def get_op_log(self) -> dict:
        paths = op_log_mod.match_paths()
        return {
            "ok": True,
            **paths,
            "active": op_log_mod.is_accepting(),
        }

    def _reset_match_ocr_state(self) -> None:
        """Clear in-match OCR caches so the new folder starts clean."""
        try:
            self.clear_highlight()
        except Exception:
            pass
        self._last_frames = []
        self._last_gold = None
        self._last_board = []
        self._last_equipment = {}
        self._board_source = None
        self._last_shop = []
        self._last_dispatch = 1
        self._last_capture_w = None
        self._auto_last_shop_fp = None
        self._auto_fail_streak = 0
        try:
            run_env_mod.clear_board_cache()
        except Exception:
            pass
        # Keep _auto_armed: auto loop continues into the new match folder.

    def begin_match(self, note: str | None = None, meta: dict | None = None) -> dict:
        """「开始新一局」: seal previous log → new folder → reset → OCR into new log."""
        prev = op_log_mod.current_match_id()
        try:
            if prev:
                op_log_mod.end_match(note="closed by begin_match")
        except Exception:
            pass
        self._reset_match_ocr_state()
        info = op_log_mod.start_match(note=note or "user begin match")
        # Kick OCR on a worker so the first events.jsonl lines land in *this* folder.
        meta_live = dict(meta) if isinstance(meta, dict) else {}
        if not meta_live:
            try:
                meta_live = self._read_form_meta()
            except Exception:
                meta_live = dict(self.cfg.get("defaults") or {})
        armed = bool(self._auto_armed)

        def work():
            try:
                self._run_live_cycle_and_push(meta_live, source="manual")
            except Exception as e:
                err = json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
                self._push_panel_js(
                    f"window.__weishu_render && window.__weishu_render({err})"
                )

        threading.Thread(target=work, name="weishu-begin-match", daemon=True).start()
        return {
            "ok": True,
            **info,
            "prev_match_id": prev,
            "ocr_started": True,
            "auto_armed": armed,
        }

    def end_current_match(self, note: str | None = None) -> dict:
        """「结束一局」: write ended_at; stop appends; keep folder."""
        out = op_log_mod.end_match(note=note or "user end match")
        try:
            self.clear_highlight()
        except Exception:
            pass
        if not out.get("ok"):
            return out
        return {**out, "active": False, "idle": True}

    def read_lineup_panel(self, meta: dict | None = None) -> dict:
        """「读阵容」: badge → read-only click → panel/equip OCR → ESC.

        Explicit button only — never armed into shop auto shot / cold launch.
        """
        meta = meta or {}
        try:
            if self._holder.get("roster_collapsed"):
                self.toggle_roster_collapsed()
        except Exception:
            pass
        if not _analyze_lock.acquire(blocking=False):
            return {"ok": False, "error": "分析进行中，请稍候"}
        t0 = time.perf_counter()
        warnings: list[str] = []
        tmp_scan: Path | None = None
        try:
            if not self.bridge.ensure_warm():
                return {"ok": False, "error": "sidecar not ready"}
            self.clear_highlight()

            # 1) Focus game, ESC to ordinary (unselected) state, scan badges.
            focus = w32.focus_game_for_input()
            try:
                w32.tap_escape()
                time.sleep(0.2)
            except Exception:
                pass
            try:
                self._reassert_topmost()
            except Exception:
                pass

            tmp_scan = grab_primary_to_temp(prefix="weishu-board-scan-")
            scan_out = self.bridge.board_scan(str(tmp_scan), timeout=60.0)
            if not scan_out.get("ok"):
                return {
                    "ok": False,
                    "error": scan_out.get("error") or "board_scan failed",
                    "focus": focus,
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                }
            scan = scan_out.get("result") if isinstance(scan_out.get("result"), dict) else {}
            badges = list(scan.get("badges") or [])
            cap = scan.get("capture") if isinstance(scan.get("capture"), dict) else {}
            width = int(cap.get("width") or 0)
            height = int(cap.get("height") or 0)
            if width <= 0 or height <= 0:
                try:
                    from PIL import Image as _Image

                    with _Image.open(tmp_scan) as im:
                        width, height = im.size
                except Exception:
                    width, height = _primary_screen_size()

            from .panel_unit_ocr import click_in_allowed_roi, click_point_from_badge

            max_n = int(meta.get("max_units") or 12)
            units: list[dict] = []
            equipment: dict[str, list[str]] = {}
            per_badge: list[dict] = []
            gold_before = self._last_gold

            for i, b in enumerate(badges[:max_n]):
                cx = int(b.get("cx") or 0)
                cy = int(b.get("cy") or 0)
                px, py = click_point_from_badge(cx, cy, width, height)
                row = {
                    "badge": b,
                    "click": {"x": px, "y": py},
                    "name": None,
                    "equipment": [],
                    "ok": False,
                }
                if not click_in_allowed_roi(px, py, width, height):
                    row["error"] = "click outside board/bench ROI"
                    warnings.append(f"badge#{i} click rejected (ROI)")
                    per_badge.append(row)
                    continue

                focus2 = w32.focus_game_for_input()
                click = w32.left_click(
                    px,
                    py,
                    allowed=lambda x, y, w=width, h=height: click_in_allowed_roi(
                        x, y, w, h
                    ),
                )
                if not click.get("ok"):
                    row["error"] = click.get("error") or "left_click failed"
                    warnings.append(f"badge#{i} click failed")
                    per_badge.append(row)
                    continue
                time.sleep(0.25)
                try:
                    self._reassert_topmost()
                except Exception:
                    pass

                tmp_panel = grab_primary_to_temp(prefix="weishu-panel-")
                try:
                    p_out = self.bridge.panel_ocr(str(tmp_panel), timeout=45.0)
                finally:
                    try:
                        tmp_panel.unlink(missing_ok=True)
                    except Exception:
                        pass

                panel = {}
                if p_out.get("ok") and isinstance(p_out.get("result"), dict):
                    panel = p_out["result"]
                name = panel.get("name")
                eq = [str(x) for x in (panel.get("equipment") or []) if x]
                row["panel"] = {
                    "panel_open": bool(panel.get("panel_open")),
                    "raw": panel.get("raw"),
                    "tier_hint": panel.get("tier_hint"),
                }
                row["focus"] = focus2
                if name:
                    row["name"] = name
                    row["equipment"] = eq
                    row["ok"] = True
                    units.append(
                        {
                            "name": name,
                            "count": 1,
                            "elite": bool(panel.get("elite")),
                            "tier": panel.get("tier_hint"),
                        }
                    )
                    if eq:
                        equipment[name] = eq
                else:
                    warnings.append(f"badge#{i} panel name OCR miss")
                per_badge.append(row)

                # ESC back to ordinary state before next badge.
                w32.focus_game_for_input()
                w32.tap_escape()
                time.sleep(0.18)
                try:
                    self._reassert_topmost()
                except Exception:
                    pass

            # Soft gold audit (read-only clicks should not spend).
            if gold_before is not None and self._last_gold is not None:
                if int(self._last_gold) != int(gold_before):
                    warnings.append(
                        f"gold changed {gold_before}→{self._last_gold} during 读阵容"
                    )

            # Merge same-name counts for board_io shape.
            merged: dict[str, dict] = {}
            order: list[str] = []
            for u in units:
                n = u["name"]
                if n not in merged:
                    order.append(n)
                    merged[n] = {
                        "name": n,
                        "count": 0,
                        "elite": False,
                        "tier": None,
                    }
                merged[n]["count"] += int(u.get("count") or 1)
                merged[n]["elite"] = merged[n]["elite"] or bool(u.get("elite"))
                if u.get("tier") is not None:
                    merged[n]["tier"] = u.get("tier")
            board = [merged[n] for n in order]

            self._last_board = board
            self._last_equipment = dict(equipment)
            self._board_source = "click_panel" if board else self._board_source
            cache_path = None
            try:
                cache_path = str(
                    run_env_mod.save_board_cache(
                        board,
                        equipment,
                        source="click_panel",
                        warnings=warnings,
                        badge_count=len(badges),
                        named_count=len(board),
                    )
                )
            except Exception as ce:
                warnings.append(f"board_cache save failed: {ce}")

            # Refresh lineup companion with new board (+ equipment via state path).
            try:
                payload = {
                    "board": board,
                    "equipment": equipment,
                    "round": int(meta.get("round") or 1),
                    "gold": int(self._last_gold or meta.get("gold") or 0),
                    "dispatch_level": int(
                        meta.get("dispatch_level") or self._last_dispatch or 1
                    ),
                }
                env_kw = self._shot_kwargs_from_run_env(meta)
                for k in (
                    "target_bond",
                    "difficulty",
                    "enemy_types",
                    "banned_operators",
                    "banned_bonds",
                    "core_bonds",
                ):
                    if env_kw.get(k) is not None:
                        payload[k] = env_kw[k]
                # Sidecar lineups op ignores equipment today; still push board.
                out_lin = self.bridge._sidecar.recommend_lineups_only(payload)
                if out_lin.get("ok"):
                    res = out_lin.get("result") if isinstance(out_lin.get("result"), dict) else {}
                    if isinstance(res, dict):
                        res["board"] = board
                        res["equipment"] = equipment
                        res["board_source"] = "click_panel"
                        out_lin["result"] = res
                    self.push_roster(out_lin)
            except Exception as le:
                warnings.append(f"lineup refresh: {le}")

            try:
                op_log_mod.append_advise_event(
                    {
                        "ok": True,
                        "result": {
                            "board": board,
                            "equipment": equipment,
                            "board_source": "click_panel",
                            "board_warnings": warnings,
                        },
                        "latency_ms": int((time.perf_counter() - t0) * 1000),
                    },
                    trigger="read_lineup",
                )
            except Exception:
                pass

            named = len(board)
            msg = (
                f"读阵容完成 · 标记 {len(badges)} · 点名 {named}"
                + (f" · 装备 {sum(len(v) for v in equipment.values())} 件" if equipment else "")
            )
            if not badges:
                msg = "读阵容：未检测到头顶标记（请确认普通未选中准备界面）"
                warnings.append("no badges")
            return {
                "ok": True,
                "pending_screenshots": False,
                "board": board,
                "equipment": equipment,
                "board_source": "click_panel",
                "badge_count": len(badges),
                "named_count": named,
                "per_badge": per_badge,
                "warnings": warnings,
                "focus": focus,
                "cache_path": cache_path,
                "message": msg,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "equip_ocr": "wired",
                "board_badge_click": "wired",
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            if tmp_scan is not None:
                try:
                    tmp_scan.unlink(missing_ok=True)
                except Exception:
                    pass
            try:
                self._reassert_topmost()
            except Exception:
                pass
            _analyze_lock.release()

    def new_match(self, note: str | None = None, meta: dict | None = None) -> dict:
        """Alias → begin_match (旧「新一局」)."""
        return self.begin_match(note=note, meta=meta)

    def get_run_env(self) -> dict:
        env = run_env_mod.load_run_env()
        return {
            "ok": True,
            "path": str(run_env_mod.RUN_ENV_PATH),
            "env": env,
            "summary": run_env_mod.summary_lines(env),
        }

    def _shot_kwargs_from_run_env(self, meta: dict) -> dict:
        """Merge session/run_env.json into recommend_shot kwargs."""
        patch = run_env_mod.gamestate_patch()
        env = run_env_mod.load_run_env()
        # Form / meta overrides empty env; env fills scoring fields.
        target = (meta.get("target_bond") or "").strip() or patch.get("target_bond") or ""
        difficulty = meta.get("difficulty") or patch.get("difficulty") or "standard"
        enemy_types = patch.get("enemy_types") or []
        if isinstance(enemy_types, list):
            enemy_types = ",".join(enemy_types)
        kw = {
            "target_bond": target,
            "difficulty": difficulty,
            "enemy_types": enemy_types,
            "banned_operators": list(patch.get("banned_operators") or []),
            "banned_bonds": list(patch.get("banned_bonds") or []),
            "core_bonds": list(env.get("core_bonds") or []),
        }
        if patch.get("regulation_level") is not None:
            kw["regulation_level"] = int(patch["regulation_level"])
        elif env.get("procedure_level") is not None:
            try:
                kw["regulation_level"] = int(env["procedure_level"])
            except (TypeError, ValueError):
                pass
        if self._last_gold is not None:
            kw["last_gold"] = self._last_gold
        # 「读阵容」cache is authoritative until user starts a new match.
        if self._board_source == "click_panel" and self._last_board:
            kw["board"] = list(self._last_board)
            kw["board_locked"] = True
            kw["board_source"] = "click_panel"
            if self._last_equipment:
                kw["equipment"] = dict(self._last_equipment)
        return kw

    def _remember_gold_from_result(self, data: dict) -> None:
        res = data.get("resources") if isinstance(data.get("resources"), dict) else {}
        st = data.get("state") if isinstance(data.get("state"), dict) else {}
        status = str(res.get("gold_status") or "")
        if status == "ocr" and res.get("gold") is not None:
            try:
                self._last_gold = int(res["gold"])
            except (TypeError, ValueError):
                pass
        elif status == "last_good" and res.get("gold") is not None:
            try:
                self._last_gold = int(res["gold"])
            except (TypeError, ValueError):
                pass
        board = data.get("board") or st.get("board") or []
        src = data.get("board_source") or st.get("board_source")
        if isinstance(board, list) and board:
            # Do not let strip OCR clobber a locked click-panel cache.
            if self._board_source == "click_panel" and src != "click_panel":
                pass
            else:
                self._last_board = board
                if src:
                    self._board_source = str(src)
        eq = data.get("equipment")
        if eq is None and isinstance(st, dict):
            eq = st.get("equipment")
        if isinstance(eq, dict) and eq:
            self._last_equipment = dict(eq)
        shop = data.get("shop") or st.get("shop") or []
        if isinstance(shop, list) and shop:
            self._last_shop = shop
        cap = data.get("capture") if isinstance(data.get("capture"), dict) else {}
        if cap.get("width"):
            try:
                self._last_capture_w = int(cap["width"])
            except (TypeError, ValueError):
                pass
        elif isinstance(shop, list):
            # Fallback: first card raw.image_width from this OCR frame.
            for c in shop:
                raw = c.get("raw") if isinstance(c, dict) else None
                if isinstance(raw, dict) and raw.get("image_width"):
                    try:
                        self._last_capture_w = int(raw["image_width"])
                        break
                    except (TypeError, ValueError):
                        pass
        if st.get("dispatch_level") is not None:
            try:
                self._last_dispatch = int(st["dispatch_level"])
            except (TypeError, ValueError):
                pass
        elif res.get("dispatch_level") is not None:
            try:
                self._last_dispatch = int(res["dispatch_level"])
            except (TypeError, ValueError):
                pass

    def _capture_width_from_result(self, data: dict | None = None) -> int | None:
        if isinstance(data, dict):
            cap = data.get("capture") if isinstance(data.get("capture"), dict) else {}
            if cap.get("width"):
                try:
                    return int(cap["width"])
                except (TypeError, ValueError):
                    pass
            shop = data.get("shop") or (data.get("state") or {}).get("shop") or []
            for c in shop if isinstance(shop, list) else []:
                raw = c.get("raw") if isinstance(c, dict) else None
                if isinstance(raw, dict) and raw.get("image_width"):
                    try:
                        return int(raw["image_width"])
                    except (TypeError, ValueError):
                        pass
        return self._last_capture_w

    def capture_run_env(self, meta: dict | None = None) -> dict:
        """Grab primary screen → opening OCR → persist session/run_env.json."""
        meta = meta or {}
        if not _analyze_lock.acquire(blocking=False):
            return {"ok": False, "error": "分析进行中，请稍候"}
        shot_persist: Path | None = None
        t0 = time.perf_counter()
        try:
            run_env_mod.ensure_session_dir()
            # Persist debug JPEG always (overwrite last_opening.jpg)
            img = grab_primary()
            shot_persist = run_env_mod.LAST_SHOT_PATH
            img.save(shot_persist, format="JPEG", quality=90, optimize=True)
            ocr_path = str(shot_persist)

            out = self.bridge.parse_opening(ocr_path, timeout=90.0)
            if not out.get("ok"):
                return {
                    "ok": False,
                    "error": out.get("error") or "opening OCR failed",
                    "path": str(run_env_mod.RUN_ENV_PATH),
                    "shot": str(shot_persist),
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                }
            parsed = out.get("result") or {}
            if not isinstance(parsed, dict):
                parsed = {}
            parsed["shot_path"] = str(shot_persist)
            prev = run_env_mod.load_run_env()
            merged = run_env_mod.merge_phase(prev, parsed)
            path = run_env_mod.save_run_env(merged)
            summary = run_env_mod.summary_lines(merged)
            result = {
                "ok": True,
                "path": str(path),
                "shot": str(shot_persist),
                "env": merged,
                "summary": summary,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "sidecar_ms": out.get("latency_ms"),
            }
            self.push_run_env(result)
            # Refresh lineup comps with new enemy/bond picture
            try:
                self.refresh_lineups({})
            except Exception:
                pass
            return result
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "path": str(run_env_mod.RUN_ENV_PATH),
                "latency_ms": int((time.perf_counter() - t0) * 1000),
            }
        finally:
            _analyze_lock.release()

    def push_roster(self, envelope: dict | None = None) -> bool:
        """Update companion roster window (board + target comps)."""
        win = self._roster()
        if not win:
            return False
        try:
            payload = json.dumps(envelope if envelope is not None else {}, ensure_ascii=False)
            win.evaluate_js(
                f"window.__weishu_roster_render && window.__weishu_roster_render({payload})"
            )
            return True
        except Exception:
            return False

    def toggle_roster_visible(self) -> bool:
        """Compat: collapse/expand roster (never destroy/hide the window)."""
        return self.toggle_roster_collapsed()

    def toggle_roster_collapsed(self) -> bool:
        """Shrink roster to title bar / restore — window stays alive."""
        win = self._roster()
        if not win:
            return False
        collapsed = not bool(self._holder.get("roster_collapsed", False))
        self._holder["roster_collapsed"] = collapsed
        win_cfg = self.cfg.get("window") or {}
        full_h = int(
            self._holder.get("roster_full_h")
            or win_cfg.get("roster_height")
            or 720
        )
        self._holder["roster_full_h"] = full_h
        width = int(win_cfg.get("roster_width") or 420)
        try:
            win.evaluate_js(
                "window.__roster_set_collapsed && window.__roster_set_collapsed(%s)"
                % ("true" if collapsed else "false")
            )
        except Exception:
            pass
        try:
            # Keep a thin bar so user can click 「展」 again — never win.hide().
            win.resize(width, 48 if collapsed else full_h)
        except Exception:
            pass
        self._reassert_topmost()
        self._holder["roster_visible"] = True
        return collapsed

    def push_run_env(self, payload: dict | None = None) -> bool:
        """Show 本局环境 on the companion roster window."""
        win = self._roster()
        if not win:
            return False
        try:
            data = payload
            if data is None:
                env = run_env_mod.load_run_env()
                data = {
                    "ok": True,
                    "path": str(run_env_mod.RUN_ENV_PATH),
                    "env": env,
                    "summary": run_env_mod.summary_lines(env),
                }
            blob = json.dumps(data, ensure_ascii=False)
            win.evaluate_js(
                f"window.__weishu_run_env_render && window.__weishu_run_env_render({blob})"
            )
            return True
        except Exception:
            return False

    def load_mock(self) -> dict:
        try:
            data = self._sanitize_result(self.bridge.load_mock(MOCK_PATH))
            self.apply_highlight_from_result(data)
            out = {"ok": True, "result": data, "latency_ms": 0}
            self.push_roster(out)
            return out
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def analyze_state(self, meta: dict) -> dict:
        if not _analyze_lock.acquire(blocking=False):
            return {"ok": False, "error": "分析进行中，请稍候"}
        try:
            state = {
                "round": int(meta.get("round") or 1),
                "gold": int(meta.get("gold") or 0),
                "dispatch_level": int(meta.get("dispatch_level") or 1),
                "difficulty": meta.get("difficulty") or "standard",
                "shop": meta.get("shop")
                or [
                    {"kind": "operator", "name": "烈夏", "tier": 1, "price": 3},
                    {"kind": "operator", "name": "真理", "tier": 2, "price": 3},
                    {"kind": "item", "name": "坚守盾牌", "tier": 1, "price": 1},
                    {"kind": "operator", "name": "塔露拉", "tier": 6, "price": 3},
                ],
                "board": meta.get("board")
                or [
                    {"name": "烈夏", "count": 2, "tier": 1, "bonds": ["乌萨斯"]},
                    {"name": "折桠", "count": 1, "tier": 1, "bonds": ["乌萨斯", "不屈"]},
                ],
            }
            env_kw = self._shot_kwargs_from_run_env(meta)
            if env_kw.get("target_bond"):
                state["target_bond"] = env_kw["target_bond"]
            elif meta.get("target_bond"):
                state["target_bond"] = meta["target_bond"]
            if env_kw.get("difficulty"):
                state["difficulty"] = env_kw["difficulty"]
            if env_kw.get("enemy_types"):
                et = env_kw["enemy_types"]
                state["enemy_types"] = (
                    et.split(",") if isinstance(et, str) else list(et)
                )
            if env_kw.get("banned_operators"):
                state["banned_operators"] = list(env_kw["banned_operators"])
            if env_kw.get("banned_bonds"):
                state["banned_bonds"] = list(env_kw["banned_bonds"])
            if env_kw.get("regulation_level") is not None:
                try:
                    state["regulation_level"] = int(env_kw["regulation_level"])
                except (TypeError, ValueError):
                    pass
            out = self.bridge.recommend_state(state)
            if out.get("ok") and isinstance(out.get("result"), dict):
                st = out["result"].setdefault("state", {})
                if isinstance(st, dict) and "shop" not in st:
                    st["shop"] = state.get("shop") or []
                out["result"] = self._sanitize_result(out["result"])
                self.apply_highlight_from_result(out["result"])
            return out
        finally:
            _analyze_lock.release()

    def clear_highlight(self) -> bool:
        """Hide glow immediately (OCR start). Next apply/set_frames must show again."""
        self._last_frames = []
        self._glow.clear()
        return True

    # --- Auto OCR loop (default off until 「自动」or first manual success) ---

    def get_auto_ocr(self) -> dict:
        return {
            "armed": bool(self._auto_armed),
            "cycles": int(self._auto_cycles),
            "fail_streak": int(self._auto_fail_streak),
            "skip_reason": self._auto_skip_reason,
            "interval_sec": float(self.cfg.get("auto_ocr_interval_sec") or 4.5),
            "gap_sec": float(self.cfg.get("auto_ocr_gap_sec") or 0.5),
        }

    def set_auto_ocr(self, enabled: bool, meta: dict | None = None) -> dict:
        """Arm/disarm auto loop. Never auto-arms on cold launch."""
        if meta and isinstance(meta, dict):
            self._auto_meta = dict(meta)
        want = bool(enabled)
        if want and not self._auto_armed:
            self._auto_armed = True
            self._auto_fail_streak = 0
            self._auto_skip_reason = None
            self._start_auto_thread()
        elif not want and self._auto_armed:
            self._auto_armed = False
            self._auto_stop.set()
        return self.get_auto_ocr()

    def note_manual_ocr_done(self, ok: bool, meta: dict | None = None) -> dict:
        """After a successful manual OCR, stay in auto (user pref)."""
        if meta and isinstance(meta, dict):
            self._auto_meta = dict(meta)
        if ok and not self._auto_armed:
            return self.set_auto_ocr(True, meta)
        return self.get_auto_ocr()

    def _start_auto_thread(self) -> None:
        if self._auto_thread and self._auto_thread.is_alive():
            self._auto_stop.clear()
            return
        self._auto_stop.clear()
        self._auto_thread = threading.Thread(
            target=self._auto_ocr_loop, name="weishu-auto-ocr", daemon=True
        )
        self._auto_thread.start()

    def _shop_fingerprint(self, result: dict | None) -> str:
        if not isinstance(result, dict):
            return ""
        shop = result.get("shop")
        st = result.get("state") if isinstance(result.get("state"), dict) else {}
        if not isinstance(shop, list):
            shop = st.get("shop") or []
        names = []
        for c in shop or []:
            if isinstance(c, dict) and c.get("name"):
                names.append(str(c["name"]))
        return "|".join(names)

    def _looks_like_prep(self) -> tuple[bool, str]:
        """Heuristic: Arknights window up, or last cycle saw shop/gold OCR."""
        if w32.find_game_hwnd():
            return True, "game_window"
        if self._last_shop:
            return True, "last_shop"
        if self._last_gold is not None:
            return True, "last_gold"
        # Soft allow while armed — first cycle discovers prep; skip only if
        # we already failed with empty shop several times.
        if self._auto_fail_streak < 2:
            return True, "probe"
        return False, "no_game_no_shop"

    def _push_panel_js(self, expr: str) -> None:
        win = self._panel()
        if not win:
            return
        try:
            win.evaluate_js(expr)
        except Exception:
            pass

    def _read_form_meta(self) -> dict:
        win = self._panel()
        meta = dict(self._auto_meta or self.cfg.get("defaults") or {})
        if not win:
            return meta
        try:
            live = win.evaluate_js(
                """({
                  round: Number(document.getElementById('round').value)||1,
                  gold: Number(document.getElementById('gold').value)||0,
                  dispatch_level: Number(document.getElementById('dispatch').value)||1,
                  target_bond: (document.getElementById('bond').value||'').trim(),
                  difficulty: 'standard'
                })"""
            )
            if isinstance(live, dict):
                meta = live
                self._auto_meta = dict(live)
        except Exception:
            pass
        return meta

    def _run_live_cycle_and_push(self, meta: dict, *, source: str = "auto") -> dict:
        """One capture→advise→glow cycle; drives Moji via panel JS."""
        self._push_panel_js(
            "window.__weishu_moji && window.__weishu_moji.thinking()"
        )
        trig = "auto" if source == "auto" else ("manual" if source in ("hotkey", "manual") else str(source))
        result = self.analyze_live(meta or {}, trigger=trig)
        try:
            payload = json.dumps(result, ensure_ascii=False)
        except Exception:
            payload = json.dumps({"ok": False, "error": "serialize failed"})
        self._push_panel_js(
            f"window.__weishu_render && window.__weishu_render({payload})"
        )
        if isinstance(result, dict) and result.get("ok"):
            try:
                self.push_roster(result)
            except Exception:
                pass
            fp = self._shop_fingerprint(result.get("result") if isinstance(result.get("result"), dict) else result)
            if fp and self._auto_last_shop_fp and fp != self._auto_last_shop_fp:
                # Shop changed (refresh/buy) — note for sooner next tick.
                result = dict(result)
                result["shop_changed"] = True
            if fp:
                self._auto_last_shop_fp = fp
        result = dict(result) if isinstance(result, dict) else {"ok": False}
        result["auto_source"] = source
        return result

    def _auto_ocr_loop(self) -> None:
        gap = float(self.cfg.get("auto_ocr_gap_sec") or 0.5)
        base_iv = float(self.cfg.get("auto_ocr_interval_sec") or 4.5)
        backoff = float(self.cfg.get("auto_ocr_backoff_sec") or 8.0)
        # Brief settle so a manual OCR that just armed us isn't doubled.
        self._auto_stop.wait(max(gap, 1.0))
        while not self._auto_stop.is_set():
            if not self._auto_armed:
                break
            # Never overlap: analyze_live uses non-blocking lock.
            if _analyze_lock.locked():
                self._auto_skip_reason = "busy"
                self._auto_stop.wait(0.35)
                continue
            ok_prep, why = self._looks_like_prep()
            if not ok_prep:
                self._auto_skip_reason = why
                self._auto_stop.wait(min(backoff, 5.0))
                continue
            self._auto_skip_reason = None
            meta = self._read_form_meta()
            t0 = time.perf_counter()
            out = self._run_live_cycle_and_push(meta, source="auto")
            elapsed = time.perf_counter() - t0
            self._auto_cycles += 1
            shop_changed = bool(out.get("shop_changed"))
            if out.get("ok"):
                self._auto_fail_streak = 0
                # After cycle ends + gap; shop change → slightly sooner next.
                wait = max(gap, base_iv - elapsed)
                if shop_changed:
                    wait = max(gap, min(wait, 1.2))
            else:
                self._auto_fail_streak += 1
                wait = max(gap, backoff if self._auto_fail_streak >= 2 else base_iv)
            # Sleep in slices so disarm is snappy.
            end = time.perf_counter() + wait
            while time.perf_counter() < end:
                if self._auto_stop.is_set() or not self._auto_armed:
                    break
                self._auto_stop.wait(0.2)
        self._auto_thread = None

    def analyze_live(self, meta: dict, trigger: str = "manual") -> dict:
        """Primary UX: grab primary screen → CLI --shot (kernel ResourceRecognizer
        fills round/gold/level when possible; form values are fallbacks only).
        """
        meta = meta or {}
        trig = str(meta.get("_trigger") or trigger or "manual")
        if not _analyze_lock.acquire(blocking=False):
            out_busy = {"ok": False, "error": "分析进行中，请稍候"}
            op_log_mod.append_advise_event(out_busy, trigger=trig)
            return out_busy
        # Drop old glow the moment a new OCR starts — only reappear after result.
        self.clear_highlight()
        tmp: Path | None = None
        shell_timing: dict = {}
        t_shell = time.perf_counter()
        out: dict = {"ok": False, "error": "unknown"}
        try:
            t_cap = time.perf_counter()
            tmp = grab_primary_to_temp()
            shell_timing["capture_ms"] = int((time.perf_counter() - t_cap) * 1000)
            env_kw = self._shot_kwargs_from_run_env(meta)
            t_side = time.perf_counter()
            out = self.bridge.recommend_shot(
                str(tmp),
                # Fallbacks only when ResourceRecognizer returns None
                round_no=int(meta.get("round") or 1),
                gold=int(meta.get("gold") or 0),
                dispatch_level=int(meta.get("dispatch_level") or 1),
                **env_kw,
            )
            shell_timing["sidecar_ms"] = int((time.perf_counter() - t_side) * 1000)
            if out.get("ok") and isinstance(out.get("result"), dict):
                out["result"] = self._sanitize_result(out["result"])
                inner0 = out.get("result") if isinstance(out.get("result"), dict) else {}
                # Difficulty-select: persist 规程等级, skip shop glow.
                if isinstance(inner0, dict) and inner0.get("skip_shop"):
                    opening = inner0.get("opening") if isinstance(inner0.get("opening"), dict) else {}
                    patch = dict(opening)
                    patch["shot_path"] = str(tmp)
                    if inner0.get("procedure_level") is not None:
                        patch["procedure_level"] = inner0["procedure_level"]
                    try:
                        prev = run_env_mod.load_run_env()
                        merged = run_env_mod.merge_phase(prev, patch)
                        run_env_mod.save_run_env(merged)
                        self.push_run_env(
                            {
                                "ok": True,
                                "path": str(run_env_mod.RUN_ENV_PATH),
                                "env": merged,
                                "summary": run_env_mod.summary_lines(merged),
                            }
                        )
                        out["run_env"] = merged
                        out["procedure_level"] = merged.get("procedure_level")
                    except Exception:
                        pass
                    shell_timing["glow_ms"] = 0
                    shell_timing["roster_ms"] = 0
                    shell_timing["total_ms"] = int((time.perf_counter() - t_shell) * 1000)
                    out["timing"] = {"shell": shell_timing, "sidecar": inner0.get("timing") or {}}
                    if out.get("latency_ms") is None:
                        out["latency_ms"] = shell_timing["total_ms"]
                    return out
                self._remember_gold_from_result(out["result"])
                t_glow = time.perf_counter()
                # Prefer lineup multi-card glow if user locked a plan
                if self._lineup_sel.get("names"):
                    iw = self._capture_width_from_result(out["result"])
                    frames = resolve_lineup_highlight(
                        self._lineup_sel["names"],
                        self._last_shop,
                        dispatch_level=self._last_dispatch,
                        image_width=iw,
                    )
                    self._last_frames = list(frames)
                    self._glow.set_frames(frames)
                else:
                    self.apply_highlight_from_result(out["result"])
                shell_timing["glow_ms"] = int((time.perf_counter() - t_glow) * 1000)
                # Persist magnifier enemies into run_env when panel was open.
                panel = inner0.get("enemy_panel") if isinstance(inner0, dict) else None
                if isinstance(panel, dict) and panel.get("names"):
                    try:
                        env = run_env_mod.merge_enemy_wave(panel)
                        self.push_run_env(
                            {
                                "ok": True,
                                "path": str(run_env_mod.RUN_ENV_PATH),
                                "env": env,
                                "summary": run_env_mod.summary_lines(env),
                            }
                        )
                    except Exception:
                        pass
                t_ui = time.perf_counter()
                self.push_roster(out)
                shell_timing["roster_ms"] = int((time.perf_counter() - t_ui) * 1000)
            shell_timing["total_ms"] = int((time.perf_counter() - t_shell) * 1000)
            if isinstance(out, dict):
                # Merge sidecar result.timing under shell envelope.
                inner = out.get("result") if isinstance(out.get("result"), dict) else {}
                side_t = inner.get("timing") if isinstance(inner, dict) else None
                out["timing"] = {
                    "shell": shell_timing,
                    "sidecar": side_t if isinstance(side_t, dict) else {},
                }
                if out.get("latency_ms") is None:
                    out["latency_ms"] = shell_timing["total_ms"]
            return out
        except Exception as e:
            out = {"ok": False, "error": str(e)}
            return out
        finally:
            try:
                op_log_mod.append_advise_event(out, trigger=trig)
            except Exception:
                pass
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
            _analyze_lock.release()

    def capture_enemy_panel(self, meta: dict | None = None) -> dict:
        """Auto-W magnifier → wait → capture → enemy OCR → run_env / 本波敌人."""
        meta = meta or {}
        if not _analyze_lock.acquire(blocking=False):
            return {"ok": False, "error": "分析进行中，请稍候"}
        tmp: Path | None = None
        t0 = time.perf_counter()
        try:
            if not self.bridge.ensure_warm():
                return {"ok": False, "error": "sidecar not ready"}
            # Keep glow prefs: clear while OCR runs (no stale shop frame).
            self.clear_highlight()
            # 1–2: focus game + SendInput W (not into overlay), wait 0.5s.
            hotkey = w32.open_enemy_magnifier(key="W", wait_s=0.5)
            # Overlay stays always-on-top; reassert after brief focus steal.
            try:
                self._reassert_topmost()
            except Exception:
                pass
            tmp = grab_primary_to_temp(prefix="weishu-enemy-")
            out = self.bridge.parse_enemy_panel(str(tmp), timeout=45.0)
            if not out.get("ok"):
                return {
                    "ok": False,
                    "error": out.get("error") or "enemy panel OCR failed",
                    "hotkey": hotkey,
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                }
            panel = out.get("result") if isinstance(out.get("result"), dict) else {}
            env = run_env_mod.load_run_env()
            if panel.get("names"):
                env = run_env_mod.merge_enemy_wave(panel)
            summary = run_env_mod.summary_lines(env)
            result = {
                "ok": True,
                "enemy_panel": panel,
                "env": env,
                "summary": summary,
                "path": str(run_env_mod.RUN_ENV_PATH),
                "hotkey": hotkey,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "sidecar_ms": out.get("latency_ms"),
            }
            self.push_run_env(result)
            try:
                self.refresh_lineups({})
            except Exception:
                pass
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
            _analyze_lock.release()

    def analyze_shot(self, meta: dict) -> dict:
        if not _analyze_lock.acquire(blocking=False):
            out_busy = {"ok": False, "error": "分析进行中，请稍候"}
            op_log_mod.append_advise_event(out_busy, trigger="manual")
            return out_busy
        self.clear_highlight()
        out: dict = {"ok": False, "error": "unknown"}
        try:
            window = self._panel()
            shot = meta.get("shot_path")
            if not shot:
                paths = (
                    window.create_file_dialog(
                        webview.OPEN_DIALOG,
                        allow_multiple=False,
                        file_types=(
                            "Image Files (*.png;*.jpg;*.jpeg)",
                            "All files (*.*)",
                        ),
                    )
                    if window
                    else None
                )
                if not paths:
                    out = {"cancelled": True, "ok": False}
                    return out
                shot = paths[0] if isinstance(paths, (list, tuple)) else paths
            env_kw = self._shot_kwargs_from_run_env(meta)
            out = self.bridge.recommend_shot(
                shot,
                round_no=int(meta.get("round") or 1),
                gold=int(meta.get("gold") or 0),
                dispatch_level=int(meta.get("dispatch_level") or 1),
                **env_kw,
            )
            if out.get("ok") and isinstance(out.get("result"), dict):
                out["result"] = self._sanitize_result(out["result"])
                self._remember_gold_from_result(out["result"])
                if self._lineup_sel.get("names"):
                    iw = self._capture_width_from_result(out["result"])
                    frames = resolve_lineup_highlight(
                        self._lineup_sel["names"],
                        self._last_shop,
                        dispatch_level=self._last_dispatch,
                        image_width=iw,
                    )
                    self._last_frames = list(frames)
                    self._glow.set_frames(frames)
                else:
                    self.apply_highlight_from_result(out["result"])
                self.push_roster(out)
            return out
        except Exception as e:
            out = {"ok": False, "error": str(e)}
            return out
        finally:
            if not out.get("cancelled"):
                try:
                    op_log_mod.append_advise_event(out, trigger="manual")
                except Exception:
                    pass
            _analyze_lock.release()

    def select_lineup_highlight(
        self,
        lineup_id: str,
        stage: str = "mid",
        names: list | None = None,
    ) -> dict:
        """User picked a lineup stage → glow shop cards in ``names``.

        ``names`` must be on-board ``next_targets`` only. Do not pass
        ``off_board_targets`` (场下经济) here — those are UI-only.
        """
        stage = (stage or "mid").strip().lower()
        if stage not in ("early", "mid", "late"):
            stage = "mid"
        name_list = [str(n) for n in (names or []) if n]
        self._lineup_sel = {
            "id": lineup_id,
            "stage": stage,
            "names": name_list,
        }
        frames = resolve_lineup_highlight(
            name_list,
            self._last_shop,
            dispatch_level=self._last_dispatch,
            image_width=self._last_capture_w,
        )
        self._last_frames = list(frames)
        self._glow.set_frames(frames)
        return {
            "ok": True,
            "id": lineup_id,
            "stage": stage,
            "names": name_list,
            "glow_count": len(frames),
            "shop_n": len(self._last_shop or []),
        }

    def clear_lineup_highlight(self) -> bool:
        self._lineup_sel = {"id": None, "stage": "mid", "names": []}
        return self.clear_highlight()

    def get_lineup_selection(self) -> dict:
        return dict(self._lineup_sel)

    def refresh_lineups(self, meta: dict | None = None) -> dict:
        """Recompute target_comps from last board + run_env (no shop OCR)."""
        meta = meta or {}
        if not self.bridge.ensure_warm():
            return {"ok": False, "error": "sidecar not ready"}
        env = run_env_mod.load_run_env()
        patch = run_env_mod.gamestate_patch()
        payload = {
            "board": self._last_board or meta.get("board") or [],
            "round": int(meta.get("round") or 1),
            "gold": int(meta.get("gold") or (self._last_gold or 0)),
            "dispatch_level": int(meta.get("dispatch_level") or 1),
            "difficulty": patch.get("difficulty") or "standard",
            "target_bond": (meta.get("target_bond") or patch.get("target_bond") or ""),
            "enemy_types": list(patch.get("enemy_types") or env.get("enemy_types") or []),
            "banned_operators": list(patch.get("banned_operators") or []),
            "banned_bonds": list(patch.get("banned_bonds") or []),
            "core_bonds": list(env.get("core_bonds") or []),
        }
        if patch.get("regulation_level") is not None:
            payload["regulation_level"] = int(patch["regulation_level"])
        elif env.get("procedure_level") is not None:
            try:
                payload["regulation_level"] = int(env["procedure_level"])
            except (TypeError, ValueError):
                pass
        out = self.bridge._sidecar.recommend_lineups_only(payload)
        if out.get("ok") and isinstance(out.get("result"), dict):
            self.push_roster(out)
        return out

    def update_highlight(
        self,
        top_pick: dict | None,
        shop: list | None = None,
        dispatch_level: int | None = None,
        image_width: int | None = None,
    ) -> list:
        # Prefer Python-side last shop (keeps raw.cx_frac). JS round-trips can
        # drop nested raw and force the brittle left-pad index path.
        use_shop = shop if shop else self._last_shop
        if shop and self._last_shop and len(shop) == len(self._last_shop):
            # Merge raw from last OCR onto JS shop names when raw missing.
            merged = []
            for a, b in zip(shop, self._last_shop):
                if not isinstance(a, dict):
                    merged.append(a)
                    continue
                d = dict(a)
                if not isinstance(d.get("raw"), dict) and isinstance(b, dict):
                    if b.get("raw"):
                        d["raw"] = b["raw"]
                merged.append(d)
            use_shop = merged
        level = (
            dispatch_level
            if dispatch_level is not None
            else self._last_dispatch
        )
        iw = image_width if image_width is not None else self._last_capture_w
        frames = resolve_highlight(
            top_pick, use_shop, dispatch_level=level, image_width=iw
        )
        self._last_frames = list(frames)
        # Always replace: empty hides; non-empty force-shows + paints (every OCR).
        self._glow.set_frames(frames)
        return frames

    def reassert_last_highlight(self) -> list:
        """Panel paint follow-up: re-anchor glow from last OCR shop, not JS shop.

        Avoids a second resolve with stripped ``raw`` after analyze_live already
        drew the correct frames — which looked like drift across OCR cycles.
        """
        if self._lineup_sel.get("names"):
            frames = resolve_lineup_highlight(
                self._lineup_sel["names"],
                self._last_shop,
                dispatch_level=self._last_dispatch,
                image_width=self._last_capture_w,
            )
            self._last_frames = list(frames)
            self._glow.set_frames(frames)
            return frames
        frames = list(self._last_frames or [])
        self._glow.set_frames(frames)
        return frames

    def _sanitize_result(self, data: dict) -> dict:
        """Apply shell affordability filter; use OCR/state gold."""
        if not isinstance(data, dict):
            return data
        gold = None
        st = data.get("state") if isinstance(data.get("state"), dict) else {}
        res = data.get("resources") if isinstance(data.get("resources"), dict) else {}
        status = str(res.get("gold_status") or "")
        # Prefer resources.gold; never invent 0 from missing OCR.
        if res.get("gold") is not None:
            gold = res.get("gold")
        elif status in ("ocr", "last_good") and st.get("gold") is not None:
            gold = st.get("gold")
        return filter_advice(data, gold=gold)

    def apply_highlight_from_result(self, data: dict) -> list:
        """Map result → glow. Must run after every successful OCR (incl. 2nd+)."""
        if not isinstance(data, dict):
            self.clear_highlight()
            return []
        data = self._sanitize_result(data)
        tp = data.get("top_pick")
        shop = None
        level = None
        st = data.get("state")
        if isinstance(st, dict):
            shop = st.get("shop")
            level = st.get("dispatch_level")
        if shop is None:
            shop = data.get("shop")
        res = data.get("resources") or {}
        if level is None:
            level = res.get("dispatch_level")
        iw = self._capture_width_from_result(data)
        # gold==0 / ready: glow 准备就绪 only — never shop buy frames
        sf = data.get("shell_filter") if isinstance(data.get("shell_filter"), dict) else {}
        verb = str((tp or {}).get("verb") or "").lower()
        if sf.get("mode") == "gold_zero_battle" or verb in (
            "ready", "battle", "开战", "准备", "准备就绪", "reposition", "adjust", "位置"
        ):
            return self.update_highlight(
                tp, shop, dispatch_level=level, image_width=iw
            )

        # Never glow an unaffordable buy — fall through to next affordable pick
        if tp and verb in ("buy", "购买"):
            if tp.get("affordable") is False or tp.get("shell_demoted"):
                for r in data.get("recommendations") or []:
                    if r.get("shell_demoted") or r.get("affordable") is False:
                        continue
                    if str(r.get("verb") or "").lower() in ("buy", "购买") and (
                        r.get("affordable") is False or r.get("shell_demoted")
                    ):
                        continue
                    tp = r
                    break
                else:
                    self.clear_highlight()
                    return []
        frames = self.update_highlight(
            tp, shop, dispatch_level=level, image_width=iw
        )
        # If buy target missed shop OCR names, still try refresh/upgrade fallbacks
        if not frames and tp:
            verb = str(tp.get("verb") or "").lower()
            if verb in ("buy", "购买", "merge"):
                for r in data.get("recommendations") or []:
                    if r.get("shell_demoted") or r.get("affordable") is False:
                        continue
                    v = str(r.get("verb") or "").lower()
                    if v in ("buy", "购买", "merge"):
                        continue
                    frames = self.update_highlight(
                        r, shop, dispatch_level=level, image_width=iw
                    )
                    if frames:
                        break
        return frames

    def toggle_visible(self) -> bool:
        """Hotkey / 隐: collapse-expand (never destroy the panel window)."""
        return self.toggle_panel_collapsed()

    def toggle_panel_collapsed(self) -> bool:
        """Shrink advice panel to title bar / restore."""
        win = self._panel()
        if not win:
            return False
        collapsed = not bool(self._holder.get("panel_collapsed", False))
        self._holder["panel_collapsed"] = collapsed
        win_cfg = self.cfg.get("window") or {}
        full_h = int(
            self._holder.get("panel_full_h")
            or win_cfg.get("height")
            or 820
        )
        self._holder["panel_full_h"] = full_h
        width = int(win_cfg.get("width") or 460)
        try:
            win.evaluate_js(
                "window.__panel_set_collapsed && window.__panel_set_collapsed(%s)"
                % ("true" if collapsed else "false")
            )
        except Exception:
            pass
        try:
            win.resize(width, 48 if collapsed else full_h)
        except Exception:
            pass
        self._reassert_topmost()
        self._visible = True
        return collapsed

    def toggle_interact(self) -> bool:
        self._interact = not self._interact
        self._apply_panel_styles()
        self._sync_chrome_guard()
        return self._interact

    def _ensure_hwnd(self) -> None:
        if not self._hwnd:
            hwnd = w32.find_window_by_title(WINDOW_TITLE)
            if hwnd:
                self._hwnd = hwnd

    def _roster_hwnd(self) -> int | None:
        hwnd = w32.find_window_by_title(ROSTER_TITLE)
        return int(hwnd) if hwnd else None

    def _reassert_topmost(self) -> None:
        """Keep advice + lineup panels above the game (HWND_TOPMOST)."""
        self._ensure_hwnd()
        if self._hwnd:
            try:
                w32.set_topmost(self._hwnd)
            except Exception:
                pass
        try:
            hwnd_r = self._roster_hwnd()
            if hwnd_r:
                w32.set_topmost(hwnd_r)
        except Exception:
            pass

    def _apply_panel_styles(self) -> None:
        self._ensure_hwnd()
        if not self._hwnd:
            return
        w32.set_layered_alpha(self._hwnd, self._alpha)
        if self._interact:
            w32.set_click_through(self._hwnd, enabled=False)
        else:
            # Body click-through, but title-bar strip stays hittable.
            over = w32.cursor_in_window_chrome(self._hwnd, chrome_h=56)
            w32.set_click_through(self._hwnd, enabled=not over)
        self._reassert_topmost()

    def _sync_chrome_guard(self) -> None:
        """While 穿透, poll cursor so 交互/隐 on the title bar stay clickable."""
        if self._interact:
            self._chrome_stop.set()
            return
        if self._chrome_thread and self._chrome_thread.is_alive():
            return
        self._chrome_stop.clear()

        def loop() -> None:
            last: bool | None = None
            ticks = 0
            while not self._chrome_stop.is_set():
                if self._interact:
                    break
                self._ensure_hwnd()
                if self._hwnd:
                    over = w32.cursor_in_window_chrome(self._hwnd, chrome_h=56)
                    want_through = not over
                    if want_through != last:
                        try:
                            w32.set_click_through(self._hwnd, enabled=want_through)
                        except Exception:
                            pass
                        last = want_through
                ticks += 1
                # Game focus / resize can steal Z-order — refresh ~2Hz.
                if ticks % 12 == 0:
                    self._reassert_topmost()
                self._chrome_stop.wait(0.04)

        self._chrome_thread = threading.Thread(
            target=loop, name="panel-chrome-guard", daemon=True
        )
        self._chrome_thread.start()

    def apply_chrome(self) -> None:
        for _ in range(40):
            self._ensure_hwnd()
            if self._hwnd:
                break
            threading.Event().wait(0.05)
        self._apply_panel_styles()
        self._sync_chrome_guard()
        self._reassert_topmost()
        # Keep a light always-on topmost heartbeat even in 交互 mode.
        def topmost_heartbeat() -> None:
            while True:
                try:
                    self._reassert_topmost()
                except Exception:
                    pass
                threading.Event().wait(1.0)

        if not getattr(self, "_topmost_thread", None) or not self._topmost_thread.is_alive():
            self._topmost_thread = threading.Thread(
                target=topmost_heartbeat, name="panel-topmost", daemon=True
            )
            self._topmost_thread.start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="weishu-box overlay (read-only)")
    parser.parse_args(argv)

    _enable_dpi_awareness()
    _soften_process_priority()
    cfg = load_config()
    bridge = AdvisorBridge(cfg["kernel_path"], cfg["kernel_python"])
    glow = GlowOverlay()
    holder: dict = {"panel": None}
    api = Api(cfg, bridge, holder, glow)

    panel_html = (UI_DIR / "index.html").as_uri()
    roster_html = (UI_DIR / "roster.html").as_uri()
    win_cfg = cfg.get("window") or {}
    sw, sh = _primary_screen_size()
    panel_w = int(win_cfg.get("width") or 460)
    panel_h = int(win_cfg.get("height") or 820)
    panel_x = win_cfg.get("x")
    panel_y = win_cfg.get("y")
    if panel_x is None:
        panel_x = max(40, sw - panel_w - 40)
    if panel_y is None:
        panel_y = 40

    roster_w = int(win_cfg.get("roster_width") or 420)
    roster_h = int(win_cfg.get("roster_height") or 720)
    roster_x = max(20, panel_x - roster_w - 16)
    roster_y = panel_y

    # Main advice panel (right) + companion roster/comps panel (left of it).
    # Both are small panels — never fullscreen WebView2 (white-screen risk).
    panel = webview.create_window(
        WINDOW_TITLE,
        url=panel_html,
        js_api=api,
        width=panel_w,
        height=panel_h,
        x=panel_x,
        y=panel_y,
        on_top=True,
        frameless=True,
        easy_drag=True,
        background_color="#0C1016",
        transparent=False,
        resizable=True,
    )
    roster = webview.create_window(
        ROSTER_TITLE,
        url=roster_html,
        js_api=api,
        width=roster_w,
        height=roster_h,
        x=roster_x,
        y=roster_y,
        on_top=True,
        frameless=True,
        easy_drag=True,
        background_color="#0C1016",
        transparent=False,
        resizable=True,
    )
    holder["panel"] = panel
    holder["roster"] = roster
    holder["roster_visible"] = True
    holder["roster_collapsed"] = False
    holder["roster_full_h"] = roster_h
    holder["panel_collapsed"] = False
    holder["panel_full_h"] = panel_h

    hotkeys = w32.HotkeyPump()

    def on_toggle():
        # Collapse/expand — never hide/destroy the advice window.
        api.toggle_panel_collapsed()

    def on_analyze():
        def work():
            try:
                meta_live = api._read_form_meta()
                result = api._run_live_cycle_and_push(meta_live, source="hotkey")
                if result.get("ok"):
                    api.note_manual_ocr_done(True, meta_live)
            except Exception as e:
                err = json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
                api._push_panel_js(
                    f"window.__weishu_render && window.__weishu_render({err})"
                )

        threading.Thread(target=work, name="weishu-live", daemon=True).start()

    def after_start():
        api.apply_chrome()
        # Soft style for roster companion (topmost, no click-through needed)
        try:
            hwnd_r = w32.find_window_by_title(ROSTER_TITLE)
            if hwnd_r:
                w32.set_layered_alpha(hwnd_r, api._alpha)
        except Exception:
            pass
        api._reassert_topmost()
        try:
            op_log_mod.start_match(note="shell launch")
        except Exception:
            pass
        hotkeys.start(
            [
                (1, w32.MOD_CONTROL | w32.MOD_SHIFT, 0x57, on_toggle),
                (2, w32.MOD_CONTROL | w32.MOD_SHIFT, 0x41, on_analyze),
            ]
        )
        # Warm RapidOCR in background (no OCR run until user clicks).
        threading.Thread(
            target=lambda: bridge.ensure_warm(),
            name="sidecar-warm",
            daemon=True,
        ).start()

        def boot_run_env():
            threading.Event().wait(1.2)
            try:
                api.push_run_env()
            except Exception:
                pass

        threading.Thread(
            target=boot_run_env, name="boot-run-env", daemon=True
        ).start()
        # Optional one-shot verify file (deleted immediately). Normal launches
        # have no such file → no auto OCR.
        trigger = ROOT / ".once_shot"
        if trigger.is_file():
            try:
                shot_path = trigger.read_text(encoding="utf-8").strip()
            except Exception:
                shot_path = ""
            try:
                trigger.unlink(missing_ok=True)
            except Exception:
                pass

            def boot_shot():
                threading.Event().wait(1.0)
                win = holder.get("panel")
                meta = {
                    "round": 1,
                    "gold": 0,
                    "dispatch_level": 1,
                    "difficulty": "standard",
                    "shot_path": shot_path,
                }
                result = api.analyze_shot(meta)
                if win:
                    payload = json.dumps(result, ensure_ascii=False)
                    try:
                        win.evaluate_js(
                            f"window.__weishu_render && window.__weishu_render({payload})"
                        )
                    except Exception:
                        pass

            if shot_path and Path(shot_path).is_file():
                threading.Thread(
                    target=boot_shot, name="once-shot", daemon=True
                ).start()

    try:
        webview.start(after_start, gui="edgechromium")
    except Exception:
        webview.start(after_start)
    finally:
        try:
            api._chrome_stop.set()
        except Exception:
            pass
        hotkeys.stop()
        glow.destroy()
        bridge.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
