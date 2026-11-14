# -*- coding: utf-8 -*-
"""OCR-based shop recognizer (the primary vision path, MAA-style).

Pipeline: screenshot -> normalized-fraction ROI -> preprocess -> OCR ->
fuzzy-snap to the built-in name dictionary -> GameState.

It reuses the same ideas as the open-source MaaFramework auto-chess tools:
resolution-independent fractional boxes, digit/text preprocessing, OCR digit
correction, and difflib matching against a known name list. No icon templates
and no game-memory access; only pixels are read.
"""
from typing import List, Optional

from PIL import Image

from .roi import get_profile, to_pixel
from .preprocess import preprocess, digit_correct
from .match_text import match_one, classify_kind
from .ocr import NullOCR
from advisor.model import GameState, ShopCard, BoardUnit


class OcrShopRecognizer:
    def __init__(self, dataset, ocr_engine=None, ui_scale: str = "100%",
                 correction: Optional[dict] = None):
        self.ds = dataset
        self.ocr = ocr_engine or NullOCR()
        self.profile = get_profile(ui_scale)
        self.correction = correction
        self.op_names = {o["name"] for o in dataset.operators}
        self.item_names = {i["name"] for i in dataset.items}

    def _crop(self, img: Image.Image, frac) -> Image.Image:
        box = to_pixel(frac, img.width, img.height)
        return img.crop(box.as_tuple())

    def _read_text(self, img: Image.Image, frac, is_number: bool) -> str:
        crop = self._crop(img, frac)
        processed = preprocess(crop, is_number=is_number)
        raw = self.ocr.read(processed)
        if is_number:
            return digit_correct(raw or "")
        return (raw or "").strip()

    def recognize_shop(self, img: Image.Image) -> List[ShopCard]:
        cards: List[ShopCard] = []
        prices = self.profile["price"]
        names = self.profile["name"]
        for slot in range(len(prices)):
            price_txt = self._read_text(img, prices[slot], is_number=True)
            name_txt = self._read_text(img, names[slot], is_number=False)
            price = int(price_txt) if price_txt.isdigit() else None
            canonical = match_one(name_txt,
                                  list(self.op_names | self.item_names),
                                  self.correction)
            if canonical is None:
                cards.append(ShopCard(
                    kind="unknown", name="", price=price,
                    raw={"slot": slot, "ocr_text": name_txt}))
                continue
            kind = classify_kind(canonical, self.op_names, self.item_names)
            tier = None
            bond = None
            if kind == "operator":
                op = self.ds.operator(canonical)
                if op:
                    tier = op.get("shop_tier")
                    bond = op["bonds"][0] if op.get("bonds") else None
            else:
                it = self.ds.item(canonical)
                if it:
                    tier = it.get("tier")
                    bond = it.get("bond") or None
            cards.append(ShopCard(
                kind=kind, name=canonical, tier=tier, price=price, bond=bond,
                raw={"slot": slot, "ocr_text": name_txt}))
        return cards

    def recognize(self, img: Image.Image, difficulty: str = "standard",
                  target_bond: Optional[str] = None,
                  board: Optional[list] = None) -> GameState:
        gold_txt = self._read_text(img, self.profile["gold"], is_number=True)
        gold = int(gold_txt) if gold_txt.isdigit() else 0
        cards = self.recognize_shop(img)
        units = [BoardUnit(**b) for b in (board or [])]
        matched = sum(1 for c in cards if c.kind in ("operator", "item"))
        return GameState(
            round=1, gold=gold, dispatch_level=1,
            difficulty=difficulty, target_bond=target_bond,
            shop=cards, board=units,
            note="ocr: %d/%d slots matched" % (matched, len(cards)),
        )
