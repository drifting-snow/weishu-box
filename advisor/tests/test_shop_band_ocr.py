# -*- coding: utf-8 -*-
"""Pure-logic tests for the shop-band OCR recognizer.

These exercise ``band_boxes_to_cards`` with synthetic OCR boxes (coordinates
modelled on the real 2560x1440 prep screenshot), so the matching / pricing /
ordering logic is covered WITHOUT requiring rapidocr or PIL. The OCR model
itself is validated separately by the manual smoke script.
"""
import unittest

from advisor.data import Dataset
from vision.shop_band_ocr import band_boxes_to_cards, NAME_STRIP_TOP

W, H = 2560, 1440


def box(text, x0, fy0, score=0.95):
    """Build a synthetic OCR box; y given as a fraction like the real layout."""
    return {
        "text": text, "score": score,
        "x0": x0, "x1": x0 + 80,
        "y0": int(fy0 * H), "y1": int((fy0 + 0.03) * H),
    }


class ShopBandCardTest(unittest.TestCase):
    def setUp(self):
        self.ds = Dataset()

    def _cards(self, boxes):
        return band_boxes_to_cards(boxes, self.ds, (W, H))

    def test_real_layout_recognizes_four_cards_in_order(self):
        # Name strip ~= fy0 0.924; UI words (upgrade/collapse/class label)
        # sit higher and/or are absent from the operator/item dictionary.
        boxes = [
            box("升级", 735, 0.897),          # upgrade tile, must be dropped
            box("坚守盾牌", 977, 0.925),       # item
            box("奥术", 1236, 0.892),          # class/bond label, dropped
            box("卡达", 1302, 0.924),
            box("深靛", 1625, 0.924),
            box("陨星", 1948, 0.924),
            box("收起", 2334, 0.898),          # collapse button, dropped
        ]
        cards = self._cards(boxes)
        names = [c.name for c in cards]
        self.assertEqual(names, ["坚守盾牌", "卡达", "深靛", "陨星"])

    def test_kinds_bonds_and_dataset_derived_prices(self):
        cards = self._cards([
            box("坚守盾牌", 977, 0.925),
            box("卡达", 1302, 0.924),
        ])
        by_name = {c.name: c for c in cards}
        shield = by_name["坚守盾牌"]
        self.assertEqual(shield.kind, "item")
        self.assertEqual(shield.bond, "坚守")
        self.assertEqual(shield.price, 1)          # item's own price field

        kada = by_name["卡达"]
        self.assertEqual(kada.kind, "operator")
        self.assertEqual(kada.tier, 1)
        self.assertEqual(kada.bond, "奥术")
        self.assertEqual(kada.price, 2)            # tier-1 economy table price

    def test_ui_words_outside_name_strip_are_ignored(self):
        cards = self._cards([
            box("升级", 735, 0.897),
            box("刷新", 2394, 0.62),
            box("卡达", 1302, 0.924),
        ])
        self.assertEqual([c.name for c in cards], ["卡达"])

    def test_unknown_text_below_strip_still_filtered_by_dictionary(self):
        # A gibberish detection inside the name strip must not snap to anything.
        cards = self._cards([box("xyz乱码", 1300, 0.924),
                             box("陨星", 1948, 0.924)])
        self.assertEqual([c.name for c in cards], ["陨星"])

    def test_duplicate_name_is_deduped_keeping_one_card(self):
        cards = self._cards([
            box("卡达", 1302, 0.924),
            box("卡达", 1310, 0.925),   # OCR split / duplicate box
        ])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].name, "卡达")

    def test_dynamic_slot_count_supported(self):
        # Fewer cards (low dispatch level) must not assume a fixed slot count.
        cards = self._cards([box("深靛", 1625, 0.924)])
        self.assertEqual(len(cards), 1)
        # And a denser board simply yields more ordered cards.
        many = self._cards([
            box("坚守盾牌", 977, 0.925), box("卡达", 1302, 0.924),
            box("深靛", 1625, 0.924), box("陨星", 1948, 0.924),
        ])
        self.assertEqual(len(many), 4)
        # name strip starts around fy 0.90, below the class labels (~0.89)
        self.assertGreaterEqual(NAME_STRIP_TOP, 0.9)


if __name__ == "__main__":
    unittest.main()
