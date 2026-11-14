# -*- coding: utf-8 -*-
"""Offline vision pipeline test using synthetic icons (no game assets needed).

Generates a few colored template PNGs, renders a "shop slot" from one of them,
and checks the matcher identifies it. Run with the engine tests:
  python -m unittest discover -s tests -v
"""
import os
import sys
import shutil
import unittest

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vision.matcher import TemplateMatcher, ASSETS

COLORS = {
    "测试干员甲": (200, 40, 40),
    "测试干员乙": (40, 120, 220),
    "测试干员丙": (40, 180, 90),
}


def make_icon(color, size=(64, 64)):
    img = Image.new("RGB", size, color)
    # add a deterministic inner mark so icons are not flat-color-only
    for x in range(16, 48):
        for y in range(16, 48):
            img.putpixel((x, y), (255, 255, 255))
    return img


class VisionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.op_dir = os.path.join(ASSETS, "op")
        cls.created = os.path.join(cls.op_dir, "_selftest")
        os.makedirs(cls.created, exist_ok=True)
        # isolated templates live in a temp subfolder; point a matcher there by
        # temporarily monkeypatching its dir.
        cls.paths = []
        for name, col in COLORS.items():
            p = os.path.join(cls.created, name + ".png")
            make_icon(col).save(p)
            cls.paths.append(p)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.created, ignore_errors=True)

    def test_template_match_identity(self):
        m = TemplateMatcher("op")
        m.dir = self.created          # use synthetic-only templates
        m._templates = {}
        slot = make_icon(COLORS["测试干员乙"])
        name, conf, scores = m.match(slot, threshold=0.0)
        self.assertEqual(name, "测试干员乙")
        self.assertGreater(conf, 0.9)
        self.assertEqual(set(scores), set(COLORS))

    def test_unknown_low_confidence(self):
        m = TemplateMatcher("op")
        m.dir = self.created
        m._templates = {}
        # a completely different noisy image should not clear a high threshold
        import random
        random.seed(1)
        noisy = Image.new("RGB", (64, 64))
        noisy.putdata([(random.randrange(256), random.randrange(256),
                        random.randrange(256)) for _ in range(64 * 64)])
        name, conf, _ = m.match(noisy, threshold=0.95)
        self.assertIsNone(name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
