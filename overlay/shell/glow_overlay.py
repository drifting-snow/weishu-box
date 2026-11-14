# -*- coding: utf-8 -*-
"""Win32 color-key glow frames over the primary monitor (no WebView2).

Uses the primary monitor's rcMonitor (physical pixels) so fractions of
2560×1440 map 1:1 when the game is fullscreen on that display.
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Optional, Sequence

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST = -1
SWP_SHOWWINDOW = 0x0040
SWP_NOACTIVATE = 0x0010
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_FRAMECHANGED = 0x0020
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
LWA_COLORKEY = 0x1
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
CS_HREDRAW = 0x0002
CS_VREDRAW = 0x0001
IDC_ARROW = 32512
COLOR_KEY = 0x000000
MONITOR_DEFAULTTOPRIMARY = 1
RDW_INVALIDATE = 0x0001
RDW_ERASE = 0x0004
RDW_UPDATENOW = 0x0100
RDW_ALLCHILDREN = 0x0080
RDW_FRAME = 0x0400

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", wintypes.BYTE * 32),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


# 64-bit safe: untyped DefWindowProcW overflows on large LPARAMs and aborts paint.
user32.DefWindowProcW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = wintypes.HDC
user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.EndPaint.restype = wintypes.BOOL
user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
user32.InvalidateRect.restype = wintypes.BOOL
user32.UpdateWindow.argtypes = [wintypes.HWND]
user32.UpdateWindow.restype = wintypes.BOOL
user32.RedrawWindow.argtypes = [
    wintypes.HWND,
    ctypes.c_void_p,
    wintypes.HRGN,
    wintypes.UINT,
]
user32.RedrawWindow.restype = wintypes.BOOL


def primary_monitor_rect() -> tuple[int, int, int, int]:
    """Return (left, top, width, height) of the primary monitor in screen pixels."""
    pt = wintypes.POINT(0, 0)
    mon = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTOPRIMARY)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if mon and user32.GetMonitorInfoW(mon, ctypes.byref(info)):
        r = info.rcMonitor
        return int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top)
    return 0, 0, int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))


class GlowOverlay:
    CLASS_NAME = "WeishuGlowOverlayV3"

    def __init__(self):
        self._hwnd: Optional[int] = None
        self._frames: list[dict] = []
        self._lock = threading.Lock()
        self._wndproc = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._mon = primary_monitor_rect()
        # Paint surface size locked at last set_frames (physical px). Avoid
        # GetClientRect drift if the HWND lags SetWindowPos after hide/show.
        self._paint_wh: tuple[int, int] = (self._mon[2], self._mon[3])
        self._seq = 0  # monotonically increases on every clear/set

    @property
    def hwnd(self) -> Optional[int]:
        return self._hwnd

    def ensure(self) -> None:
        if self._hwnd:
            return
        if self._thread and self._thread.is_alive():
            self._ready.wait(timeout=3.0)
            return
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._thread_main, name="weishu-glow", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=3.0)

    def clear(self) -> None:
        """Hide immediately (OCR start). HWND stays alive for the next set_frames."""
        with self._lock:
            self._seq += 1
            self._frames = []
        hwnd = self._hwnd
        if not hwnd:
            return
        # Blank the surface while still visible, then hide — avoids stale green.
        self._force_paint(hwnd)
        user32.ShowWindow(hwnd, SW_HIDE)

    def set_frames(self, frames: Sequence[dict]) -> None:
        """Replace glow rects every call. Empty → clear/hide; non-empty → show+paint."""
        cleaned = [dict(f) for f in frames if f.get("frac")]
        with self._lock:
            self._seq += 1
            self._frames = cleaned
            empty = not self._frames
        hwnd = self._hwnd
        if empty:
            if hwnd:
                self._force_paint(hwnd)
                user32.ShowWindow(hwnd, SW_HIDE)
            return

        self.ensure()
        hwnd = self._hwnd
        if not hwnd:
            return

        # Re-query primary every OCR — never accumulate a stale origin/size.
        left, top, width, height = primary_monitor_rect()
        self._mon = (left, top, width, height)
        with self._lock:
            self._paint_wh = (max(1, width), max(1, height))

        # Re-assert layered color-key every show — survives hide/show cycles.
        user32.SetLayeredWindowAttributes(hwnd, COLOR_KEY, 0, LWA_COLORKEY)
        user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            left,
            top,
            width,
            height,
            SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_FRAMECHANGED,
        )
        # Show FIRST, then paint onto the visible layered surface.
        # (Painting while still hidden after SW_HIDE often leaves a blank frame
        # on the second OCR cycle.)
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        self._force_paint(hwnd)
        # Second paint pass: layered color-key sometimes drops the first
        # UpdateWindow after a hide→show transition.
        self._force_paint(hwnd)

    def hide(self) -> None:
        """Alias for clear — panel toggle / OCR start."""
        self.clear()

    def destroy(self) -> None:
        with self._lock:
            self._seq += 1
            self._frames = []
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
            self._hwnd = None

    def _force_paint(self, hwnd: int) -> None:
        user32.InvalidateRect(hwnd, None, True)
        user32.RedrawWindow(
            hwnd,
            None,
            None,
            RDW_INVALIDATE | RDW_ERASE | RDW_UPDATENOW | RDW_ALLCHILDREN | RDW_FRAME,
        )
        user32.UpdateWindow(hwnd)

    def _thread_main(self) -> None:
        try:
            self._create_window()
            self._ready.set()
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            self._ready.set()
        finally:
            self._hwnd = None

    def _create_window(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)
        overlay = self

        def _proc(hwnd, msg, wparam, lparam):
            if msg == WM_PAINT:
                ps = PAINTSTRUCT()
                hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
                try:
                    overlay._paint(hdc, hwnd)
                finally:
                    user32.EndPaint(hwnd, ctypes.byref(ps))
                return 0
            if msg == WM_ERASEBKGND:
                return 1
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = WNDPROC(_proc)
        wc = WNDCLASSW()
        wc.style = CS_HREDRAW | CS_VREDRAW
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, IDC_ARROW)
        wc.hbrBackground = gdi32.CreateSolidBrush(COLOR_KEY)
        wc.lpszClassName = self.CLASS_NAME
        # Ignore already-registered (relaunch in same process)
        user32.RegisterClassW(ctypes.byref(wc))

        left, top, width, height = primary_monitor_rect()
        self._mon = (left, top, width, height)
        ex = (
            WS_EX_LAYERED
            | WS_EX_TRANSPARENT
            | WS_EX_TOPMOST
            | WS_EX_TOOLWINDOW
            | WS_EX_NOACTIVATE
        )
        hwnd = user32.CreateWindowExW(
            ex,
            self.CLASS_NAME,
            "weishu-glow",
            WS_POPUP,
            left,
            top,
            width,
            height,
            None,
            None,
            hinst,
            None,
        )
        if not hwnd:
            raise OSError("CreateWindowExW failed for glow overlay")
        self._hwnd = int(hwnd)
        user32.SetLayeredWindowAttributes(hwnd, COLOR_KEY, 0, LWA_COLORKEY)
        user32.ShowWindow(hwnd, SW_HIDE)

    def _paint(self, hdc, hwnd) -> None:
        # Prefer the monitor size snapped at set_frames. Fall back to client
        # rect only if unset — prevents fraction mapping against a lagged HWND.
        with self._lock:
            sw, sh = self._paint_wh
            frames = list(self._frames)
        if sw <= 1 or sh <= 1:
            rc = RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rc))
            sw = max(1, int(rc.right - rc.left))
            sh = max(1, int(rc.bottom - rc.top))

        brush = gdi32.CreateSolidBrush(COLOR_KEY)
        old = gdi32.SelectObject(hdc, brush)
        gdi32.PatBlt(hdc, 0, 0, sw, sh, 0x00F00021)  # PATCOPY
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(brush)

        for f in frames:
            frac = f.get("frac") or [0, 0, 0, 0]
            x, y, w, h = frac
            left = int(round(x * sw))
            top = int(round(y * sh))
            right = int(round((x + w) * sw))
            bottom = int(round((y + h) * sh))
            for inset, color, width in (
                (-6, 0x00448844, 2),
                (-2, 0x0055CC77, 3),
                (2, 0x005DFFB0, 3),
            ):
                pen = gdi32.CreatePen(0, width, color)
                old_pen = gdi32.SelectObject(hdc, pen)
                old_brush = gdi32.SelectObject(hdc, gdi32.GetStockObject(5))
                gdi32.Rectangle(
                    hdc,
                    left - inset,
                    top - inset,
                    right + inset,
                    bottom + inset,
                )
                gdi32.SelectObject(hdc, old_brush)
                gdi32.SelectObject(hdc, old_pen)
                gdi32.DeleteObject(pen)
