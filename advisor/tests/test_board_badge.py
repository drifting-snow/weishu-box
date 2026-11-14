# -*- coding: utf-8 -*-
"""Self-contained tests for the head-badge detector (no game screenshots).

Stamps the shipped badge template onto a flat tile-coloured canvas at the
calibrated 2560x1440 resolution, exercising the real NCC + shape-gate + grid
pipeline without depending on large copyrighted game frames. The flat canvas
is deliberately uniform so only stamped markers can pass the shape gate.
"""
import unittest

import numpy as np
from PIL import Image

from vision.board_badge import (
    Badge,
    BOARD_ROIS,
    detect_badges,
    load_template,
    _shape_gate,
)

CANVAS_W, CANVAS_H = 2560, 1440
TILE_GRAY = 185          # light sandy tile, brighter than the badge (~95 mean)
# Real badge centres from the calibrated normal frame; all inside BOARD_ROIS.
REAL_CENTERS = [(872, 387), (1016, 387), (1465, 644), (1620, 644), (1797, 788)]


def _canvas():
    return np.full((CANVAS_H, CANVAS_W), TILE_GRAY, dtype=np.float32)


def _stamp(canvas, tpl, cx, cy):
    h, w = tpl.shape
    y0, x0 = cy - h // 2, cx - w // 2
    canvas[y0:y0 + h, x0:x0 + w] = tpl


def _frame(centers):
    tpl = load_template()
    canvas = _canvas()
    for cx, cy in centers:
        _stamp(canvas, tpl, cx, cy)
    return canvas, tpl


class TemplateLoadingTest(unittest.TestCase):
    def test_template_shipped_and_grayscale(self):
        tpl = load_template()
        self.assertEqual(tpl.ndim, 2)
        # 1440p reference template is 76 wide x 66 tall.
        self.assertEqual(tpl.shape, (66, 76))
        self.assertLess(tpl.mean(), 140.0)      # dark marker, not a bright tile


class ShapeGateTest(unittest.TestCase):
    def test_true_badge_passes_gate(self):
        canvas, tpl = _frame([(872, 387)])
        ok, bars, darkening, bvi = _shape_gate(canvas, 872, 387, half=34)
        self.assertTrue(ok)
        self.assertGreaterEqual(bars, 1)
        self.assertGreaterEqual(darkening, 25.0)
        self.assertGreaterEqual(bvi, 20.0)

    def test_flat_tile_rejected(self):
        canvas = _canvas()
        ok, bars, darkening, bvi = _shape_gate(canvas, 872, 387, half=34)
        self.assertFalse(ok)
        self.assertLess(darkening, 25.0)


class DetectionTest(unittest.TestCase):
    def test_detects_all_stamped_badges_inside_roi(self):
        canvas, tpl = _frame(REAL_CENTERS)
        badges = detect_badges(canvas, template=tpl, rois=BOARD_ROIS)
        self.assertEqual(len(badges), len(REAL_CENTERS))
        self.assertTrue(all(isinstance(b, Badge) for b in badges))
        got = {(b.cx, b.cy) for b in badges}
        for ex in REAL_CENTERS:
            self.assertTrue(
                any(abs(ex[0] - gx) <= 12 and abs(ex[1] - gy) <= 12
                    for gx, gy in got),
                "missing badge near %s" % (ex,),
            )
        for b in badges:
            self.assertTrue(
                any(x0 <= b.cx_f <= x1 and y0 <= b.cy_f <= y1
                    for x0, y0, x1, y1 in BOARD_ROIS)
            )

    def test_blank_canvas_has_no_detection(self):
        canvas, tpl = _frame([])
        self.assertEqual(detect_badges(canvas, template=tpl, rois=BOARD_ROIS), [])

    def test_near_flat_patch_never_collapses_into_a_detection(self):
        # Near-flat low-variance UI regions (freeze/refresh buttons) drive the
        # normalized correlation outside its mathematical [-1, 1] range. Such a
        # collapse must never surface as a badge, even inside an ROI.
        tpl = load_template()
        canvas = _canvas()
        rng = np.random.default_rng(0)
        patch = (TILE_GRAY
                 + rng.normal(0.0, 1.7, (120, 120)).astype(np.float32)
                 + np.linspace(-3.0, 3.0, 120)[None, :])
        canvas[400:520, 800:920] = patch          # centre ~ (860, 460), inside ROI
        self.assertEqual(detect_badges(canvas, template=tpl, rois=BOARD_ROIS), [])

    def test_returned_scores_stay_within_ncc_range(self):
        # A correlation coefficient is bounded to [-1, 1]; lock this invariant
        # so a future NCC change cannot reintroduce super-unity collapse peaks.
        canvas, tpl = _frame(REAL_CENTERS)
        for b in detect_badges(canvas, template=tpl, rois=BOARD_ROIS):
            self.assertLessEqual(abs(b.score), 1.0)

    def test_accepts_pil_and_ndarray_equivalently(self):
        canvas, tpl = _frame([(872, 387), (1465, 644)])
        from_array = detect_badges(canvas, template=tpl, rois=BOARD_ROIS)
        pil = Image.fromarray(canvas.astype(np.uint8)).convert("RGB")
        from_pil = detect_badges(pil, template=tpl, rois=BOARD_ROIS)
        self.assertEqual(len(from_array), len(from_pil))

    def test_fractions_resolution_independent(self):
        canvas, _ = _frame([(872, 387), (1465, 644), (1797, 788)])
        small = np.asarray(
            Image.fromarray(canvas.astype(np.uint8)).resize((1920, 1080)),
            dtype=np.float32,
        )
        b_full = detect_badges(canvas, rois=BOARD_ROIS)
        b_small = detect_badges(small, rois=BOARD_ROIS)
        self.assertEqual(len(b_full), len(b_small))
        for a, b in zip(
            sorted(b_full, key=lambda z: (z.cy_f, z.cx_f)),
            sorted(b_small, key=lambda z: (z.cy_f, z.cx_f)),
        ):
            self.assertAlmostEqual(a.cx_f, b.cx_f, delta=0.015)
            self.assertAlmostEqual(a.cy_f, b.cy_f, delta=0.015)


if __name__ == "__main__":
    unittest.main()
