# -*- coding: utf-8 -*-
"""Trim the optional OCR stack for offline/GitHub distribution.

The advisor core is pure stdlib; only the screenshot path needs the vision
extra (rapidocr -> onnxruntime / numpy / opencv). Two things in that stack are
dead weight for static-image OCR:

  1. opencv's bundled FFmpeg video plugin
     (opencv_videoio_ffmpeg*.dll / libopencv_videoio_ffmpeg*.so): only used for
     video capture/decoding. We read still PNGs, so it is safe to remove.
     ~25-29 MB on Windows.
  2. opencv-python (with Qt/GUI DLLs) vs opencv-python-headless: rapidocr only
     ever imports ``cv2``, never opens a window, so the headless wheel works
     unchanged. Swap manually (see README); this script handles the FFmpeg trim
     that applies to either wheel.

The script MOVES the plugin into a backup folder next to cv2 (recoverable), it
never permanently deletes anything. Stdlib only.

Usage:
  python tools/slim_vision.py            # dry-run, report what would move
  python tools/slim_vision.py --apply    # perform the move
"""
import argparse
import glob
import os
import shutil
import sys

# Filename globs across platforms for the FFmpeg video plugin.
FFMPEG_GLOBS = (
    "opencv_videoio_ffmpeg*.dll",   # Windows
    "libopencv_videoio_ffmpeg*.so",  # Linux
    "libopencv_videoio_ffmpeg*.dylib",  # macOS
)
BACKUP_DIRNAME = "_removed_ffmpeg"


def find_cv2_dir():
    try:
        import cv2  # noqa: F401
    except Exception as e:
        return None, "cv2 not importable: %s" % e
    return os.path.dirname(os.path.abspath(cv2.__file__)), None


def find_ffmpeg_plugins(cv2_dir):
    hits = []
    for pattern in FFMPEG_GLOBS:
        hits.extend(glob.glob(os.path.join(cv2_dir, "**", pattern),
                              recursive=True))
    return sorted(set(hits))


def human_mb(path):
    return round(os.path.getsize(path) / 1048576, 1)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Trim FFmpeg plugin from opencv.")
    ap.add_argument("--apply", action="store_true",
                    help="move the plugin to a backup folder (default: dry-run)")
    args = ap.parse_args(argv)

    cv2_dir, err = find_cv2_dir()
    if err:
        print("[slim] %s" % err)
        print("[slim] Install the vision extra first: pip install -e \".[vision]\"")
        return 1

    plugins = find_ffmpeg_plugins(cv2_dir)
    if not plugins:
        print("[slim] No FFmpeg video plugin found under %s (already trimmed?)."
              % cv2_dir)
        return 0

    total = sum(human_mb(p) for p in plugins)
    backup = os.path.join(cv2_dir, BACKUP_DIRNAME)
    for p in plugins:
        print("  %7s MB  %s" % (human_mb(p), p))
    print("[slim] %d plugin file(s), %.1f MB total." % (len(plugins), total))

    if not args.apply:
        print("[slim] Dry-run only. Re-run with --apply to move them to:\n  %s"
              % backup)
        return 0

    os.makedirs(backup, exist_ok=True)
    for p in plugins:
        shutil.move(p, os.path.join(backup, os.path.basename(p)))
    print("[slim] Moved %d file(s) to %s" % (len(plugins), backup))
    print("[slim] Re-run the OCR smoke test to confirm; restore by moving them back.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
