# -*- coding: utf-8 -*-
"""Convenience launcher: python run_overlay.py

No --demo. Does not open screenshot viewers. Live OCR only on button/hotkey.
"""
import sys

from shell.main import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
