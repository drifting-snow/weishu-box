# -*- coding: utf-8 -*-
"""ROI calibration helper.

Usage:
  python tools/calibrate.py <screenshot.png>

Opens the screenshot in the default viewer and prints instructions. Because
drawing an interactive overlay needs a GUI toolkit (not a required dependency),
this tool supports two modes:

  1. Manual mode (default, zero dependency):
     you read pixel boxes from any image editor and pass them as arguments,
     or edit assets/roi/config.json directly using the written skeleton.

  2. Template harvesting:
     python tools/calibrate.py <screenshot.png> --crop <l,t,r,b> --name <op|item>/<名字>
     saves the cropped icon into assets/templates/<op|item>/<名字>.png

All coordinates are absolute pixels in the screenshot at the resolution you
actually play at. Keep UI scale fixed between calibration and runtime.
"""
import os
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROI_CFG = os.path.join(ROOT, "assets", "roi", "config.json")

SKELETON = {
    "resolution": [1920, 1080],
    "ui_scale": 1.0,
    "gold": [0, 0, 100, 40],
    "dispatch_level": [0, 0, 60, 40],
    "round": [0, 0, 60, 40],
    "shop_slots": [
        [100, 900, 220, 1020],
        [240, 900, 360, 1020],
        [380, 900, 500, 1020],
        [520, 900, 640, 1020],
        [660, 900, 780, 1020],
    ],
    "note": "Replace every box with real coordinates from your screenshot.",
}


def ensure_config():
    os.makedirs(os.path.dirname(ROI_CFG), exist_ok=True)
    if not os.path.exists(ROI_CFG):
        json.dump(SKELETON, open(ROI_CFG, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print("wrote skeleton:", ROI_CFG)
    else:
        print("config exists:", ROI_CFG)


def crop_template(image_path, box, name):
    from PIL import Image
    kind, _, label = name.partition("/")
    if kind not in ("op", "item") or not label:
        raise SystemExit("--name must look like op/史尔特尔 or item/坚守盾牌")
    out_dir = os.path.join(ROOT, "assets", "templates", kind)
    os.makedirs(out_dir, exist_ok=True)
    img = Image.open(image_path).convert("RGB")
    crop = img.crop(tuple(box))
    out = os.path.join(out_dir, label + ".png")
    crop.save(out)
    print("saved template:", out, crop.size)


def main(argv):
    if not argv:
        print(__doc__)
        ensure_config()
        return
    image = argv[0]
    if "--crop" in argv:
        i = argv.index("--crop")
        box = [int(x) for x in argv[i + 1].split(",")]
        name = argv[argv.index("--name") + 1]
        crop_template(image, box, name)
    else:
        ensure_config()
        print("Open", image, "in an image editor, read each box as left,top,right,bottom")
        print("then update", ROI_CFG)
        print("Harvest an icon template with: --crop l,t,r,b --name op/名字")


if __name__ == "__main__":
    main(sys.argv[1:])
