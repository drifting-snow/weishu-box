# -*- coding: utf-8 -*-
"""Real-OCR smoke test (requires rapidocr_onnxruntime).

Renders known operator/item names and a price with a CJK font, runs the actual
RapidOCR backend plus preprocessing and dictionary matching, and prints whether
the end-to-end primary vision path works on this machine.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw, ImageFont

from advisor.data import Dataset
from vision.ocr import RapidOCREngine
from vision.preprocess import preprocess, digit_correct
from vision.match_text import match_one

# Cross-platform CJK font candidates. The smoke test is optional and only runs
# on a machine with a GUI/OCR stack, but it must not assume a Windows-only path.
FONT_CANDIDATES = [
    # Windows
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    # Linux (common distro packages)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
]


def load_font(size):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    raise SystemExit(
        "no CJK font found; install a CJK font (e.g. Noto Sans CJK) or add its "
        "path to FONT_CANDIDATES in tools/ocr_smoke.py")


def render(text, size=(260, 70), font_size=40, dark_bg=False):
    bg = (28, 28, 34) if dark_bg else (255, 255, 255)
    fg = (240, 240, 240) if dark_bg else (20, 20, 20)
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    font = load_font(font_size)
    d.text((12, 12), text, font=font, fill=fg)
    return img


def main():
    ds = Dataset()
    ocr = RapidOCREngine()
    op_names = {o["name"] for o in ds.operators}
    item_names = {i["name"] for i in ds.items}
    dictionary = list(op_names | item_names)

    # pick a few real names that exist in the dataset
    sample_ops = [n for n in ["真理", "烈夏", "史尔特尔", "阿米娅"] if n in op_names][:3]
    sample_items = [n for n in ["坚守盾牌", "盟约之币"] if n in item_names][:2]

    print("== number OCR (dark background, digit preprocessing) ==")
    num_img = render("3", size=(80, 70), font_size=44, dark_bg=True)
    raw_num = ocr.read(preprocess(num_img, is_number=True))
    print("  raw=%r -> digit=%r" % (raw_num, digit_correct(raw_num)))

    print("== name OCR + dictionary snap ==")
    ok = 0
    total = 0
    for name in sample_ops + sample_items:
        total += 1
        img = render(name, dark_bg=False)
        raw = ocr.read(preprocess(img, is_number=False))
        snapped = match_one(raw, dictionary)
        good = (snapped == name)
        ok += int(good)
        print("  target=%-6s raw=%-10r snapped=%-8r %s" %
              (name, raw, snapped, "OK" if good else "MISS"))

    print("result: %d/%d names snapped correctly" % (ok, total))
    print("NOTE: rendered-text OCR is a sanity check; real in-game ROI accuracy"
          " depends on vision/roi.py calibration from an actual screenshot.")


if __name__ == "__main__":
    main()
