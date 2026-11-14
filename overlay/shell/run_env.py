# -*- coding: utf-8 -*-
"""Per-run opening environment (合约/策略/自选) — session file, not kernel data/."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import ROOT

SESSION_DIR = ROOT / "session"
RUN_ENV_PATH = SESSION_DIR / "run_env.json"
LAST_SHOT_PATH = SESSION_DIR / "last_opening.jpg"
BOARD_CACHE_PATH = SESSION_DIR / "board_cache.json"

# Fields that merge into GameState / sidecar shot request.
# procedure_level (run_env) → regulation_level (GameState / clear_margin).
GAMESTATE_KEYS = (
    "difficulty",
    "enemy_types",
    "banned_operators",
    "banned_bonds",
    "target_bond",
)


def empty_run_env() -> dict:
    return {
        "version": 1,
        "captured_at": None,
        "screen": None,
        "source_shots": {
            "difficulty_select": None,
            "contract": None,
            "strategy": None,
            "draft": None,
            "last": None,
        },
        "difficulty": "standard",
        "procedure_level": None,
        "core_bonds": [],
        "splash_bonds": [],
        "core_bonds_seen": [],
        "splash_bonds_seen": [],
        "target_bond": None,
        "enemy_types": [],
        "enemy_labels_raw": [],
        "enemy_leader_raw": None,
        # Live magnifier-panel wave (shop OCR / 读敌人) — not opening 特训 tags.
        "enemy_wave_names": [],
        "enemy_wave_resolutions": [],
        "enemy_wave_at": None,
        "strategy_raw": [],
        "banned_operators": [],
        "banned_bonds": [],
        "draft_picks": [],
        "warnings": [],
        "raw_texts": [],
    }


def ensure_session_dir() -> Path:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_DIR


def load_run_env(path: Optional[Path] = None) -> dict:
    p = path or RUN_ENV_PATH
    if not p.is_file():
        return empty_run_env()
    try:
        with open(p, encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return empty_run_env()
    if not isinstance(data, dict):
        return empty_run_env()
    base = empty_run_env()
    base.update({k: data[k] for k in data if k in base or k in ("version",)})
    # nested source_shots
    shots = data.get("source_shots") if isinstance(data.get("source_shots"), dict) else {}
    base["source_shots"] = {**empty_run_env()["source_shots"], **shots}
    return base


def save_run_env(env: dict, path: Optional[Path] = None) -> Path:
    ensure_session_dir()
    p = path or RUN_ENV_PATH
    out = deepcopy(env) if isinstance(env, dict) else empty_run_env()
    out["version"] = int(out.get("version") or 1)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return p


def stamp_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def merge_phase(prev: dict, parsed: dict) -> dict:
    """Merge a new OCR parse into the persisted run env (phase-aware)."""
    out = deepcopy(prev) if prev else empty_run_env()
    screen = parsed.get("screen") or out.get("screen")
    out["captured_at"] = stamp_now()
    out["screen"] = screen
    out["warnings"] = list(parsed.get("warnings") or [])
    out["raw_texts"] = list(parsed.get("raw_texts") or [])[:80]

    # Always refresh these when present
    for key in (
        "difficulty",
        "procedure_level",
        "enemy_types",
        "enemy_labels_raw",
        "enemy_leader_raw",
        "strategy_raw",
        "banned_operators",
        "banned_bonds",
        "draft_picks",
        "core_bonds",
        "splash_bonds",
        "core_bonds_seen",
        "splash_bonds_seen",
        "target_bond",
    ):
        val = parsed.get(key)
        if val is None:
            continue
        if isinstance(val, list) and not val and key in (
            "enemy_types",
            "enemy_labels_raw",
            "banned_operators",
            "strategy_raw",
            "core_bonds",
            "splash_bonds",
            "core_bonds_seen",
            "splash_bonds_seen",
            "draft_picks",
            "banned_bonds",
        ):
            # Empty list from a non-matching phase should not wipe prior data
            if screen == "contract" and key in (
                "enemy_types",
                "enemy_labels_raw",
                "core_bonds",
                "splash_bonds",
                "core_bonds_seen",
                "splash_bonds_seen",
            ):
                out[key] = val
            elif screen == "strategy" and key == "strategy_raw":
                out[key] = val
            elif screen == "draft" and key in (
                "banned_operators",
                "draft_picks",
                "banned_bonds",
            ):
                out[key] = val
            continue
        # None / empty string for scalar leader should not wipe prior contract data
        if key == "enemy_leader_raw" and not val and screen != "contract":
            continue
        if key == "procedure_level" and val is None:
            continue
        if key == "target_bond" and not val and screen != "contract":
            continue
        out[key] = val

    shots = out.setdefault("source_shots", empty_run_env()["source_shots"])
    shot_path = parsed.get("shot_path")
    if shot_path:
        shots["last"] = shot_path
        if screen in ("contract", "strategy", "draft", "difficulty_select"):
            # Persist under stable key; difficulty_select shares "last" + alias.
            if screen == "difficulty_select":
                shots["difficulty_select"] = shot_path
            else:
                shots[screen] = shot_path

    # Only auto-fill target_bond when exactly one locked core bond.
    if not out.get("target_bond") and len(out.get("core_bonds") or []) == 1:
        out["target_bond"] = out["core_bonds"][0]

    return out


def gamestate_patch(env: Optional[dict] = None) -> dict[str, Any]:
    """Subset to inject into recommend_shot / GameState.

    Maps run_env ``procedure_level`` → advisor ``regulation_level`` (1..20 HP
    curve / clear_margin). Distinct from shop ``dispatch_level`` (1..6).
    """
    data = env if isinstance(env, dict) else load_run_env()
    patch: dict[str, Any] = {}
    for k in GAMESTATE_KEYS:
        v = data.get(k)
        if v is None or v == "" or v == []:
            continue
        patch[k] = v
    pl = data.get("procedure_level")
    if pl is not None:
        try:
            lv = int(pl)
            if 1 <= lv <= 20:
                patch["regulation_level"] = lv
        except (TypeError, ValueError):
            pass
    return patch


def summary_lines(env: dict) -> list[str]:
    """Short Chinese lines for the panel."""
    lines: list[str] = []
    screen = env.get("screen") or "?"
    label = {
        "difficulty_select": "规程难度选择",
        "contract": "合约 1/3",
        "strategy": "策略 2/3",
        "draft": "自选 3/3",
    }.get(screen, str(screen))
    lines.append(f"屏：{label}")
    if env.get("procedure_level") is not None:
        lines.append(f"规程等级 {env['procedure_level']}")
    if env.get("enemy_types") or env.get("enemy_labels_raw"):
        labels = env.get("enemy_labels_raw") or []
        if not labels:
            # fallback: show keys
            labels = env.get("enemy_types") or []
        lines.append("特训敌人：" + "、".join(str(x) for x in labels))
    if env.get("enemy_wave_names"):
        wave = "、".join(str(x) for x in env["enemy_wave_names"])
        keys = env.get("enemy_types") or []
        key_s = (" → " + "/".join(str(k) for k in keys)) if keys else ""
        lines.append(f"本波敌人：{wave}{key_s}")
    if env.get("enemy_leader_raw"):
        lines.append(f"假想敌：{env['enemy_leader_raw']}")
    if env.get("core_bonds"):
        lines.append("核心盟约：" + "、".join(env["core_bonds"]))
    elif env.get("core_bonds_seen"):
        lines.append(
            "可见核心(未锁)：" + "、".join(env["core_bonds_seen"][:8])
            + ("…" if len(env["core_bonds_seen"]) > 8 else "")
        )
    if env.get("splash_bonds"):
        shown = env["splash_bonds"]
        lines.append("附加盟约：" + "、".join(shown) + f"（{len(shown)}）")
    elif env.get("splash_bonds_seen"):
        lines.append(
            "可见附加(未锁)：" + "、".join(env["splash_bonds_seen"][:8])
            + ("…" if len(env["splash_bonds_seen"]) > 8 else "")
        )
    if env.get("target_bond"):
        lines.append(f"目标羁绊：{env['target_bond']}")
    if env.get("strategy_raw"):
        lines.append("策略：" + "、".join(env["strategy_raw"]))
    if env.get("banned_operators"):
        lines.append("本局禁用：" + "、".join(env["banned_operators"]))
    if env.get("banned_bonds"):
        lines.append("禁用羁绊：" + "、".join(env["banned_bonds"]))
    for w in (env.get("warnings") or [])[:2]:
        lines.append("⚠ " + str(w))
    if not any(
        env.get(k)
        for k in (
            "enemy_types",
            "enemy_wave_names",
            "banned_operators",
            "strategy_raw",
            "core_bonds",
            "splash_bonds",
            "core_bonds_seen",
            "enemy_leader_raw",
        )
    ):
        lines.append("（未解析到关键字段，可换开局屏再试）")
    return lines


def merge_enemy_wave(panel: dict, path: Optional[Path] = None) -> dict:
    """Persist magnifier-panel OCR into run_env (feeds counter sort / shop).

    Only updates when the panel produced at least one recognized name.
    Trait keys replace prior enemy_types when present (panel is live wave).
    """
    env = load_run_env(path)
    if not isinstance(panel, dict) or not panel.get("names"):
        return env
    env["enemy_wave_names"] = list(panel.get("names") or [])
    env["enemy_wave_resolutions"] = list(panel.get("resolutions") or [])
    env["enemy_wave_at"] = stamp_now()
    keys = list(panel.get("trait_keys") or [])
    if keys:
        env["enemy_types"] = keys
        # Keep opening 特训 labels; wave names are the live list.
        labels = []
        for r in panel.get("resolutions") or []:
            if not isinstance(r, dict):
                continue
            nm = r.get("name") or r.get("input")
            st = r.get("status") or ""
            if not nm:
                continue
            if st == "tactical":
                tk = "/".join(r.get("trait_keys") or []) or "?"
                labels.append(f"{nm}({tk})")
            elif st == "untyped":
                labels.append(f"{nm}(普通)")
            else:
                labels.append(str(nm))
        if labels:
            env["enemy_labels_raw"] = labels
    save_run_env(env, path)
    return env


def empty_board_cache() -> dict:
    return {
        "version": 1,
        "captured_at": None,
        "source": None,
        "board": [],
        "equipment": {},
        "warnings": [],
        "badge_count": 0,
        "named_count": 0,
    }


def load_board_cache(path: Optional[Path] = None) -> dict:
    p = path or BOARD_CACHE_PATH
    if not p.is_file():
        return empty_board_cache()
    try:
        with open(p, encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return empty_board_cache()
    if not isinstance(data, dict):
        return empty_board_cache()
    base = empty_board_cache()
    base.update({k: data[k] for k in data if k in base})
    if not isinstance(base.get("board"), list):
        base["board"] = []
    if not isinstance(base.get("equipment"), dict):
        base["equipment"] = {}
    return base


def save_board_cache(
    board: list,
    equipment: Optional[dict] = None,
    *,
    source: str = "click_panel",
    warnings: Optional[list] = None,
    badge_count: int = 0,
    named_count: int = 0,
    path: Optional[Path] = None,
) -> Path:
    ensure_session_dir()
    p = path or BOARD_CACHE_PATH
    out = {
        "version": 1,
        "captured_at": stamp_now(),
        "source": source,
        "board": list(board or []),
        "equipment": dict(equipment or {}),
        "warnings": list(warnings or []),
        "badge_count": int(badge_count or 0),
        "named_count": int(named_count or 0),
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return p


def clear_board_cache(path: Optional[Path] = None) -> None:
    p = path or BOARD_CACHE_PATH
    try:
        if p.is_file():
            p.unlink()
    except Exception:
        pass


def empty_board_cache() -> dict:
    return {
        "version": 1,
        "captured_at": None,
        "source": None,
        "board": [],
        "equipment": {},
        "warnings": [],
        "badge_count": 0,
        "named_count": 0,
    }


def load_board_cache(path: Optional[Path] = None) -> dict:
    p = path or BOARD_CACHE_PATH
    if not p.is_file():
        return empty_board_cache()
    try:
        with open(p, encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return empty_board_cache()
    if not isinstance(data, dict):
        return empty_board_cache()
    base = empty_board_cache()
    base.update({k: data[k] for k in data if k in base})
    if not isinstance(base.get("board"), list):
        base["board"] = []
    if not isinstance(base.get("equipment"), dict):
        base["equipment"] = {}
    return base


def save_board_cache(
    board: list,
    equipment: Optional[dict] = None,
    *,
    source: str = "click_panel",
    warnings: Optional[list] = None,
    badge_count: int = 0,
    named_count: int = 0,
    path: Optional[Path] = None,
) -> Path:
    ensure_session_dir()
    p = path or BOARD_CACHE_PATH
    out = {
        "version": 1,
        "captured_at": stamp_now(),
        "source": source,
        "board": list(board or []),
        "equipment": dict(equipment or {}),
        "warnings": list(warnings or []),
        "badge_count": int(badge_count or 0),
        "named_count": int(named_count or 0),
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return p


def clear_board_cache(path: Optional[Path] = None) -> None:
    p = path or BOARD_CACHE_PATH
    try:
        if p.is_file():
            p.unlink()
    except Exception:
        pass
