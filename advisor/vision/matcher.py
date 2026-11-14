# -*- coding: utf-8 -*-
"""Icon template matching with numpy only (no OpenCV required).

Templates are small PNGs named after the operator/item, e.g.
  assets/templates/op/史尔特尔.png
  assets/templates/item/坚守盾牌.png
A slot crop is resized to a fixed canvas and compared to every template by
normalized mean absolute error; the smallest error wins. Confidence is
1 - error in 0..1.

Deterministic and offline. For higher runtime accuracy, replace .match() with
cv2.matchTemplate or an ONNX embedding model while keeping the same API.
"""
import os
import numpy as np
from PIL import Image

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "assets", "templates")


def to_array(img: Image.Image, size=(64, 64)) -> np.ndarray:
    if img.size != size:
        img = img.resize(size, Image.BILINEAR)
    return np.asarray(img, dtype=np.float32) / 255.0


def normalized_mae(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a - b)))


class TemplateMatcher:
    def __init__(self, subdir="op", target_size=(64, 64)):
        self.dir = os.path.join(ASSETS, subdir)
        self.target_size = target_size
        self._templates = {}  # name -> array on the fixed canvas

    def _load(self):
        if self._templates or not os.path.isdir(self.dir):
            return
        for fn in os.listdir(self.dir):
            if not fn.lower().endswith(".png"):
                continue
            name = os.path.splitext(fn)[0]
            img = Image.open(os.path.join(self.dir, fn)).convert("RGB")
            self._templates[name] = to_array(img, self.target_size)

    def names(self):
        self._load()
        return sorted(self._templates.keys())

    def match(self, slot_img: Image.Image, threshold=0.0):
        """Return (best_name, confidence 0..1, all_scores). None if no templates."""
        self._load()
        if not self._templates:
            return None, 0.0, {}
        slot = to_array(slot_img, self.target_size)
        scores = {name: 1.0 - normalized_mae(slot, arr)
                  for name, arr in self._templates.items()}
        best = max(scores, key=scores.get)
        if scores[best] < threshold:
            return None, scores[best], scores
        return best, scores[best], scores
