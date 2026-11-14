# -*- coding: utf-8 -*-
"""Visual calibration using shell.shop_layout fractions."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw

from shell.shop_layout import (
    BAND_FRAC,
    UPGRADE_FRAC,
    CARD_FRACS_REF,
    FREEZE_FRAC,
    REFRESH_FRAC,
)

SRC = Path(os.environ.get("WEISHU_SHOT", "shots/prepare.png"))
OUT = Path(os.environ.get("WEISHU_OUT", "tmp/weishu-slot-calib.png"))
OUT_BAND = Path(os.environ.get("WEISHU_OUT_BAND", "tmp/weishu-slot-calib-band.png"))


def main():
    im = Image.open(SRC)
    w, h = im.size
    vis = im.copy()
    d = ImageDraw.Draw(vis)

    def box(frac, color, label, width=4):
        x, y, ww, hh = frac
        l, t = x * w, y * h
        r, b = (x + ww) * w, (y + hh) * h
        d.rectangle([l, t, r, b], outline=color, width=width)
        d.text((l + 6, t + 6), label, fill=color)

    box(BAND_FRAC, (255, 255, 255), "band", 2)
    box(UPGRADE_FRAC, (0, 255, 120), "upgrade")
    for i, c in enumerate(CARD_FRACS_REF):
        box(c, (80, 180, 255), f"card{i}")
    box(FREEZE_FRAC, (120, 220, 255), "freeze")
    box(REFRESH_FRAC, (255, 180, 80), "refresh")
    vis.resize((1280, 720)).save(OUT)
    by0 = int(0.58 * h)
    band = vis.crop((0, by0, w, h)).resize((1280, int(1280 * (h - by0) / w)))
    band.save(OUT_BAND)
    print("wrote", OUT)
    print("wrote", OUT_BAND)


if __name__ == "__main__":
    main()
