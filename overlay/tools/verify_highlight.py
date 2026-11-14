# -*- coding: utf-8 -*-
"""Draw shop_layout fracs for Lv1/4, Lv2/5, Lv4/6 ROI verification."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw

from shell.shop_layout import (
    all_debug_fracs,
    resolve_highlight,
    slots_for_dispatch_level,
)

SRC = Path(os.environ.get("WEISHU_SHOT", "shots/prepare.png"))
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.environ.get("WEISHU_OUT", "tmp/weishu-highlight-verify.png"))


def main():
    im = Image.open(SRC).convert("RGBA")
    w, h = im.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    def box(frac, color, label, width=5):
        x, y, ww, hh = frac
        l, t = x * w, y * h
        r, b = (x + ww) * w, (y + hh) * h
        for i in range(3):
            d.rectangle(
                [l - i, t - i, r + i, b + i],
                outline=color,
                width=1 if i else width,
            )
        d.text((l + 8, t + 8), label, fill=color)

    layout4 = all_debug_fracs(4)
    layout5 = all_debug_fracs(5)
    layout6 = all_debug_fracs(6)

    box(layout4["band"], (255, 255, 255, 100), "band", 2)
    box(layout4["upgrade"], (0, 255, 120, 255), "up_n4")
    for i, c in enumerate(layout4["cards"]):
        box(c, (80, 180, 255, 200), f"c4_{i}", 3)
    box(layout5["upgrade"], (255, 80, 200, 220), "up_n5", 4)
    box(layout6["upgrade"], (255, 200, 80, 220), "up_n6", 4)
    box(layout4["freeze"], (120, 220, 255, 255), "freeze")
    box(layout4["refresh"], (255, 180, 80, 255), "refresh")
    box(layout4["ready"], (93, 255, 176, 255), "ready", 6)

    # Lv4 / 6-slot buy sample (empty left pads)
    shop6 = [
        {"name": "哈洛德", "raw": {"x0": 0.527 * 2560}},
        {"name": "旅骨", "raw": {"x0": 0.648 * 2560}},
        {"name": "折娅", "raw": {"x0": 0.775 * 2560}},
    ]
    hl = resolve_highlight({"verb": "buy", "target": "折娅"}, shop6, dispatch_level=4)
    for f in hl:
        box(f["frac"], (255, 230, 80, 255), "BUY " + f["label"], 7)

    print("slots", {lv: slots_for_dispatch_level(lv) for lv in range(1, 7)})
    print("hl", hl)
    print("up6", layout6["upgrade"])

    out = Image.alpha_composite(im, overlay).convert("RGB")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.resize((1280, 720)).save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
