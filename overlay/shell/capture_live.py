# -*- coding: utf-8 -*-
"""Live screen capture for overlay (read-only pixels). Never opens image viewers."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image


def grab_primary(region: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
    """Capture primary monitor (or a pixel box). No UI, no Image.show()."""
    from PIL import ImageGrab

    # all_screens=False → primary virtual desktop origin behavior on Win
    img = ImageGrab.grab(bbox=region, all_screens=False)
    return img.convert("RGB")


def grab_primary_to_temp(
    region: Optional[Tuple[int, int, int, int]] = None,
    prefix: str = "weishu-live-",
) -> Path:
    """Save a live capture to a temp JPEG (faster than PNG); never display it."""
    img = grab_primary(region=region)
    fd, name = tempfile.mkstemp(prefix=prefix, suffix=".jpg")
    path = Path(name)
    try:
        import os

        os.close(fd)
    except Exception:
        pass
    # JPEG is much cheaper to encode than PNG for 2560×1440; OCR still works.
    # quality=85 / no optimize: ~3× faster encode than q90+optimize on 1440p.
    img.save(path, format="JPEG", quality=85, optimize=False)
    return path
