# -*- coding: utf-8 -*-
"""Shell-owned per-match operation log (OCR snapshot + advice).

Layout:
  session/matches/<match_id>/meta.json
  session/matches/<match_id>/events.jsonl

No screenshots by default. Does not change kernel scoring.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import ROOT
from . import run_env as run_env_mod

SESSION_DIR = ROOT / "session"
MATCHES_DIR = SESSION_DIR / "matches"
CURRENT_MATCH_PATH = SESSION_DIR / "current_match.json"

# Retention: keep newest N match folders.
KEEP_MATCHES = 30

_lock = threading.Lock()
_seq = 0
_match_id: Optional[str] = None
# True only between start_match and end_match. After 结束一局, appends are skipped
# until the next 开始新一局 (no silent ensure_match into a new folder).
_accepting: bool = False


def _stamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _match_dir(match_id: str) -> Path:
    return MATCHES_DIR / match_id


def ensure_matches_root() -> Path:
    MATCHES_DIR.mkdir(parents=True, exist_ok=True)
    return MATCHES_DIR


def current_match_id() -> Optional[str]:
    return _match_id


def match_paths(match_id: Optional[str] = None) -> dict:
    mid = match_id or _match_id
    if not mid:
        return {
            "match_id": None,
            "dir": None,
            "events": None,
            "meta": None,
            "active": False,
        }
    d = _match_dir(mid)
    return {
        "match_id": mid,
        "dir": str(d),
        "events": str(d / "events.jsonl"),
        "meta": str(d / "meta.json"),
        "active": bool(_accepting and mid == _match_id),
    }


def _write_meta(match_id: str, **patch: Any) -> Path:
    d = _match_dir(match_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "meta.json"
    meta: dict[str, Any] = {}
    if path.is_file():
        try:
            with open(path, encoding="utf-8-sig") as f:
                meta = json.load(f) or {}
        except Exception:
            meta = {}
    meta.setdefault("match_id", match_id)
    meta.setdefault("started_at", _stamp())
    meta.update({k: v for k, v in patch.items() if v is not None})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return path


def _remember_current(match_id: str) -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    with open(CURRENT_MATCH_PATH, "w", encoding="utf-8") as f:
        json.dump({"match_id": match_id, "updated_at": _stamp()}, f, ensure_ascii=False)


def prune_old_matches(keep: int = KEEP_MATCHES) -> None:
    ensure_matches_root()
    dirs = [p for p in MATCHES_DIR.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for old in dirs[max(0, int(keep)) :]:
        try:
            for child in old.iterdir():
                child.unlink(missing_ok=True)
            old.rmdir()
        except Exception:
            pass


def start_match(note: Optional[str] = None, match_id: Optional[str] = None) -> dict:
    """Begin a new match folder (「开始新一局」or shell start)."""
    global _match_id, _seq, _accepting
    with _lock:
        ensure_matches_root()
        if match_id:
            mid = match_id
        else:
            base = datetime.now().strftime("m%Y%m%d-%H%M%S")
            mid = base
            n = 2
            while _match_dir(mid).exists():
                mid = f"{base}-{n}"
                n += 1
        _match_id = mid
        _seq = 0
        _accepting = True
        _write_meta(mid, started_at=_stamp(), ended_at=None, note=note or "")
        (_match_dir(mid) / "events.jsonl").touch(exist_ok=True)
        _remember_current(mid)
        prune_old_matches()
        return match_paths(mid)


def ensure_match() -> Optional[str]:
    """Return active match id, or None when idle after 结束一局.

    Does **not** auto-create a folder after an explicit end — user must
    「开始新一局」. Cold shell still calls start_match in after_start.
    """
    with _lock:
        if _accepting and _match_id:
            return _match_id
        return None


def is_accepting() -> bool:
    with _lock:
        return bool(_accepting and _match_id)


def end_match(note: Optional[str] = None) -> dict:
    """Finalize meta.ended_at; stop appends (keep folder)."""
    global _match_id, _accepting
    with _lock:
        mid = _match_id
        if not mid:
            _accepting = False
            return {"ok": False, "error": "no active match", "active": False}
        patch: dict[str, Any] = {"ended_at": _stamp()}
        if note is not None:
            patch["note"] = note
        _write_meta(mid, **patch)
        paths = match_paths(mid)
        _match_id = None
        _accepting = False
        paths["active"] = False
        return {"ok": True, **paths}


def _shop_rows(data: dict) -> list:
    shop = data.get("shop")
    st = data.get("state") if isinstance(data.get("state"), dict) else {}
    if not isinstance(shop, list):
        shop = st.get("shop") or []
    rows = []
    for i, c in enumerate(shop or []):
        if not isinstance(c, dict):
            continue
        cost = c.get("price")
        if cost is None:
            cost = c.get("cost")
        try:
            cost_i = int(cost) if cost is not None and str(cost).isdigit() else cost
        except Exception:
            cost_i = cost
        rows.append(
            {
                "slot": i,
                "name": c.get("name") or c.get("target"),
                "cost": cost_i,
                "star": c.get("star") or c.get("tier"),
                "kind": c.get("kind"),
            }
        )
    return rows


def _board_rows(data: dict) -> list:
    board = data.get("board")
    st = data.get("state") if isinstance(data.get("state"), dict) else {}
    if not isinstance(board, list):
        board = st.get("board") or []
    rows = []
    for u in board or []:
        if not isinstance(u, dict):
            continue
        rows.append(
            {
                "name": u.get("name"),
                "count": u.get("count"),
                "elite": u.get("elite"),
                "tier": u.get("tier") or u.get("star"),
            }
        )
    return rows


def _advice_block(data: dict) -> dict:
    tp = data.get("top_pick") if isinstance(data.get("top_pick"), dict) else None
    ranked = []
    for r in (data.get("recommendations") or [])[:8]:
        if not isinstance(r, dict):
            continue
        ranked.append(
            {
                "kind": r.get("verb") or r.get("kind"),
                "name": r.get("target") or r.get("name"),
                "score": r.get("score"),
                "affordable": r.get("affordable"),
                "shell_demoted": r.get("shell_demoted"),
                "reason": (r.get("reason") or "")[:160],
            }
        )
    top = None
    if tp:
        top = {
            "kind": tp.get("verb") or tp.get("kind") or "none",
            "name": tp.get("target") or tp.get("name"),
            "slot": tp.get("slot"),
            "score": tp.get("score"),
            "affordable": tp.get("affordable"),
        }
    else:
        top = {"kind": "none", "name": None, "slot": None, "score": None}
    reason = ""
    if tp and tp.get("reason"):
        reason = str(tp["reason"])[:200]
    elif ranked:
        reason = str(ranked[0].get("reason") or "")[:200]
    return {
        "top_pick": top,
        "ranked": ranked,
        "team_gaps": list(data.get("team_gaps") or []),
        "reason_short": reason,
        "shell_filter": data.get("shell_filter"),
    }


def _ocr_block(data: dict) -> dict:
    st = data.get("state") if isinstance(data.get("state"), dict) else {}
    res = data.get("resources") if isinstance(data.get("resources"), dict) else {}
    panel = data.get("enemy_panel") if isinstance(data.get("enemy_panel"), dict) else {}
    env = {}
    try:
        env_full = run_env_mod.load_run_env()
        env = {
            "enemy_types": list(env_full.get("enemy_types") or []),
            "enemy_wave_names": list(env_full.get("enemy_wave_names") or []),
            "target_bond": env_full.get("target_bond"),
            "banned_operators": list(env_full.get("banned_operators") or [])[:12],
        }
    except Exception:
        env = {}
    gold = res.get("gold")
    if gold is None:
        gold = st.get("gold")
    level = res.get("dispatch_level")
    if level is None:
        level = st.get("dispatch_level")
    enemy_types = list(st.get("enemy_types") or env.get("enemy_types") or [])
    enemy_names = list(
        panel.get("names")
        or st.get("enemy_names")
        or env.get("enemy_wave_names")
        or []
    )
    equipment = data.get("equipment")
    if not isinstance(equipment, dict):
        equipment = st.get("equipment") if isinstance(st.get("equipment"), dict) else {}
    return {
        "gold": gold,
        "dispatch_level": level,
        "round": res.get("round") if res.get("round") is not None else st.get("round"),
        "shop": _shop_rows(data),
        "board": _board_rows(data),
        "equipment": dict(equipment or {}),
        "board_source": data.get("board_source") or st.get("board_source"),
        "board_warnings": list(data.get("board_warnings") or []),
        "enemy_names": enemy_names,
        "enemy_types": enemy_types,
        "run_env": env,
        "gold_status": res.get("gold_status"),
    }


def _timing_block(envelope: dict) -> dict:
    t = envelope.get("timing") if isinstance(envelope.get("timing"), dict) else {}
    shell = t.get("shell") if isinstance(t.get("shell"), dict) else {}
    side = t.get("sidecar") if isinstance(t.get("sidecar"), dict) else {}
    if not side and isinstance(envelope.get("result"), dict):
        side = envelope["result"].get("timing") or {}
    return {
        "capture": shell.get("capture_ms"),
        "sidecar": shell.get("sidecar_ms") or side.get("vision_ms"),
        "total": shell.get("total_ms") or envelope.get("latency_ms"),
        "advise": side.get("advise_ms"),
        "shop": side.get("shop_ms"),
        "board": side.get("board_ms"),
    }


def append_advise_event(
    envelope: dict,
    *,
    trigger: str = "manual",
) -> Optional[Path]:
    """Append one OCR→advise cycle (or error line). Never raises to caller."""
    global _seq
    try:
        mid = ensure_match()
        trig = str(trigger or "manual")
        if trig == "hotkey":
            trig = "manual"
        with _lock:
            _seq += 1
            seq = _seq
            events_path = _match_dir(mid) / "events.jsonl"
            if not envelope or not envelope.get("ok"):
                line = {
                    "ts": _stamp(),
                    "seq": seq,
                    "trigger": trig,
                    "error": (envelope or {}).get("error") or "advise failed",
                }
            else:
                data = envelope.get("result") if isinstance(envelope.get("result"), dict) else envelope
                # Detect gold0 battle mode for trigger tag.
                sf = data.get("shell_filter") if isinstance(data.get("shell_filter"), dict) else {}
                if sf.get("mode") == "gold_zero_battle" and trig in ("manual", "auto"):
                    trig = "gold_zero"
                line = {
                    "ts": _stamp(),
                    "seq": seq,
                    "trigger": trig,
                    "ocr": _ocr_block(data),
                    "advice": _advice_block(data),
                    "timing_ms": _timing_block(envelope),
                }
            with open(events_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
            _write_meta(mid, last_seq=seq, last_ts=line["ts"], last_trigger=trig)
            _remember_current(mid)
            return events_path
    except Exception:
        return None
