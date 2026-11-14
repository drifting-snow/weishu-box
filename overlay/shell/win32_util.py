# -*- coding: utf-8 -*-
"""Minimal Win32 helpers: topmost, layered alpha, click-through, hotkeys."""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable, Optional, Tuple

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
LWA_ALPHA = 0x2
# Must be pointer-sized ((HWND)-1). Plain Python -1 without SetWindowPos
# argtypes zero-extends to 0xFFFFFFFF on x64 → ERROR_INVALID_WINDOW_HANDLE,
# so style changes that drop TOPMOST never get reasserted (参谋 panel bug).
HWND_TOPMOST = wintypes.HWND(-1)
HWND_NOTOPMOST = wintypes.HWND(-2)
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
VK_LBUTTON = 0x01
WM_NCLBUTTONDOWN = 0x00A1
HTCAPTION = 2

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.ReleaseCapture.argtypes = []
user32.ReleaseCapture.restype = wintypes.BOOL
user32.SendMessageW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.SendMessageW.restype = wintypes.LPARAM

# Hard lock while native caption drag (WM_NCLBUTTONDOWN) owns the move loop.
# Heartbeat / chrome-guard must not SetWindowPos or toggle WS_EX_* during this.
_drag_lock = threading.Event()

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

# Prefer 64-bit aware Get/SetWindowLongPtr when available
if ctypes.sizeof(ctypes.c_void_p) == 8:
    _GetWindowLong = user32.GetWindowLongPtrW
    _SetWindowLong = user32.SetWindowLongPtrW
else:
    _GetWindowLong = user32.GetWindowLongW
    _SetWindowLong = user32.SetWindowLongW


def find_window_by_title(title: str) -> Optional[int]:
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return None
    return int(hwnd)


def left_button_down() -> bool:
    """True while primary mouse button is held (drag / click in progress)."""
    try:
        return bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
    except Exception:
        return False


def drag_in_progress() -> bool:
    """Native caption drag session or any LMB hold (skip Z-order / style churn)."""
    return _drag_lock.is_set() or left_button_down()


def read_exstyle(hwnd: int) -> int:
    if not hwnd:
        return 0
    try:
        return int(_GetWindowLong(hwnd, GWL_EXSTYLE) or 0)
    except Exception:
        return 0


def clear_transparent_bits(hwnd: int) -> int:
    """Drop WS_EX_TRANSPARENT/NOACTIVATE without SetWindowPos (safe mid-gesture)."""
    if not hwnd or not user32.IsWindow(hwnd):
        return 0
    ex = read_exstyle(hwnd)
    new_ex = (ex | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST) & ~(
        WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
    )
    if new_ex != ex:
        try:
            _SetWindowLong(hwnd, GWL_EXSTYLE, new_ex)
        except Exception:
            pass
        ex = read_exstyle(hwnd)
    return ex


def begin_caption_drag(hwnd: int) -> dict:
    """Native Windows title-bar drag (ReleaseCapture + WM_NCLBUTTONDOWN/HTCAPTION).

    pywebview easy_drag + ``-webkit-app-region: drag`` is unreliable on WebView2
    WinForms hosts: app-region eats chrome pointer events without a real caption
    move, and SetWindowPos heartbeats can cancel JS ``pywebviewMoveWindow``.
    """
    out: dict = {"ok": False, "hwnd": int(hwnd or 0), "ex_before": 0, "ex_after": 0}
    if not hwnd or not user32.IsWindow(hwnd):
        out["error"] = "bad_hwnd"
        return out
    out["ex_before"] = read_exstyle(hwnd)
    _drag_lock.set()
    try:
        # Chrome must not be click-through when the gesture starts.
        out["ex_cleared"] = clear_transparent_bits(hwnd)
        user32.ReleaseCapture()
        # Cross-thread SendMessage: UI thread runs DefWindowProc move loop
        # until LMB up; calling thread blocks for the duration.
        user32.SendMessageW(
            wintypes.HWND(hwnd),
            WM_NCLBUTTONDOWN,
            HTCAPTION,
            0,
        )
        out["ok"] = True
    except Exception as e:
        out["error"] = str(e)
    finally:
        out["ex_after"] = read_exstyle(hwnd)
        _drag_lock.clear()
    return out


def set_topmost(hwnd: int, *, force: bool = False) -> None:
    """Force HWND_TOPMOST + WS_EX_TOPMOST (Hearthstone-box always-on-top).

    Routine heartbeats must not call SetWindowPos while the user is dragging:
    after the x64 HWND_TOPMOST fix, SetWindowPos actually succeeds and a 1Hz
    (or faster) reassert with SWP_NOMOVE cancels caption moves. Skip while a
    drag session / LMB is down unless force=True (explicit style settle).
    force=True is still refused during an active native caption drag.
    """
    if not hwnd or not user32.IsWindow(hwnd):
        return
    if _drag_lock.is_set():
        return
    if not force and left_button_down():
        return
    # SetWindowLong* often clears the TOPMOST bit; put it back before Z-order.
    try:
        ex = int(_GetWindowLong(hwnd, GWL_EXSTYLE) or 0)
        if not (ex & WS_EX_TOPMOST):
            _SetWindowLong(hwnd, GWL_EXSTYLE, ex | WS_EX_TOPMOST)
    except Exception:
        pass
    # Z-order only — no SWP_SHOWWINDOW / SWP_FRAMECHANGED (those disrupt drag
    # and NC layout on frameless WebView2 panels).
    user32.SetWindowPos(
        hwnd,
        HWND_TOPMOST,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
    )


def set_layered_alpha(hwnd: int, alpha: int) -> None:
    """alpha 0–255."""
    if not hwnd:
        return
    if _drag_lock.is_set():
        return
    alpha = max(0, min(255, int(alpha)))
    ex = _GetWindowLong(hwnd, GWL_EXSTYLE)
    _SetWindowLong(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED | WS_EX_TOOLWINDOW)
    user32.SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA)
    # SetWindowLong can drop Z-order — reassert always-on-top.
    set_topmost(hwnd, force=True)


def set_click_through(hwnd: int, enabled: bool) -> None:
    if not hwnd:
        return
    # Do not toggle WS_EX_TRANSPARENT mid-drag — that drops mouse capture.
    if drag_in_progress():
        return
    ex = _GetWindowLong(hwnd, GWL_EXSTYLE)
    ex |= WS_EX_LAYERED | WS_EX_TOOLWINDOW
    if enabled:
        ex |= WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
    else:
        ex &= ~WS_EX_TRANSPARENT
        # keep NOACTIVATE optional; clear so buttons work
        ex &= ~WS_EX_NOACTIVATE
    _SetWindowLong(hwnd, GWL_EXSTYLE, ex)
    # Changing WS_EX_* via SetWindowLong often loses HWND_TOPMOST.
    set_topmost(hwnd, force=True)


def cursor_in_window_chrome(hwnd: int, chrome_h: int = 48) -> bool:
    """True if cursor is over the top chrome strip of hwnd (screen coords)."""
    if not hwnd:
        return False
    pt = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(pt)):
        return False
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    if not (rect.left <= pt.x < rect.right and rect.top <= pt.y < rect.bottom):
        return False
    return (pt.y - rect.top) < max(24, int(chrome_h))


def show_noactivate(hwnd: int, visible: bool) -> None:
    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE if visible else SW_HIDE)


class HotkeyPump:
    """Background thread registering global hotkeys via RegisterHotKey."""

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._handlers: dict[int, Callable[[], None]] = {}
        self._tid = 0

    def start(self, bindings: list[tuple[int, int, int, Callable[[], None]]]) -> None:
        """bindings: list of (id, modifiers, vk, callback)."""
        if self._thread and self._thread.is_alive():
            return

        def run():
            self._tid = threading.get_ident()
            for hid, mods, vk, cb in bindings:
                ok = user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk)
                if ok:
                    self._handlers[hid] = cb
            msg = wintypes.MSG()
            while not self._stop.is_set():
                r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r == 0 or r == -1:
                    break
                if msg.message == WM_HOTKEY:
                    cb = self._handlers.get(int(msg.wParam))
                    if cb:
                        try:
                            cb()
                        except Exception:
                            pass
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            for hid in list(self._handlers):
                user32.UnregisterHotKey(None, hid)
            self._handlers.clear()

        self._stop.clear()
        self._thread = threading.Thread(target=run, name="weishu-hotkeys", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._tid:
            user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)  # WM_QUIT


# --- Game key injection (enemy magnifier W) ---------------------------------

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
VK_W = 0x57
VK_ESCAPE = 0x1B
MAPVK_VK_TO_VSC = 0
SM_CXSCREEN = 0
SM_CYSCREEN = 1

# Overlay / chrome titles we must never treat as the game client.
_OVERLAY_TITLE_MARKERS = ("卫戍盒子", "weishu-box", "Cursor", "Visual Studio Code")


ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", INPUT_UNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


def _is_overlay_title(title: str) -> bool:
    t = title or ""
    return any(m in t for m in _OVERLAY_TITLE_MARKERS)


def find_game_hwnd(
    title_substrings: tuple[str, ...] = ("明日方舟", "Arknights", "arknights"),
) -> Optional[int]:
    """Best-effort: visible top-level window whose title looks like the client."""
    matches: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _lp):  # type: ignore[no-untyped-def]
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value or ""
        if not title or _is_overlay_title(title):
            return True
        low = title.lower()
        for sub in title_substrings:
            if sub.lower() in low:
                matches.append((int(hwnd), title))
                break
        return True

    user32.EnumWindows(_enum, 0)
    if not matches:
        return None
    # Prefer the largest client area (game usually fullscreen / big).
    best = matches[0][0]
    best_area = -1
    for hwnd, _title in matches:
        rc = wintypes.RECT()
        if user32.GetClientRect(hwnd, ctypes.byref(rc)):
            area = max(0, rc.right - rc.left) * max(0, rc.bottom - rc.top)
            if area > best_area:
                best_area = area
                best = hwnd
    return best


def focus_hwnd(hwnd: int) -> bool:
    """Bring hwnd to foreground so the next SendInput lands in-game."""
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    kernel32 = ctypes.windll.kernel32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    fg = user32.GetForegroundWindow()
    if int(fg or 0) == int(hwnd):
        return True
    cur_tid = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    tgt_tid = user32.GetWindowThreadProcessId(hwnd, None)
    attached_fg = False
    attached_tgt = False
    try:
        if fg and fg_tid and fg_tid != cur_tid:
            attached_fg = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
        if tgt_tid and tgt_tid != cur_tid:
            attached_tgt = bool(user32.AttachThreadInput(cur_tid, tgt_tid, True))
        user32.BringWindowToTop(hwnd)
        ok = bool(user32.SetForegroundWindow(hwnd))
        # Fallback: briefly topmost-toggle without stealing permanently.
        if not ok:
            user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
            )
            user32.SetWindowPos(
                hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
            )
            ok = bool(user32.SetForegroundWindow(hwnd))
        return ok or int(user32.GetForegroundWindow() or 0) == int(hwnd)
    finally:
        if attached_tgt and tgt_tid:
            user32.AttachThreadInput(cur_tid, tgt_tid, False)
        if attached_fg and fg_tid:
            user32.AttachThreadInput(cur_tid, fg_tid, False)


def tap_vk(vk: int) -> bool:
    """Physical key tap via SendInput (goes to current foreground window)."""
    scan = int(user32.MapVirtualKeyW(int(vk) & 0xFF, MAPVK_VK_TO_VSC) or 0)

    def _one(flags: int) -> INPUT:
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        # Prefer scancode when available so games that ignore virtual-key still see it.
        use_scan = bool(scan)
        inp.u.ki = KEYBDINPUT(
            wVk=0 if use_scan else (int(vk) & 0xFFFF),
            wScan=(scan & 0xFFFF) if use_scan else 0,
            dwFlags=(flags | KEYEVENTF_SCANCODE) if use_scan else flags,
            time=0,
            dwExtraInfo=ULONG_PTR(0),
        )
        return inp

    down = _one(0)
    up = _one(KEYEVENTF_KEYUP)
    arr = (INPUT * 2)(down, up)
    n = user32.SendInput(2, arr, ctypes.sizeof(INPUT))
    return int(n) == 2


def open_enemy_magnifier(
    *,
    key: str = "W",
    wait_s: float = 0.5,
    title_substrings: tuple[str, ...] = ("明日方舟", "Arknights", "arknights"),
) -> dict:
    """Focus game client, tap magnifier key, wait for panel paint.

    Leaves the panel open (a second W would toggle-close only if the first
    successfully opened it — unsafe if already open). Overlay windows stay
    always-on-top; we only steal foreground briefly for the keystroke.
    """
    import time as _time

    vk = VK_W if str(key).upper() == "W" else ord(str(key).upper()[0])
    hwnd = find_game_hwnd(title_substrings)
    focused = False
    note = ""
    if hwnd:
        focused = focus_hwnd(hwnd)
        if not focused:
            note = "game found but SetForeground failed; SendInput may miss"
    else:
        note = "game window not found by title; SendInput to current foreground"
    tapped = tap_vk(vk)
    _time.sleep(max(0.0, float(wait_s)))
    return {
        "ok": bool(tapped),
        "hwnd": int(hwnd) if hwnd else None,
        "focused": bool(focused),
        "key": str(key).upper(),
        "wait_s": float(wait_s),
        "tapped": bool(tapped),
        "close_after": False,
        "note": note
        or "magnifier left open (no second W — toggle is unsafe if already open)",
    }


def _abs_mouse(x: int, y: int) -> Tuple[int, int]:
    """Map physical pixels → SendInput absolute 0..65535 (primary virtual screen)."""
    sw = max(1, int(user32.GetSystemMetrics(SM_CXSCREEN)))
    sh = max(1, int(user32.GetSystemMetrics(SM_CYSCREEN)))
    ax = int(round(x * 65535.0 / max(1, sw - 1)))
    ay = int(round(y * 65535.0 / max(1, sh - 1)))
    return max(0, min(65535, ax)), max(0, min(65535, ay))


def left_click(
    x: int,
    y: int,
    *,
    allowed: Optional[Callable[[int, int], bool]] = None,
) -> dict:
    """Single left-click at physical screen pixels via SendInput.

    Read-only recognition only — no drag / right-click / double-click.
    When ``allowed`` is set, refuse coordinates outside that predicate
    (hard ROI gate for board/bench clicks).
    """
    xi, yi = int(x), int(y)
    if allowed is not None and not allowed(xi, yi):
        return {
            "ok": False,
            "error": "click rejected: outside allowed ROI",
            "x": xi,
            "y": yi,
        }
    ax, ay = _abs_mouse(xi, yi)

    def _mi(flags: int) -> INPUT:
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.u.mi = MOUSEINPUT(
            dx=ax if (flags & MOUSEEVENTF_ABSOLUTE) else 0,
            dy=ay if (flags & MOUSEEVENTF_ABSOLUTE) else 0,
            mouseData=0,
            dwFlags=flags,
            time=0,
            dwExtraInfo=ULONG_PTR(0),
        )
        return inp

    move = _mi(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)
    down = _mi(MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE)
    up = _mi(MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE)
    arr = (INPUT * 3)(move, down, up)
    n = user32.SendInput(3, arr, ctypes.sizeof(INPUT))
    return {
        "ok": int(n) == 3,
        "x": xi,
        "y": yi,
        "sent": int(n),
    }


def tap_escape() -> bool:
    """ESC — preferred panel close (read-only; no UI button click)."""
    return tap_vk(VK_ESCAPE)


def focus_game_for_input(
    title_substrings: tuple[str, ...] = ("明日方舟", "Arknights", "arknights"),
) -> dict:
    """Focus game client before click / ESC (same discover path as 读敌人)."""
    hwnd = find_game_hwnd(title_substrings)
    focused = False
    note = ""
    if hwnd:
        focused = focus_hwnd(hwnd)
        if not focused:
            note = "game found but SetForeground failed"
    else:
        note = "game window not found by title"
    return {
        "ok": bool(hwnd),
        "hwnd": int(hwnd) if hwnd else None,
        "focused": bool(focused),
        "note": note,
    }
