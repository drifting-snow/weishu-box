# -*- coding: utf-8 -*-
"""Recognition pipeline: screenshot -> cropped slots -> GameState.

Coordinates live in assets/roi/config.json (calibrated per resolution/UI scale).
Icon identity comes from TemplateMatcher; numeric fields (gold/level/round)
go through an injectable OCR function so the engine never depends on one OCR
stack. Default OCR is a placeholder that returns None and asks for manual input.
"""
import json
import os

from PIL import Image
from .matcher import TemplateMatcher
from advisor.model import GameState, ShopCard, BoardUnit

ROI_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "assets", "roi", "config.json")


def load_roi(path=ROI_PATH):
    if not os.path.exists(path):
        raise SystemExit(
            "ROI config missing: %s\nRun tools/calibrate.py on a shop screenshot first."
            % path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def crop(img: Image.Image, box):
    return img.crop(tuple(box))  # box = [left, top, right, bottom]


class Recognizer:
    def __init__(self, ocr_func=None, match_threshold=0.85):
        self.roi = load_roi()
        self.op_matcher = TemplateMatcher("op")
        self.item_matcher = TemplateMatcher("item")
        self.ocr_func = ocr_func  # callable(img_crop)->str or None
        self.match_threshold = match_threshold

    def _ocr_int(self, img, key):
        if not self.ocr_func:
            return None
        try:
            txt = self.ocr_func(crop(img, self.roi[key]))
            digits = "".join(ch for ch in str(txt) if ch.isdigit())
            return int(digits) if digits else None
        except Exception:
            return None

    def parse_shop(self, img: Image.Image):
        cards = []
        slots = self.roi.get("shop_slots", [])
        for i, box in enumerate(slots):
            slot = crop(img, box)
            op_name, op_conf, _ = self.op_matcher.match(slot, self.match_threshold)
            if op_name:
                cards.append(ShopCard(kind="operator", name=op_name,
                                      raw={"confidence": round(op_conf, 3), "slot": i}))
                continue
            item_name, it_conf, _ = self.item_matcher.match(slot, self.match_threshold)
            if item_name:
                cards.append(ShopCard(kind="item", name=item_name,
                                      raw={"confidence": round(it_conf, 3), "slot": i}))
                continue
            cards.append(ShopCard(kind="unknown", name="",
                                  raw={"slot": i, "confidence": 0.0}))
        return cards

    def recognize(self, img: Image.Image, difficulty="standard",
                  target_bond=None, board=None) -> GameState:
        cards = self.parse_shop(img)
        gold = self._ocr_int(img, "gold") or 0
        level = self._ocr_int(img, "dispatch_level") or 1
        rnd = self._ocr_int(img, "round") or 1
        units = [BoardUnit(**b) for b in (board or [])]
        return GameState(
            round=rnd, gold=gold, dispatch_level=level,
            difficulty=difficulty, target_bond=target_bond,
            shop=cards, board=units,
            note="vision" if any(c.name for c in cards) else "no-icon-matched",
        )
