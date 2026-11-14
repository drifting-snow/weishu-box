# -*- coding: utf-8 -*-
"""Prep-screen resource OCR (calibrated on two real 2560x1440 screenshots:
a tier-I frame prep_tier1.png and a tier-II frame concrete_ui.png).

Reads the numbers the advisor previously needed by hand:
  * round          -- top "回合 N"
  * enemy_count    -- top chess-icon N (user-confirmed: enemies this wave)
  * gold           -- bottom-right yellow diamond chip
  * upgrade_cost   -- hexagon number on the upgrade tile (cost to level up)
  * dispatch_level -- white vertical pips inside the upgrade tile (tier I/II..)

Key calibration fact: the upgrade tile's HORIZONTAL position drifts with the
number of shop cards (tier-I 4 cards -> tile center x~775; tier-II 5 cards ->
x~451 at 2560 wide), while every element's vertical position is fixed and the
hex cost + pips are horizontally centered on the tile's "LEVEL" text. So the
tile x is anchored dynamically by OCR-locating LEVEL; fixed top/gold ROIs use
resolution-independent fractions. The tier pips are Roman-style bars, not
digits, so they are counted with a column-profile (numpy) instead of OCR.

Pure helpers (parse_int / anchor_tile_center / count_tier_pips) take plain
data so they are unit-testable without an OCR model. The OCR engine is
injectable (any object with .detect(img)->list[dict]); the advisor core stays
stdlib-only and this module never presses any game key.
"""
from dataclasses import dataclass
from typing import List, Optional

# Fixed ROIs as (x, y, w, h) fractions of the full frame (from 2560x1440).
ROUND_FRAC = (935 / 2560, 22 / 1440, 80 / 2560, 56 / 1440)
ENEMY_FRAC = (1560 / 2560, 18 / 1440, 120 / 2560, 64 / 1440)
# Gold chip sits on the yellow diamond BOTTOM-RIGHT of the shop cluster.
# MUST stay below the 刷新 cost bubble (bubble cy≈0.58–0.63, digit「1」) —
# a high/wide gold ROI misreads that bubble as gold (broke→recommend refresh).
GOLD_FRAC = (2360 / 2560, 1020 / 1440, 120 / 2560, 70 / 1440)
# Refresh cost pip above 刷新 (for contamination checks / diagnostics only).
REFRESH_COST_FRAC = (2350 / 2560, 830 / 1440, 150 / 2560, 90 / 1440)
# Reject any "gold" digit whose center lies in the refresh-cost band.
GOLD_MIN_CY = 0.68

# Band OCR-scanned to locate the LEVEL anchor (covers the tile's x drift).
TILE_BAND_FRAC = (300 / 2560, 1000 / 1440, 650 / 2560, 130 / 1440)
# Hex-cost crop centered on the tile anchor (half-width + fixed y band).
HEX_HALF_W_FRAC = 55 / 2560
HEX_Y_FRAC = (1028 / 1440, 1095 / 1440)
# Tier-pip window centered on the anchor (half-width + fixed y band).
PIP_HALF_W_FRAC = 78 / 2560
PIP_Y_FRAC = (1180 / 1440, 1310 / 1440)

OCR_SCALE = 3          # small resource digits need 3x to read reliably
PIP_BRIGHT = 170       # grayscale threshold for the near-white mint pips
PIP_COL_FRAC = 0.25    # a column counts as pip body if >25% of rows are bright
PIP_MIN_WIDTH = 10     # wide bars only; thin frame lines (<10px) are ignored


@dataclass
class Resources:
    round: Optional[int] = None
    enemy_count: Optional[int] = None
    gold: Optional[int] = None
    upgrade_cost: Optional[int] = None
    dispatch_level: Optional[int] = None
    warnings: Optional[List[str]] = None

    def as_dict(self) -> dict:
        return {
            "round": self.round, "enemy_count": self.enemy_count,
            "gold": self.gold, "upgrade_cost": self.upgrade_cost,
            "dispatch_level": self.dispatch_level,
            "warnings": self.warnings or [],
        }


def _frac_box(frac, width: int, height: int):
    x, y, w, h = frac
    return (int(round(x * width)), int(round(y * height)),
            int(round((x + w) * width)), int(round((y + h) * height)))


# OCR often renders gold「0」as Latin O / fullwidth ０ / 〇.
_ZERO_LIKE = {
    "O", "o", "Ο", "ο", "О", "о", "〇", "零", "０", "ₒ", "°", "˚",
}


def _digit_part(text: str) -> str:
    """Extract digits; map lone zero-like glyphs to '0'."""
    s = str(text or "").strip()
    if not s:
        return ""
    if s in _ZERO_LIKE:
        return "0"
    # e.g. "O1" / "1O" mixed — replace zero-like then keep digits
    for z in _ZERO_LIKE:
        s = s.replace(z, "0")
    return "".join(ch for ch in s if ch.isdigit())


def parse_int(boxes: List[dict]) -> Optional[int]:
    """Concatenate digit-bearing OCR tokens left-to-right into one integer.

    Handles a single '25', a split '2'+'0', OCR 'O' as zero, and ignores
    letter noise such as 'EVEL'. Returns None when no digit token is present.
    """
    digits = []
    for b in boxes:
        part = _digit_part(str(b.get("text", "")))
        if part:
            digits.append((b.get("x0", 0), part))
    if not digits:
        return None
    digits.sort(key=lambda t: t[0])
    try:
        return int("".join(part for _x, part in digits))
    except ValueError:
        return None


def anchor_tile_center(boxes: List[dict]) -> Optional[int]:
    """Center-x of the LEVEL token in FULL-FRAME coordinates, or None.

    Boxes must already be rebased from the upscaled band crop to full-frame
    pixels by the caller (this function adds no offset itself). Matching uses a
    LEV prefix because OCR occasionally renders LEVEL as LEVEI.
    """
    for b in boxes:
        token = str(b.get("text", "")).upper().replace(" ", "")
        if token.startswith("LEV"):
            return int(round((b["x0"] + b["x1"]) / 2))
    return None


def count_tier_pips(gray_array, bright: int = PIP_BRIGHT,
                    col_frac: float = PIP_COL_FRAC,
                    min_width: int = PIP_MIN_WIDTH) -> int:
    """Count wide bright vertical bars (tier pips) in a grayscale numpy crop.

    Thin bright frame lines fail the min-width gate; each pip is a wide bar.
    Pure over the input array so it can be unit-tested with synthetic images.
    """
    import numpy as np
    arr = np.asarray(gray_array)
    height = arr.shape[0]
    on = ((arr > bright).sum(axis=0) / height) > col_frac
    widths, start = [], None
    for i, flag in enumerate(on):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            widths.append(i - start)
            start = None
    if start is not None:
        widths.append(len(on) - start)
    return sum(1 for w in widths if w >= min_width)


class ResourceRecognizer:
    """Screenshot -> Resources. OCR engine is injectable; lazy by default."""

    def __init__(self, ocr_engine=None):
        self.ocr = ocr_engine

    def _engine(self):
        if self.ocr is None:
            from .shop_band_ocr import BandOCREngine
            self.ocr = BandOCREngine()
        return self.ocr

    def _read_number(self, img, frac) -> Optional[int]:
        box = _frac_box(frac, img.width, img.height)
        crop = img.crop(box)
        big = crop.resize((crop.width * OCR_SCALE, crop.height * OCR_SCALE))
        raw = self._engine().detect(big)
        # re-base to full-frame coords (offsets cancel for parse ordering, but
        # keep absolute x0 so multi-token concatenation stays left-to-right)
        for b in raw:
            b["x0"] = box[0] + b["x0"] / OCR_SCALE
            b["x1"] = box[0] + b["x1"] / OCR_SCALE
            b["y0"] = box[1] + b.get("y0", 0) / OCR_SCALE
            b["y1"] = box[1] + b.get("y1", 0) / OCR_SCALE
        return parse_int(raw)

    def _read_gold(self, img) -> tuple[Optional[int], List[str]]:
        """Read gold chip; never accept the 刷新 cost bubble「1」as gold."""
        notes: List[str] = []
        width, height = img.width, img.height
        box = _frac_box(GOLD_FRAC, width, height)
        crop = img.crop(box)
        big = crop.resize((crop.width * OCR_SCALE, crop.height * OCR_SCALE))
        raw = self._engine().detect(big)
        for b in raw:
            b["x0"] = box[0] + b["x0"] / OCR_SCALE
            b["x1"] = box[0] + b["x1"] / OCR_SCALE
            b["y0"] = box[1] + b.get("y0", 0) / OCR_SCALE
            b["y1"] = box[1] + b.get("y1", 0) / OCR_SCALE

        # Drop any token whose center is still in the refresh-cost band
        # (defensive — GOLD_FRAC should already sit below GOLD_MIN_CY).
        kept = []
        for b in raw:
            cy = (float(b.get("y0", 0)) + float(b.get("y1", 0))) / 2.0 / height
            if cy < GOLD_MIN_CY:
                notes.append("ignored digit in refresh-cost band cy=%.3f text=%r"
                             % (cy, b.get("text")))
                continue
            kept.append(b)

        gold = parse_int(kept)

        # Contaminant check vs 刷新 cost bubble「1」.
        # Never blindly map gold=1+refresh=1 → 0 (gold=1 is a valid broke-ish
        # purse). If the only evidence for「1」is refresh-band noise, return
        # None (unknown) — callers must NOT treat unknown as battle-ready 0.
        # Only OCR the refresh pip when gold==1 — otherwise this is a wasted
        # ~1s RapidOCR pass every click with no decision impact.
        if gold != 1:
            return gold, notes
        refresh_cost = self._read_number(img, REFRESH_COST_FRAC)
        if gold == 1 and refresh_cost == 1:
            zeros = []
            ones_in_gold_roi = []
            for b in kept:
                part = _digit_part(str(b.get("text", "")))
                if part == "0":
                    zeros.append(b)
                elif part == "1":
                    ones_in_gold_roi.append(b)
            if zeros and not ones_in_gold_roi:
                gold = 0
                notes.append("gold corrected via explicit 0 in gold ROI")
            elif ones_in_gold_roi:
                # Digit「1」really sits in the gold chip ROI — trust it.
                notes.append(
                    "gold=1 kept (refresh pip also 1; gold-ROI digit confirmed)"
                )
            else:
                gold = None
                notes.append(
                    "gold ambiguous vs refresh-cost「1」; leaving unrecognized"
                )

        return gold, notes

    def read_resources(self, img, *, skip_enemy: bool = False) -> Resources:
        """Read prep-screen resources.

        ``skip_enemy``: omit the top chess-icon OCR (~0.5–0.6s). Overlay shop
        decide path does not use enemy_count; opening/env flows keep it on.
        """
        width, height = img.width, img.height
        warnings: List[str] = []

        round_no = self._read_number(img, ROUND_FRAC)
        enemy_count = None if skip_enemy else self._read_number(img, ENEMY_FRAC)
        if skip_enemy:
            warnings.append("enemy_count skipped (overlay fast path)")
        gold, gold_notes = self._read_gold(img)
        warnings.extend(gold_notes)

        # Dynamic upgrade-tile anchor via the LEVEL text.
        band_box = _frac_box(TILE_BAND_FRAC, width, height)
        band = img.crop(band_box)
        band_big = band.resize((band.width * 2, band.height * 2))
        band_raw = self._engine().detect(band_big)
        for b in band_raw:
            b["x0"] = band_box[0] + b["x0"] / 2
            b["x1"] = band_box[0] + b["x1"] / 2
        cx = anchor_tile_center(band_raw)

        upgrade_cost = dispatch_level = None
        if cx is None:
            warnings.append("未定位到升级 tile 的 LEVEL 锚点，升本费/本数缺失")
        else:
            hw = int(round(PIP_HALF_W_FRAC * width))
            hex_hw = int(round(HEX_HALF_W_FRAC * width))
            hy0 = int(round(HEX_Y_FRAC[0] * height))
            hy1 = int(round(HEX_Y_FRAC[1] * height))
            py0 = int(round(PIP_Y_FRAC[0] * height))
            py1 = int(round(PIP_Y_FRAC[1] * height))

            hexcrop = img.crop((cx - hex_hw, hy0, cx + hex_hw, hy1))
            hex_big = hexcrop.resize(
                (hexcrop.width * OCR_SCALE, hexcrop.height * OCR_SCALE))
            upgrade_cost = parse_int(self._engine().detect(hex_big))

            pipcrop = img.convert("L").crop((cx - hw, py0, cx + hw, py1))
            dispatch_level = count_tier_pips(pipcrop) or None

        for label, val in (("round", round_no), ("enemy_count", enemy_count),
                           ("gold", gold), ("upgrade_cost", upgrade_cost),
                           ("dispatch_level", dispatch_level)):
            if val is None:
                if label == "enemy_count" and skip_enemy:
                    continue
                warnings.append("%s 未识别" % label)

        return Resources(round_no, enemy_count, gold, upgrade_cost,
                         dispatch_level, warnings)
