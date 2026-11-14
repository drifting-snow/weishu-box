# -*- coding: utf-8 -*-
"""End-to-end smoke: opening parse on difficulty-select ref shot."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADVISOR = ROOT.parent / "weishu-advisor"
sys.path.insert(0, str(ADVISOR))
sys.path.insert(0, str(ROOT / "shell"))

from PIL import Image  # noqa: E402
from opening_parse import parse_opening_detections  # noqa: E402
from vision.shop_band_ocr import BandOCREngine  # noqa: E402


def main() -> int:
    shot = ROOT / "session" / "ref_difficulty_select_13.png"
    img = Image.open(shot).convert("RGB")
    w, h = img.size
    eng = BandOCREngine()
    small = img.resize((w // 2, h // 2))
    raw = eng.detect(small)
    parsed = parse_opening_detections(
        raw,
        img_w=float(small.width),
        img_h=float(small.height),
        bond_names=[],
        operator_names=[],
        image=small,
    )
    print("screen", parsed.get("screen"))
    print("procedure_level", parsed.get("procedure_level"))
    pl = parsed.get("procedure_level")
    # Mirror run_env.gamestate_patch mapping without package import.
    regulation = int(pl) if pl is not None else None
    print("regulation_level", regulation)
    assert parsed.get("screen") == "difficulty_select", parsed
    assert pl == 13, parsed
    assert regulation == 13, regulation
    print(json.dumps({"ok": True, "procedure_level": 13, "regulation_level": 13}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
