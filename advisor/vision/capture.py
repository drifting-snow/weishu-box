# -*- coding: utf-8 -*-
"""Screen capture. PIL ImageGrab on Windows, with an image-file fallback.

No game memory / input injection: this only reads pixels from the screen or
from a saved screenshot, keeping the tool strictly read-only (advisor only).
"""
from PIL import Image


def grab_screen(region=None):
    """Capture the whole screen or a bounding box (left, top, right, bottom)."""
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=True)
    except Exception:
        # headless / unsupported: callers should use load_image instead
        raise
    if region:
        img = img.crop(region)
    return img.convert("RGB")


def load_image(path):
    return Image.open(path).convert("RGB")
