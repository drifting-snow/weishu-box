# -*- coding: utf-8 -*-
"""Parse RapidOCR detections from opening screens → run_env fields.

Covers:
  * 规程难度选择（开始模拟 / 认证获取效率）
  * 合约/策略/自选（1/3·2/3·3/3）

Pure parse + optional cyan-glow selection filter for 核心/附加盟约 icons.
Coordinates are normalized 0..1 (cx, cy) relative to the OCR image.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable, List, Optional, Sequence, Tuple

# Sidecar runs with cwd=weishu-advisor so vision.* resolves. Overlay never imports
# this module for OCR — only the worker does.
try:
    from vision.match_text import match_one as _match_one
except Exception:  # pragma: no cover
    def _match_one(text: str, dictionary: List[str], **kwargs):  # type: ignore
        t = (text or "").strip()
        return t if t in dictionary else None


ENEMY_LABEL_RE = re.compile(r"特训敌人[·・･.]?\s*(\S+)")
# Allow OCR glue like 「4规程等级15」 / 「规程等级 13」.
PROCEDURE_RE = re.compile(r"规程等级\s*([0-9]{1,2})")
LEADER_RE = re.compile(r"假想敌[：:]\s*(\S+)")
# Difficulty select BEFORE 1/3 contract — both may show 「规程等级N」.
PHASE_MARKERS = (
    (
        "difficulty_select",
        ("开始模拟", "请选择模拟难度", "认证获取效率", "模拟强度"),
    ),
    ("contract", ("1/3", "确认本局信息")),
    ("strategy", ("2/3", "选择策略")),
    ("draft", ("3/3", "确定自选", "自选编队")),
)
# Bottom summary bar on difficulty-select (normalized cy).
DIFFICULTY_BAR_CY = 0.72
# Top-left in-match / contract badge band.
PROTOCOL_BADGE_CY_MAX = 0.12
PROTOCOL_BADGE_CX_MAX = 0.35

# OCR often reads 胄 as 胃
_LEADER_FIX = {"胃": "胄", "冑": "胄"}

# Selected covenant icons glow teal/cyan; greyed icons stay near-neutral.
# Measured on 2560×1440 1/3 screen: selected cyan≈140–190, grey≈2–16 at dy≈60px.
CYAN_SELECT_THRESHOLD = 45.0
ICON_DY_FRACS = (0.035, 0.045, 0.055, 0.065, 0.075)  # fraction of image height above label


def _norm_boxes(raw: Sequence[dict], img_w: float, img_h: float) -> List[dict]:
    out = []
    for b in raw or []:
        text = str(b.get("text") or "").strip()
        if not text:
            continue
        x0 = float(b.get("x0") or 0)
        x1 = float(b.get("x1") or 0)
        y0 = float(b.get("y0") or 0)
        y1 = float(b.get("y1") or 0)
        # Already normalized?
        if 0 <= x0 <= 1.5 and 0 <= x1 <= 1.5 and img_w > 2:
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
        else:
            cx = ((x0 + x1) / 2.0) / max(img_w, 1.0)
            cy = ((y0 + y1) / 2.0) / max(img_h, 1.0)
        out.append(
            {
                "text": text,
                "cx": cx,
                "cy": cy,
                "score": float(b.get("score") or 0),
            }
        )
    return out


def detect_screen(texts: Iterable[str]) -> Optional[str]:
    blob = " ".join(texts)
    blob_ns = blob.replace(" ", "")
    for name, markers in PHASE_MARKERS:
        if any(m.replace(" ", "") in blob_ns for m in markers):
            return name
    if "选择策略" in blob or "泛用型策略" in blob:
        return "strategy"
    if "本局禁用" in blob or "自选" in blob:
        return "draft"
    if "核心盟约" in blob or "特训敌人" in blob:
        return "contract"
    return None


def _parse_procedure_hits(
    boxes: Sequence[dict],
) -> List[Tuple[int, float, float, float]]:
    """Return (level, cx, cy, score) for every 规程等级N OCR hit."""
    hits: List[Tuple[int, float, float, float]] = []
    for b in boxes:
        t = str(b.get("text") or "")
        m = PROCEDURE_RE.search(t)
        if not m:
            continue
        try:
            lv = int(m.group(1))
        except ValueError:
            continue
        if not (1 <= lv <= 20):
            continue
        hits.append(
            (
                lv,
                float(b.get("cx") or 0),
                float(b.get("cy") or 0),
                float(b.get("score") or 0),
            )
        )
    return hits


def pick_procedure_level(
    boxes: Sequence[dict],
    screen: Optional[str] = None,
) -> Optional[int]:
    """Choose the selected 规程等级 when multiple list rows are visible.

    Difficulty-select shows every unlocked row (11/12/13/…) plus the bottom
    summary bar. Prefer the bottom bar; else the level that appears most often
    (selected row + bar); else highest-score single hit.
    """
    hits = _parse_procedure_hits(boxes)
    if not hits:
        return None
    if screen == "difficulty_select":
        bottom = [h for h in hits if h[2] >= DIFFICULTY_BAR_CY]
        if bottom:
            bottom.sort(key=lambda h: (h[1], -h[3]))  # leftmost, then score
            return bottom[0][0]
        counts = Counter(h[0] for h in hits)
        best_n, best_c = counts.most_common(1)[0]
        if best_c >= 2:
            return best_n
        hits_sorted = sorted(hits, key=lambda h: (-h[3], h[2]))
        return hits_sorted[0][0]
    # Contract / in-match badge: prefer top-left; else best score.
    badge = [
        h
        for h in hits
        if h[1] <= PROTOCOL_BADGE_CX_MAX and h[2] <= PROTOCOL_BADGE_CY_MAX
    ]
    pool = badge or hits
    pool = sorted(pool, key=lambda h: (-h[3], h[1], h[2]))
    return pool[0][0]


def is_difficulty_select_texts(texts: Iterable[str]) -> bool:
    return detect_screen(list(texts)) == "difficulty_select"


def _enemy_name_to_key(cn: str, enemy_types: dict) -> Optional[str]:
    cn = (cn or "").strip()
    if not cn:
        return None
    for key, meta in (enemy_types or {}).items():
        if key.startswith("_"):
            continue
        name = (meta or {}).get("name") if isinstance(meta, dict) else None
        if name == cn or key == cn:
            return key
    for key, meta in (enemy_types or {}).items():
        if key.startswith("_"):
            continue
        name = (meta or {}).get("name") if isinstance(meta, dict) else ""
        if name and (name in cn or cn in name):
            return key
    return None


def cyan_score_above_label(
    img: Any,
    cx: float,
    cy: float,
    *,
    patch_frac: float = 0.01,
) -> float:
    """Max teal/cyan score of patches above a label (normalized cx,cy on this img)."""
    try:
        import numpy as np
    except Exception:
        return 0.0
    arr = np.asarray(img.convert("RGB"))
    h, w = arr.shape[0], arr.shape[1]
    fx = int(cx * w)
    fy_text = int(cy * h)
    half = max(6, int(patch_frac * min(w, h)))
    best = 0.0
    for frac in ICON_DY_FRACS:
        fy = max(0, fy_text - int(frac * h))
        y0, y1 = max(0, fy - half), min(h, fy + half)
        x0, x1 = max(0, fx - half), min(w, fx + half)
        patch = arr[y0:y1, x0:x1]
        if patch.size == 0:
            continue
        r = float(patch[:, :, 0].mean())
        g = float(patch[:, :, 1].mean())
        b = float(patch[:, :, 2].mean())
        cyan = (g + b) / 2.0 - r
        if cyan > best:
            best = cyan
    return best


def is_icon_selected(img: Any, cx: float, cy: float, threshold: float = CYAN_SELECT_THRESHOLD) -> bool:
    return cyan_score_above_label(img, cx, cy) >= threshold


def parse_opening_detections(
    raw: Sequence[dict],
    *,
    img_w: float,
    img_h: float,
    bond_names: Sequence[str],
    operator_names: Sequence[str],
    enemy_types_meta: Optional[dict] = None,
    image: Any = None,
) -> dict:
    """Return a partial run_env dict (no file I/O).

    If ``image`` is a PIL image matching ``img_w``×``img_h`` (the OCR canvas),
    core/splash bonds are filtered to cyan-glow (selected) icons.
    """
    boxes = _norm_boxes(raw, img_w, img_h)
    texts = [b["text"] for b in boxes]
    screen = detect_screen(texts)
    warnings: list[str] = []
    if not screen:
        warnings.append("未识别开局相位（1/3|2/3|3/3），仍尝试抽字段")

    procedure_level = pick_procedure_level(boxes, screen)
    enemy_labels_raw: list[str] = []
    enemy_type_keys: list[str] = []
    enemy_leader_raw = None
    strategy_raw: list[str] = []
    core_hits: List[Tuple[str, float, float, float]] = []  # name, cx, cy, cyan
    splash_hits: List[Tuple[str, float, float, float]] = []
    banned_operators: list[str] = []

    et_meta = enemy_types_meta or {}
    if "enemy_types" in et_meta and isinstance(et_meta["enemy_types"], dict):
        et_meta = et_meta["enemy_types"]

    bonds = list(bond_names)
    ops = list(operator_names)

    core_hdr_cy = None
    splash_hdr_cy = None
    ban_boxes = []
    for b in boxes:
        t = b["text"]
        if "核心盟约" in t:
            core_hdr_cy = b["cy"]
        if "附加盟约" in t:
            splash_hdr_cy = b["cy"]
        if "本局禁用" in t:
            ban_boxes.append(b)

        for em in ENEMY_LABEL_RE.finditer(t):
            label = em.group(1).strip()
            label = re.split(r"[，,。\s]", label)[0]
            if label and label not in enemy_labels_raw:
                enemy_labels_raw.append(label)
            key = _enemy_name_to_key(label, et_meta)
            if key and key not in enemy_type_keys:
                enemy_type_keys.append(key)
            elif label and not key:
                warnings.append(f"未知特训标签：{label}")

        lm = LEADER_RE.search(t)
        if lm:
            leader = lm.group(1)
            for a, bfix in _LEADER_FIX.items():
                leader = leader.replace(a, bfix)
            leader = re.sub(r"[，,。.\s]+$", "", leader)
            enemy_leader_raw = leader

        if "策略" in t and t not in ("2/3选择策略", "请选择策略", "选择策略"):
            if "型策略" in t or t.endswith("策略"):
                if t not in strategy_raw and "选择" not in t and "2/3" not in t:
                    strategy_raw.append(t)

    # Bond snap by region (contract screen)
    if screen in (None, "contract"):
        y_core_lo = (core_hdr_cy + 0.04) if core_hdr_cy is not None else 0.30
        y_core_hi = (splash_hdr_cy - 0.02) if splash_hdr_cy is not None else 0.70
        y_splash_lo = (splash_hdr_cy + 0.02) if splash_hdr_cy is not None else 0.70
        y_splash_hi = 0.98
        seen_core: set[str] = set()
        seen_splash: set[str] = set()
        for b in boxes:
            t = b["text"]
            if len(t) > 8 or t.isdigit():
                continue
            if b["cx"] > 0.78:  # right info panel
                continue
            hit = _match_one(t, bonds)
            if not hit:
                continue
            cy = b["cy"]
            cyan = 0.0
            if image is not None:
                cyan = cyan_score_above_label(image, b["cx"], b["cy"])
            if y_core_lo <= cy <= y_core_hi:
                if hit not in seen_core:
                    seen_core.add(hit)
                    core_hits.append((hit, b["cx"], b["cy"], cyan))
            elif y_splash_lo <= cy <= y_splash_hi:
                if hit not in seen_splash:
                    seen_splash.add(hit)
                    splash_hits.append((hit, b["cx"], b["cy"], cyan))

    core_bonds_seen = [h[0] for h in core_hits]
    splash_bonds_seen = [h[0] for h in splash_hits]

    if image is not None and (core_hits or splash_hits):
        core_bonds = [n for n, _x, _y, c in core_hits if c >= CYAN_SELECT_THRESHOLD]
        splash_bonds = [n for n, _x, _y, c in splash_hits if c >= CYAN_SELECT_THRESHOLD]
        if core_hits and not core_bonds:
            warnings.append("核心盟约未见青色高亮，未锁定已选")
        if splash_hits and not splash_bonds:
            warnings.append("附加盟约未见青色高亮，未锁定已选")
    else:
        # No image → cannot tell selected vs grey; keep seen lists only
        core_bonds = []
        splash_bonds = []
        if core_bonds_seen:
            warnings.append(
                f"核心盟约可见{len(core_bonds_seen)}个但无像素选中检测；请手填目标羁绊"
            )
        if splash_bonds_seen:
            warnings.append(
                f"附加盟约可见{len(splash_bonds_seen)}个但无像素选中检测"
            )

    # Strategy screen: capture 泛用型策略 etc.
    if screen == "strategy":
        for b in boxes:
            t = b["text"]
            if "策略" in t and "选择" not in t and "2/3" not in t and "请" not in t:
                if t not in strategy_raw:
                    strategy_raw.append(t)

    def _looks_like_op_name(t: str) -> bool:
        t = (t or "").strip()
        if not t or t.isdigit() or len(t) < 2 or len(t) > 8:
            return False
        skip = (
            "本局禁用", "自选", "编队", "准备", "盟约", "策略", "规程",
            "特训", "假想", "确认", "信息", "完整", "模拟", "阵容",
        )
        if any(s in t for s in skip):
            return False
        cjk = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
        return cjk >= max(2, len(t) - 1)

    if screen in (None, "draft") and (ban_boxes or "本局禁用" in "".join(texts)):
        ban_cys = [b["cy"] for b in ban_boxes] or [0.4, 0.8]
        candidates: list[str] = []
        for b in boxes:
            t = b["text"]
            if "本局禁用" in t:
                continue
            near = any(abs(b["cy"] - by) < 0.14 for by in ban_cys)
            right = b["cx"] >= 0.55
            if not (near and right):
                continue
            hit = _match_one(t, ops) if ops else None
            if hit:
                candidates.append(hit)
            elif _looks_like_op_name(t):
                candidates.append(t)
        if len(candidates) < 2 and ban_boxes:
            for b in boxes:
                if b["cx"] < 0.72:
                    continue
                if not any(abs(b["cy"] - by) < 0.16 for by in ban_cys):
                    continue
                hit = _match_one(b["text"], ops) if ops else None
                name = hit or (b["text"].strip() if _looks_like_op_name(b["text"]) else None)
                if name:
                    candidates.append(name)
        for name in candidates:
            if name not in banned_operators:
                banned_operators.append(name)

    if enemy_leader_raw:
        for a, bfix in _LEADER_FIX.items():
            enemy_leader_raw = enemy_leader_raw.replace(a, bfix)

    # Multi-core selection is normal — do not invent a single target.
    target_bond = core_bonds[0] if len(core_bonds) == 1 else None

    return {
        "screen": screen,
        "difficulty": "standard",
        "procedure_level": procedure_level,
        "core_bonds": core_bonds,
        "splash_bonds": splash_bonds,
        "core_bonds_seen": core_bonds_seen,
        "splash_bonds_seen": splash_bonds_seen,
        "core_cyan": {n: round(c, 1) for n, _x, _y, c in core_hits},
        "splash_cyan": {n: round(c, 1) for n, _x, _y, c in splash_hits},
        "target_bond": target_bond,
        "enemy_types": enemy_type_keys,
        "enemy_labels_raw": [f"特训敌人·{x}" for x in enemy_labels_raw],
        "enemy_leader_raw": enemy_leader_raw,
        "strategy_raw": strategy_raw,
        "banned_operators": banned_operators,
        "banned_bonds": [],
        "draft_picks": [],
        "warnings": warnings,
        "raw_texts": texts[:60],
    }
