# -*- coding: utf-8 -*-
"""ROI preprocessing for OCR, reimplemented with PIL+numpy (no OpenCV).

Mirrors the proven MAA pipeline:
  grayscale -> upscale (x3 digits / x2 text) -> invert dark background
  -> binary threshold for digits -> white border padding
The OCR backend receives a clean, high-contrast, light-background image.
"""
import numpy as np
from PIL import Image

BORDER = 10
DARK_MEAN = 100
DIGIT_THRESHOLD = 150


def _gray(img: Image.Image) -> Image.Image:
    return img.convert("L")


def _to_pil(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(arr.astype(np.uint8), mode="L")


def preprocess(img: Image.Image, is_number: bool = False) -> Image.Image:
    gray = _gray(img)
    scale = 3.0 if is_number else 2.0
    if scale != 1.0:
        size = (max(1, int(gray.width * scale)), max(1, int(gray.height * scale)))
        gray = gray.resize(size, Image.BICUBIC)

    arr = np.asarray(gray, dtype=np.uint8)

    # invert when the background is dark (mean brightness below threshold)
    border_px = np.concatenate([arr[0, :], arr[-1, :], arr[:, 0], arr[:, -1]])
    if float(np.mean(border_px)) < DARK_MEAN:
        arr = 255 - arr

    if is_number:
        arr = np.where(arr >= DIGIT_THRESHOLD, 255, 0).astype(np.uint8)

    # white padding so glyphs never touch the image edge (helps OCR)
    padded = np.full((arr.shape[0] + 2 * BORDER, arr.shape[1] + 2 * BORDER),
                     255, dtype=np.uint8)
    padded[BORDER:BORDER + arr.shape[0], BORDER:BORDER + arr.shape[1]] = arr
    return _to_pil(padded).convert("RGB")


def digit_correct(text: str) -> str:
    """Common OCR digit confusions (MAA uses the same map)."""
    table = {
        "O": "0", "o": "0", "Q": "0", "D": "0",
        "I": "1", "l": "1", "i": "1",
        "Z": "2", "z": "2",
        "S": "5", "s": "5",
        "B": "8", "b": "6",
        "g": "9", "q": "9",
    }
    for k, v in table.items():
        text = text.replace(k, v)
    return "".join(ch for ch in text if ch.isdigit())
