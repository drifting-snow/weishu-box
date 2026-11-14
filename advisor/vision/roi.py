# -*- coding: utf-8 -*-
"""Normalized, resolution-independent ROI layout (MAA-style).

Every box is a fraction (x, y, w, h) of the full screenshot, so one layout
works at any resolution. Only the in-game UI scale needs a separate profile
(90% / 100%). Pixel boxes are derived at runtime from the actual image size.

Reference fractions below are seeded from an open-source MaaFramework project
(MaaAutoReverse) for a 16:9 client and MUST be re-calibrated from a real
screenshot of your own client via tools/calibrate.py.
"""
from dataclasses import dataclass
from typing import Dict, List, Tuple

# fraction boxes: (x, y, w, h)
PROFILES: Dict[str, dict] = {
    "100%": {
        # 6 shop slots, ordered right-to-left as laid out in the reference;
        # each entry pairs a price ROI and a name ROI (name list follows).
        "price": [
            (0.7927, 0.7444, 0.0120, 0.0269),
            (0.6650, 0.7444, 0.0120, 0.0269),
            (0.5373, 0.7444, 0.0120, 0.0269),
            (0.4095, 0.7444, 0.0120, 0.0269),
            (0.2818, 0.7444, 0.0120, 0.0269),
            (0.1541, 0.7444, 0.0120, 0.0269),
        ],
        "name": [
            (0.7568, 0.9500, 0.0896, 0.0296),
            (0.6289, 0.9500, 0.0896, 0.0296),
            (0.5010, 0.9500, 0.0896, 0.0296),
            (0.3730, 0.9500, 0.0896, 0.0296),
            (0.2451, 0.9500, 0.0896, 0.0296),
            (0.1172, 0.9500, 0.0896, 0.0296),
        ],
        "gold": (0.9313, 0.7204, 0.0266, 0.0370),
        "hand_area": (0.1240, 0.5824, 0.6594, 0.0889),
        "shop_display": (0.0995, 0.7435, 0.7599, 0.2444),
    },
    "90%": {
        "price": [
            (0.8141, 0.7704, 0.0100, 0.0232),
            (0.6990, 0.7704, 0.0100, 0.0232),
            (0.5839, 0.7704, 0.0100, 0.0232),
            (0.4688, 0.7704, 0.0100, 0.0232),
            (0.3537, 0.7704, 0.0100, 0.0232),
            (0.2386, 0.7704, 0.0100, 0.0232),
        ],
        "name": [
            (0.7807, 0.9556, 0.0818, 0.0250),
            (0.6656, 0.9556, 0.0818, 0.0250),
            (0.5505, 0.9556, 0.0818, 0.0250),
            (0.4354, 0.9556, 0.0818, 0.0250),
            (0.3203, 0.9556, 0.0818, 0.0250),
            (0.2052, 0.9556, 0.0818, 0.0250),
        ],
        "gold": (0.9381, 0.7481, 0.0240, 0.0342),
        "hand_area": (0.1234, 0.5907, 0.6599, 0.1102),
        "shop_display": (0.1901, 0.7685, 0.6844, 0.2204),
    },
}


@dataclass
class PixelBox:
    left: int
    top: int
    right: int
    bottom: int

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)


def to_pixel(frac: Tuple[float, float, float, float],
             width: int, height: int) -> PixelBox:
    x, y, w, h = frac
    left = int(round(x * width))
    top = int(round(y * height))
    right = int(round((x + w) * width))
    bottom = int(round((y + h) * height))
    return PixelBox(left, top, right, bottom)


def slot_count(profile: dict) -> int:
    return len(profile["price"])


def get_profile(ui_scale: str = "100%") -> dict:
    if ui_scale not in PROFILES:
        raise KeyError("unknown ui_scale %r; choose %s" %
                       (ui_scale, sorted(PROFILES)))
    return PROFILES[ui_scale]
