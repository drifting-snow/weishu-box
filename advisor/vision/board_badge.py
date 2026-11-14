# -*- coding: utf-8 -*-
"""Detect deployed-unit head badges (the I-VI / 1-to-6-bar marker above each
chibi). Only tiers I/II/III have been seen and profiled so far; tiers IV/V/S
VI exist in-game and their full-frame samples are pending (user to supply).
Localization relies on the shared dark rounded-square frame, not the bar
count, so adding higher tiers should not break detection; only the best-effort
bar-count classifier needs re-checking on dense IV-VI bars.

Why badges: the board chibi themselves cannot be OCR'd reliably (2D art, no
text, selection-state colour overlays). Every owned unit instead carries a
fixed dark rounded-square badge with 1-3 bright vertical bars just above its
head. The badge is a stable, high-contrast anchor that also yields a unit
count; the marker->click offset (down-right) is resolved by the click shell,
not here. This module is perception-only and never clicks.

Validated on four real 2560x1440 frames (see
docs/board_click_ocr_design.md section 8.5): 100% precision/recall on normal
(unselected) frames, 7/7 badges including the bench row. Selection-state
frames intentionally degrade (orange overlay) - the caller must ESC back to a
normal frame before detecting.

Pipeline (pure numpy + pillow, no new dependencies):
  1. FFT normalized cross-correlation against a fixed badge template, with an
     absolute local-variance floor so near-flat regions (water, solid overlay)
     cannot blow the normalized score past the [-1, 1] range.
  2. Data-driven shape gate. Profiled true vs false samples separate cleanly
     on `darkening` (badge darker than its surrounding tile ring): true badges
     >= 26.7 gray levels, every false positive <= 23.1. A second feature
     `bar_vs_inner` (brightest central column vs dark interior) guards the bar.
  3. Row/grid clustering: real badges form an equidistant lattice; scattered
     lone candidates are rejected.

Thresholds were profiled at 2560x1440 and MUST be re-checked at other
resolutions / UI scales (documented as a remaining calibration gap).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

# --- Calibrated constants (2560x1440, 100% UI scale). See module docstring. ---
# ROI boxes as (x0, y0, x1, y1) fractions: main board then the bench row.
# Excludes top bar/covenant icons, left ESC+skill panel, right enemy/red-frame
# zone and freeze/refresh buttons, and the y>0.72H shop-card strip / water.
BOARD_ROIS: Tuple[Tuple[float, float, float, float], ...] = (
    (0.27, 0.20, 0.75, 0.58),
    (0.27, 0.55, 0.80, 0.72),
)
PEAK_THRESH = 0.62          # NCC candidate threshold (gate does the real work)
NMS_RADIUS = 42             # px at 1440p; scaled with image height
VAR_FLOOR = 15.0 ** 2       # local-std floor (gray levels^2) against NCC collapse
DARKEN_MIN = 25.0           # clean gap: true >=26.7, false <=23.1
BAR_VS_INNER_MIN = 20.0     # bright bar must stand out from the dark interior
ROW_TOL = 34                # px at 1440p: same-row badge y tolerance
GRID_HALF = 78              # px at 1440p: max off-lattice scatter for a row
BADGE_HALF = 34             # px at 1440p: half window for the shape-gate patch
_TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "assets", "head_badge_template.png"
)


@dataclass
class Badge:
    """One detected head badge. Fraction coords are resolution-independent."""

    cx: int                     # centre pixel x
    cy: int                     # centre pixel y
    cx_f: float                 # centre x as fraction of image width
    cy_f: float                 # centre y as fraction of image height
    score: float                # NCC score (not by itself a truth test)
    tier: int                   # best-effort 1..6 bar count; I-III profiled,
                                # IV-VI pending samples; confirm exact tier via panel
    darkening: float
    bar_vs_inner: float


def load_template(path: Optional[str] = None) -> np.ndarray:
    """Load the grayscale badge template shipped under vision/assets."""
    img = Image.open(path or _TEMPLATE_PATH).convert("L")
    return np.asarray(img, dtype=np.float32)


def _to_gray(image) -> np.ndarray:
    if isinstance(image, np.ndarray):
        arr = image.astype(np.float32)
        if arr.ndim == 3:
            arr = arr.mean(axis=2)
        return arr
    return np.asarray(image.convert("L"), dtype=np.float32)


def _ncc_map(img: np.ndarray, tpl: np.ndarray) -> np.ndarray:
    """FFT normalized cross-correlation with an absolute variance floor."""
    th, tw = tpl.shape
    h, w = img.shape
    t = tpl - tpl.mean()
    t_denom = np.sqrt((t * t).sum())
    # integral images for local window sum / sum-of-squares
    ii = np.zeros((h + 1, w + 1), dtype=np.float64)
    ii[1:, 1:] = np.cumsum(np.cumsum(img, 0), 1)
    ii2 = np.zeros((h + 1, w + 1), dtype=np.float64)
    ii2[1:, 1:] = np.cumsum(np.cumsum(img * img, 0), 1)
    corr = np.fft.irfft2(
        np.fft.rfft2(img, (h, w))
        * np.fft.rfft2(np.flipud(np.fliplr(tpl)), (h, w)),
        (h, w),
    )
    n = th * tw
    res = np.full((h, w), -1.0, dtype=np.float32)
    for y in range(h - th + 1):
        xs = np.arange(w - tw + 1)
        local_sum = ii[y + th, xs + tw] - ii[y, xs + tw] - ii[y + th, xs] + ii[y, xs]
        local_sq = ii2[y + th, xs + tw] - ii2[y, xs + tw] - ii2[y + th, xs] + ii2[y, xs]
        denom = np.sqrt(np.maximum(local_sq - local_sum * local_sum / n, VAR_FLOOR))
        numer = corr[y + th - 1, xs + tw - 1] - tpl.mean() * local_sum
        res[y, xs] = numer / (t_denom * denom + 1e-9)
    return res


def _shape_gate(
    gray: np.ndarray, cx: int, cy: int, half: int
) -> Tuple[bool, int, float, float]:
    """Return (ok, bar_count, darkening, bar_vs_inner) for one candidate."""
    badge = gray[cy - half:cy + half, cx - half:cx + half]
    if badge.shape != (2 * half, 2 * half):
        return False, 0, 0.0, 0.0
    ring = []
    for dy in range(-half - 14, half + 15, 4):
        for dx in range(-half - 14, half + 15, 4):
            if abs(dx) > half or abs(dy) > half:
                ring.append(gray[cy + dy, cx + dx])
    ring = np.asarray(ring, dtype=np.float32)
    darkening = float(ring.mean() - badge.mean())
    inner = np.concatenate(
        [badge[:6].ravel(), badge[-6:].ravel(),
         badge[:, :6].ravel(), badge[:, -6:].ravel()]
    )
    strip = badge[:, half - 14:half + 14]
    col_mean = strip.mean(axis=0)
    bar_vs_inner = float(col_mean.max() - inner.mean())
    ok = darkening >= DARKEN_MIN and bar_vs_inner >= BAR_VS_INNER_MIN
    bright = col_mean > inner.mean() + max(12.0, 0.5 * bar_vs_inner)
    # NOTE: bars can reach 6 (tiers I-VI). The b-a>3 merge gap was tuned on
    # I-III; dense IV-VI bars are narrower and may under-count until real
    # samples arrive. tier stays best-effort; the panel text is authoritative.
    idx = np.where(bright)[0]
    bars = 0
    if len(idx):
        bars = 1
        for a, b in zip(idx, idx[1:]):
            if b - a > 3:
                bars += 1
    return ok, bars, darkening, bar_vs_inner


def _cluster_rows(
    pts: List[Tuple[float, int, int, int]],
    row_tol: int,
    grid_half: int,
) -> List[Tuple[float, int, int, int]]:
    """Group into rows, then keep points that sit on each row's x lattice."""
    ordered = sorted(pts, key=lambda p: p[2])  # by cy
    rows: List[List[Tuple[float, int, int, int]]] = []
    for p in ordered:
        for row in rows:
            if abs(p[2] - np.mean([q[2] for q in row])) <= row_tol:
                row.append(p)
                break
        else:
            rows.append([p])
    kept: List[Tuple[float, int, int, int]] = []
    for row in rows:
        row = sorted(row, key=lambda p: p[1])      # by cx
        if len(row) == 1:
            # A lone badge is plausible for a single-unit row; keep only if the
            # shape gate already confirmed a real bar (tier >= 1).
            if row[0][3] >= 1:
                kept.extend(row)
            continue
        xs = np.array([p[1] for p in row])
        gaps = np.diff(xs)
        step = np.median(gaps[gaps > 0]) if np.any(gaps > 0) else grid_half * 2
        anchor = xs[0]
        good = [row[0]]
        for p in row[1:]:
            k = round((p[1] - anchor) / step)
            if abs(p[1] - (anchor + k * step)) <= grid_half:
                good.append(p)
        kept.extend(good)
    return kept


def detect_badges(
    image,
    template: Optional[np.ndarray] = None,
    rois: Sequence[Tuple[float, float, float, float]] = BOARD_ROIS,
) -> List[Badge]:
    """Detect all head badges in a normal (unselected) preparation screenshot.

    `image` is a PIL image (RGB/L) or a grayscale/RGB numpy array. Selection
    state frames are expected to under-detect by design; ESC to a normal frame
    first. Returns badges ordered top-to-bottom, left-to-right.
    """
    gray = _to_gray(image)
    height, width = gray.shape
    base_tpl = template if template is not None else load_template()
    scale = height / 1440.0
    # Rescale the template to the target resolution so NCC matches the badge
    # size actually present (gray-level thresholds stay in 0-255 and are not
    # scaled; only geometry and the template are).
    if abs(scale - 1.0) > 0.02:
        bth, btw = base_tpl.shape
        new_w = max(16, int(round(btw * scale)))
        new_h = max(14, int(round(bth * scale)))
        tpl = np.asarray(
            Image.fromarray(base_tpl.astype(np.uint8)).resize((new_w, new_h),
                                                                Image.LANCZOS),
            dtype=np.float32,
        )
    else:
        tpl = base_tpl
    th, tw = tpl.shape
    nms_r = max(8, int(round(NMS_RADIUS * scale)))
    row_tol = max(8, int(round(ROW_TOL * scale)))
    grid_half = max(16, int(round(GRID_HALF * scale)))
    half = max(16, int(round(BADGE_HALF * scale)))

    boxes_px = [
        (max(0, int(x0 * width)), max(0, int(y0 * height)),
         min(width, int(x1 * width)), min(height, int(y1 * height)))
        for x0, y0, x1, y1 in rois
    ]

    def in_roi(x: int, y: int) -> bool:
        return any(a <= x < c and b <= y < d for a, b, c, d in boxes_px)

    res = _ncc_map(gray, tpl)
    # A normalized correlation coefficient is mathematically bounded to
    # [-1, 1]. Despite the VAR_FLOOR guard, near-flat UI regions (e.g. the
    # freeze/refresh buttons, std ~2 gray levels) still produce |score| > 1
    # (observed 2.21, 3.78) from residual numerical instability. Such peaks are
    # never real badges, so hard-discard anything outside the valid range;
    # true detections always satisfy |score| <= 1 and are unaffected.
    valid = (res > PEAK_THRESH) & (res <= 1.0)
    candidates: List[Tuple[float, int, int]] = []
    for yy, xx in np.argwhere(valid):
        cx, cy = xx + tw // 2, yy + th // 2
        if in_roi(cx, cy):
            candidates.append((float(res[yy, xx]), cx, cy))
    candidates.sort(reverse=True)

    nms: List[Tuple[float, int, int]] = []
    for score, cx, cy in candidates:
        if all((cx - kx) ** 2 + (cy - ky) ** 2 > nms_r ** 2
               for _, kx, ky in nms):
            nms.append((score, cx, cy))

    gated: List[Tuple[float, int, int, int]] = []
    for score, cx, cy in nms:
        ok, bars, _, _ = _shape_gate(gray, cx, cy, half)
        if ok:
            gated.append((score, cx, cy, max(1, bars)))

    final = _cluster_rows(gated, row_tol, grid_half)
    badges = [
        Badge(
            cx=cx, cy=cy, cx_f=cx / width, cy_f=cy / height,
            score=round(score, 3), tier=tier,
            darkening=round(_shape_gate(gray, cx, cy, half)[2], 1),
            bar_vs_inner=round(_shape_gate(gray, cx, cy, half)[3], 1),
        )
        for score, cx, cy, tier in sorted(final, key=lambda p: (p[2], p[1]))
    ]
    return badges
