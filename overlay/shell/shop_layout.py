# -*- coding: utf-8 -*-
"""Shop-band decision highlight layout (fractions of full client / primary).

Slot rule (user): base 4 shop cards; +1 at dispatch Lv2; +1 at Lv4
  → Lv1: 4 | Lv2–3: 5 | Lv4+: 6

Calibrated on 2560×1440:
  Lv1 / 4 cards (准备界面.png): LEVEL cx≈0.303; names 0.408/0.523/0.649/0.775
  Lv2 / 5 cards: LEVEL cx≈0.176 (kernel resource_ocr 451/2560)
  Lv4 / 6 cards (live LEVEL IV): LEVEL cx≈0.049
  冻结/刷新 text centers ≈0.831 / 0.952; 准备就绪 ≈(0.937, 0.158)
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

BAND_FRAC = (0.0, 0.68, 1.0, 0.32)

CARD_W = 0.112
CARD_Y = 0.700
CARD_H = 0.275

UPGRADE_W = 0.095
UPGRADE_Y = CARD_Y
UPGRADE_H = CARD_H

# OCR name centers at Lv1 / 4 shop cards
CARD_NAME_CX_REF4 = (0.408, 0.523, 0.649, 0.775)

# Upgrade tile centers by shop slot count
_UPGRADE_CX_BY_N = {
    4: 775 / 2560,   # ≈0.3027
    5: 451 / 2560,   # ≈0.1762
    6: 0.049,        # live LEVEL IV
}

# Freeze / refresh — round button body around OCR text
FREEZE_FRAC = (0.800, 0.610, 0.062, 0.095)
REFRESH_FRAC = (0.920, 0.610, 0.062, 0.095)

# Top-right 准备就绪 (ref OCR cx≈0.937 cy≈0.158)
READY_FRAC = (0.880, 0.115, 0.110, 0.090)

REF_WIDTH = 2560
REF_HEIGHT = 1440
BASE_SHOP_SLOTS = 4


def slots_for_dispatch_level(dispatch_level: Optional[int]) -> int:
    """Base 4; +1 at Lv2; +1 at Lv4 → 4 / 5 / 6."""
    lv = int(dispatch_level or 1)
    n = BASE_SHOP_SLOTS
    if lv >= 2:
        n += 1
    if lv >= 4:
        n += 1
    return n


def _box_from_center(cx: float, w: float, y: float, h: float) -> tuple[float, float, float, float]:
    return (max(0.0, cx - w / 2.0), y, w, h)


def _slot_count(shop: Optional[Sequence[Any]], dispatch_level: Optional[int]) -> int:
    """Geometry always follows dispatch level (OCR shop len is incomplete when empties)."""
    return slots_for_dispatch_level(dispatch_level)


def upgrade_cx_for_count(n_cards: int) -> float:
    if n_cards in _UPGRADE_CX_BY_N:
        return _UPGRADE_CX_BY_N[n_cards]
    if n_cards <= 3:
        return _UPGRADE_CX_BY_N[4] + 0.04 * (4 - max(1, n_cards))
    # beyond 6: keep drifting left from n=6
    return max(0.02, _UPGRADE_CX_BY_N[6] - 0.02 * (n_cards - 6))


def upgrade_frac_for_count(n_cards: int) -> tuple[float, float, float, float]:
    return _box_from_center(upgrade_cx_for_count(n_cards), UPGRADE_W, UPGRADE_Y, UPGRADE_H)


def card_fracs_for_count(n: int) -> list[tuple[float, float, float, float]]:
    """L→R card boxes; packed right of the (possibly drifted) upgrade tile."""
    if n <= 0:
        return []
    if n == 4:
        return [
            _box_from_center(cx, CARD_W, CARD_Y, CARD_H) for cx in CARD_NAME_CX_REF4
        ]

    up = upgrade_frac_for_count(n)
    w = CARD_W if n <= 4 else max(0.095, CARD_W - 0.006 * (n - 4))
    left_cx = up[0] + up[2] + 0.014 + w / 2.0
    # last card stays left of freeze cluster
    right_cx = 0.775 if n <= 5 else 0.785
    if n == 1:
        return [_box_from_center((left_cx + right_cx) / 2.0, w, CARD_Y, CARD_H)]
    out = []
    for i in range(n):
        t = i / (n - 1)
        cx = left_cx + (right_cx - left_cx) * t
        out.append(_box_from_center(cx, w, CARD_Y, CARD_H))
    return out


def _shop_entries(shop: Optional[Sequence[Any]]) -> list[dict]:
    out = []
    if not shop:
        return out
    for c in shop:
        if isinstance(c, dict):
            out.append(c)
        else:
            out.append({"name": str(c)})
    return out


def _card_cx_frac(
    entry: dict,
    image_width: Optional[float] = None,
) -> Optional[float]:
    """Normalize shop-card OCR x to a 0..1 fraction of the *capture* width.

    Prefer ``raw.cx_frac`` (written by sidecar from this frame). Else divide
    ``raw.x0`` by this frame's ``image_width`` — never a stale hard-coded
    2560, which drifts whenever capture size ≠ REF_WIDTH.
    """
    if not isinstance(entry, dict):
        return None
    raw = entry.get("raw") if isinstance(entry.get("raw"), dict) else {}
    cx = raw.get("cx_frac")
    if cx is not None:
        try:
            v = float(cx)
            if 0.0 <= v <= 1.5:
                return v
        except (TypeError, ValueError):
            pass
    x0 = raw.get("x0")
    if x0 is None:
        return None
    try:
        x0f = float(x0)
    except (TypeError, ValueError):
        return None
    if x0f <= 1.5:
        return x0f
    w = None
    for candidate in (
        raw.get("image_width"),
        image_width,
        raw.get("capture_width"),
    ):
        if candidate is None:
            continue
        try:
            w = float(candidate)
            if w > 1:
                break
        except (TypeError, ValueError):
            w = None
    if not w or w <= 1:
        w = float(REF_WIDTH)
    return x0f / w


def _layout_index_for_target(
    target: str,
    shop: Optional[Sequence[Any]],
    fracs: list[tuple[float, float, float, float]],
    image_width: Optional[float] = None,
) -> int:
    """Map buy target → card slot index on the level-based layout."""
    entries = _shop_entries(shop)
    names = [str(e.get("name") or e.get("target") or "") for e in entries]
    n = len(fracs)
    if not target or n <= 0:
        return -1

    # Prefer absolute x from OCR when present (handles empty left slots).
    hit = -1
    for i, nm in enumerate(names):
        if nm == target:
            hit = i
            break
    if hit < 0:
        for i, nm in enumerate(names):
            if target in nm or nm in target:
                hit = i
                break
    if hit < 0:
        return -1

    entry = entries[hit]
    cx = _card_cx_frac(entry, image_width=image_width)
    if cx is not None:
        best_i, best_d = 0, 1e9
        for i, frac in enumerate(fracs):
            fcx = frac[0] + frac[2] / 2.0
            d = abs(fcx - cx)
            if d < best_d:
                best_d, best_i = d, i
        # Reject absurd snaps (e.g. stale x0 from a previous frame size).
        if best_d <= 0.12:
            return best_i

    # OCR often omits empty left slots → pad index to the right.
    if len(names) < n:
        return (n - len(names)) + hit
    if hit < n:
        return hit
    return -1


def resolve_lineup_highlight(
    names: Sequence[str],
    shop: Optional[Sequence[Any]] = None,
    dispatch_level: Optional[int] = None,
    image_width: Optional[float] = None,
) -> list[dict]:
    """Glow every shop card whose name is in ``names`` (lineup stage pick)."""
    want = {str(n).strip() for n in (names or []) if n and str(n).strip()}
    if not want:
        return []
    n = _slot_count(shop, dispatch_level)
    fracs = card_fracs_for_count(n)
    frames: list[dict] = []
    seen_idx: set[int] = set()
    for target in want:
        idx = _layout_index_for_target(
            target, shop, fracs, image_width=image_width
        )
        if idx < 0 or idx >= len(fracs) or idx in seen_idx:
            continue
        seen_idx.add(idx)
        frames.append(
            {
                "key": f"lineup_card_{idx}_n{n}",
                "label": target,
                "frac": list(fracs[idx]),
            }
        )
    return frames


def resolve_highlight(
    top_pick: Optional[dict],
    shop: Optional[Sequence[Any]] = None,
    dispatch_level: Optional[int] = None,
    image_width: Optional[float] = None,
) -> list[dict]:
    """Map top_pick → glow frames. Each: {key, label, frac:[x,y,w,h]}."""
    if not top_pick:
        return []
    verb = str(top_pick.get("verb") or "").lower().strip()
    target = str(top_pick.get("target") or "").strip()

    n = _slot_count(shop, dispatch_level)

    if verb in ("ready", "battle", "开战", "准备", "准备就绪", "deploy"):
        return [{"key": "ready", "label": "准备就绪", "frac": list(READY_FRAC)}]

    if verb in ("refresh", "刷新"):
        return [{"key": "refresh", "label": "刷新", "frac": list(REFRESH_FRAC)}]

    if verb in ("freeze", "冻结"):
        return [{"key": "freeze", "label": "冻结", "frac": list(FREEZE_FRAC)}]

    if verb in ("upgrade", "level", "升本", "升级"):
        return [{
            "key": f"upgrade_n{n}",
            "label": "升级",
            "frac": list(upgrade_frac_for_count(n)),
        }]

    if verb in ("buy", "购买", "merge"):
        fracs = card_fracs_for_count(n)
        idx = _layout_index_for_target(
            target, shop, fracs, image_width=image_width
        )
        if idx < 0 or idx >= len(fracs):
            return []
        return [{
            "key": f"card_{idx}_n{n}",
            "label": target or f"card{idx}",
            "frac": list(fracs[idx]),
        }]
    # Shell gold==0 advice: no shop glow
    if verb in ("reposition", "adjust", "位置"):
        return [{"key": "ready", "label": "准备就绪", "frac": list(READY_FRAC)}]

    return []


def frac_to_css_percent(frac: Sequence[float]) -> dict:
    x, y, w, h = frac
    return {
        "left": f"{x * 100:.3f}%",
        "top": f"{y * 100:.3f}%",
        "width": f"{w * 100:.3f}%",
        "height": f"{h * 100:.3f}%",
    }


def all_debug_fracs(n_cards: int = 4) -> dict:
    return {
        "band": BAND_FRAC,
        "upgrade": upgrade_frac_for_count(n_cards),
        "cards": card_fracs_for_count(n_cards),
        "freeze": FREEZE_FRAC,
        "refresh": REFRESH_FRAC,
        "ready": READY_FRAC,
    }
