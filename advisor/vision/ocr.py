# -*- coding: utf-8 -*-
"""Pluggable OCR backends. The advisor core never hard-requires any OCR stack.

Priority in get_default_ocr():
  1. RapidOCR (rapidocr_onnxruntime) - offline, bundles PP-OCR models, pip-only
  2. Windows built-in OCR (winrt)   - no model download, Windows 10/11 only
  3. NullOCR                        - returns empty; you then input manually

All backends expose .read(PIL.Image) -> str. Keep them swappable so the
intranet target machine can run pure-stdlib/manual until an offline wheel of
RapidOCR + models is transferred.
"""
from PIL import Image


class NullOCR:
    name = "null"

    def read(self, img: Image.Image) -> str:
        return ""


class RapidOCREngine:
    """Offline PaddleOCR-compatible engine via rapidocr_onnxruntime."""
    name = "rapidocr"

    def __init__(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
        except Exception as e:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "rapidocr_onnxruntime is not installed; `pip install rapidocr_onnxruntime`") from e
        self._ocr = RapidOCR()

    def read(self, img: Image.Image) -> str:
        import numpy as np
        result, _ = self._ocr(np.asarray(img.convert("RGB")))
        if not result:
            return ""
        # each item: [box, text, score]; join texts left-to-right by x origin
        items = sorted(result, key=lambda r: min(p[0] for p in r[0]))
        return " ".join(str(r[1]) for r in items).strip()


class WindowsOCREngine:
    """Windows.Media.Ocr via winrt (no model download). Best-effort, zh-CN."""
    name = "windows_ocr"

    def __init__(self, lang="zh-Hans-CN"):  # pragma: no cover - platform specific
        import asyncio
        import winrt.windows.media.ocr as ocr
        import winrt.windows.graphics.imaging as imaging
        import winrt.windows.globalization as globalization
        self._ocr = ocr
        self._imaging = imaging
        self._lang = globalization.Language(lang)
        self._engine = ocr.OcrEngine.try_create_from_language(self._lang)
        self._asyncio = asyncio

    def read(self, img: Image.Image) -> str:  # pragma: no cover
        import numpy as np
        arr = np.asarray(img.convert("RGBA"))
        # build a SoftwareBitmap via an in-memory PNG stream
        import io
        buf = io.BytesIO()
        img.convert("RGBA").save(buf, format="PNG")
        stream = self._imaging.InMemoryRandomAccessStream()
        writer = stream.get_output_stream_at(0)
        writer.write(buf.getvalue())
        writer.flush()
        stream.seek(0)
        bitmap = self._imaging.BitmapDecoder.create_async(stream)
        # winrt async bridging varies by wrapper version; kept as an extension point
        raise NotImplementedError(
            "Windows OCR async bridge needs environment-specific wiring; use RapidOCR")


def get_default_ocr():
    try:
        return RapidOCREngine()
    except Exception:
        return NullOCR()
