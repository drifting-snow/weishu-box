# -*- coding: utf-8 -*-
"""Shop-band OCR recognizer (calibrated on a real 2560x1440 client).

Why a second recognizer alongside ``shop_ocr.py``:
the fractional ROI table there was seeded from another project and hard-codes
6 right-to-left slots, but the live client lays out a *dynamic* number of
cards (dispatch level 1 shows an upgrade tile + 4 shop cards, left-to-right).
Instead of brittle fixed slots, this recognizer OCRs the whole bottom shop
band once and lets the built-in 141-operator / 70-item name dictionary act as
the filter: every detected text is fuzzy-snapped to a canonical name and the
UI-only words (upgrade / collapse / class labels) simply fail to match.

Card prices are NOT OCR-read (the yellow price pips are hard to recognize).
They are derived from the dataset: operators via the tier economy table plus
special 整备能力 prices, items via their own price field.

Design:
  * ``detect_band`` wraps the OCR engine and returns raw (box, text, score);
  * ``band_boxes_to_cards`` is a pure function over those boxes, so the
    matching logic is unit-testable without any OCR model installed;
  * the OCR engine is injectable and only imported lazily, keeping the
    advisor core stdlib-only.
Stdlib + local packages only at import time; rapidocr/numpy/PIL are optional.
"""
from typing import List, Optional, Tuple

from .match_text import match_one, classify_kind
from advisor.model import GameState, ShopCard, BoardUnit
from advisor import economy as econ

# Bottom band fractions, measured from the real 2560x1440 prep screenshot.
# Card name texts land around fy0 ~= 0.92; the band below covers name + price.
BAND_FRAC = (0.0, 0.68, 1.0, 1.0)  # (x, y, w, h) of the cropped OCR region
# Only detections whose TOP edge sits in this name strip are treated as card
# names. Class/bond labels sit higher (~0.89); this keeps them separate even
# before the dictionary filter runs.
NAME_STRIP_TOP = 0.90
NAME_STRIP_BOTTOM = 0.975


def _band_pixel_box(width: int, height: int):
    x, y, w, h = BAND_FRAC
    return (int(x * width), int(y * height),
            int((x + w) * width), int((y + h) * height))


class BandOCREngine:
    """Lazy RapidOCR wrapper returning coordinate-bearing detections."""

    def __init__(self):
        try:
            import numpy as np  # noqa: F401
            from rapidocr_onnxruntime import RapidOCR
        except Exception as e:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "vision extra not installed; pip install -e \".[vision]\"") from e
        self._np = np
        self._ocr = RapidOCR()

    def detect(self, img) -> List[dict]:
        import numpy as np
        result, _ = self._ocr(np.asarray(img.convert("RGB")))
        out = []
        for box, text, score in (result or []):
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            out.append({
                "text": str(text), "score": float(score),
                "x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys),
            })
        return out


def _derive_price(ds, kind: str, canonical: str) -> Optional[int]:
    """Dataset-derived price so we never depend on OCR of the price pips."""
    if kind == "operator":
        op = ds.operator(canonical)
        if op is not None:
            return econ.buy_price(ds, op)
        return None
    if kind == "item":
        it = ds.item(canonical)
        if it is not None:
            raw = it.get("price")
            try:
                return int(raw) if raw is not None else None
            except (TypeError, ValueError):
                return None
    return None


def band_boxes_to_cards(boxes: List[dict], ds,
                        image_size: Tuple[int, int],
                        correction: Optional[dict] = None) -> List[ShopCard]:
    """Pure mapping from raw OCR boxes to ordered shop cards.

    ``boxes`` items need text/x0/x1/y0/y1 (absolute pixels). Coordinates are
    normalized against ``image_size`` so the name-strip test is resolution
    independent. UI words that do not snap to a known name are dropped.
    """
    width, height = image_size
    op_names = {o["name"] for o in ds.operators}
    item_names = {i["name"] for i in ds.items}
    dictionary = list(op_names | item_names)

    candidates = []
    for b in boxes:
        fy0 = b["y0"] / height
        if not (NAME_STRIP_TOP <= fy0 <= NAME_STRIP_BOTTOM):
            continue
        canonical = match_one(b["text"], dictionary, correction)
        if canonical is None:
            continue
        kind = classify_kind(canonical, op_names, item_names)
        if kind == "unknown":
            continue
        candidates.append((b["x0"], canonical, kind, round(b.get("score", 0.0), 3)))

    # De-duplicate the same name if OCR split it, keeping the leftmost hit,
    # then order cards left-to-right as the player sees them.
    seen = {}
    for x0, name, kind, score in candidates:
        if name not in seen or x0 < seen[name][0]:
            seen[name] = (x0, kind, score)

    cards = []
    for name, (x0, kind, score) in sorted(seen.items(), key=lambda kv: kv[1][0]):
        tier = bond = None
        if kind == "operator":
            op = ds.operator(name)
            if op:
                tier = op.get("shop_tier")
                bond = op["bonds"][0] if op.get("bonds") else None
        else:
            it = ds.item(name)
            if it:
                tier = it.get("tier")
                bond = it.get("bond") or None
        cards.append(ShopCard(
            kind=kind, name=name, tier=tier,
            price=_derive_price(ds, kind, name), bond=bond,
            raw={"x0": round(x0), "confidence": score, "source": "band_ocr"},
        ))
    return cards


class ShopBandRecognizer:
    """High-level recognizer: screenshot -> GameState (shop band OCR)."""

    def __init__(self, dataset, ocr_engine=None, correction: Optional[dict] = None):
        self.ds = dataset
        self.ocr = ocr_engine  # injectable; lazily built on first use
        self.correction = correction

    def _engine(self):
        if self.ocr is None:
            self.ocr = BandOCREngine()
        return self.ocr

    def recognize_shop(self, img) -> List[ShopCard]:
        box = _band_pixel_box(img.width, img.height)
        band = img.crop(box)
        # Re-base OCR coordinates back to full-image space for the strip test.
        off_x, off_y = box[0], box[1]
        raw = self._engine().detect(band)
        for b in raw:
            b["x0"] += off_x
            b["x1"] += off_x
            b["y0"] += off_y
            b["y1"] += off_y
        return band_boxes_to_cards(raw, self.ds, (img.width, img.height),
                                   self.correction)

    def recognize(self, img, difficulty: str = "standard",
                  target_bond: Optional[str] = None,
                  board: Optional[list] = None,
                  round: int = 1, gold: int = 0,
                  dispatch_level: int = 1,
                  enemy_types: Optional[List[str]] = None,
                  enemy_names: Optional[List[str]] = None) -> GameState:
        cards = self.recognize_shop(img)
        units = [BoardUnit(**b) for b in (board or [])]
        matched = sum(1 for c in cards if c.kind in ("operator", "item"))
        return GameState(
            round=round, gold=gold, dispatch_level=dispatch_level,
            difficulty=difficulty, target_bond=target_bond,
            shop=cards, board=units,
            enemy_types=list(enemy_types or []),
            enemy_names=list(enemy_names or []),
            note="band_ocr: %d shop cards matched (round/gold/level manual)"
                 % matched,
        )
