"""A small badge beside the user's own pointer saying what Orbyn is doing
(Listening, Thinking, Researching...), as HeyClicky's cursor companion does.

It follows the operating system's cursor position, never a model-supplied
point, and points at nothing, so rule 3 is untouched. It is click-through,
topmost, never activated and excluded from screen capture (so perception and
the D179 picture never see it). It draws only in WM_PAINT; its timer moves
the window and invalidates (rule 4). It shows only while Orbyn is busy or
listening, and the island hides it when a full-screen app is in front."""

from __future__ import annotations

import ghostcursor.overlay.dpi  # noqa: F401  (rule 4: before any overlay)

import ctypes
import math
import time
from ctypes import wintypes

import win32api
import win32con
import win32gui

from ghostcursor.overlay.window import COLOR_KEY, ensure_class

CLASS = "OrbynCompanion"
OFFSET = (18, 22)  # below-right of the arrow's hotspot, clear of the arrow
SIZE = (132, 28)
TIMER_ID, TIMER_MS = 9, 30
WDA_EXCLUDEFROMCAPTURE = 0x11
BG = win32api.RGB(22, 26, 34)
TEXT = win32api.RGB(249, 247, 242)
AMBER = win32api.RGB(239, 182, 96)
BLUE = win32api.RGB(64, 156, 235)
#: Click-through, always on top, never in Alt+Tab, never takes focus.
EX_STYLE = (
    win32con.WS_EX_LAYERED
    | win32con.WS_EX_TRANSPARENT
    | win32con.WS_EX_TOPMOST
    | win32con.WS_EX_TOOLWINDOW
    | win32con.WS_EX_NOACTIVATE
)
_windows: dict[int, "Companion"] = {}
_brushes: dict[int, int] = {}
_font = None

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SetTimer.argtypes = (
    wintypes.HWND,
    ctypes.c_size_t,
    wintypes.UINT,
    ctypes.c_void_p,
)
_user32.SetTimer.restype = ctypes.c_size_t
_user32.KillTimer.argtypes = (wintypes.HWND, ctypes.c_size_t)
_user32.KillTimer.restype = wintypes.BOOL


def label(app, listener, *, fullscreen=False) -> str | None:
    """What the badge says, or None to hide it. Generic state only: the
    busy label when it is one of the app's own activity names, never a goal.
    Hidden over a full-screen app, game or presentation."""

    from ghostcursor.workspace.app import ACTIVITY_LABELS

    if fullscreen:
        return None
    if listener is not None and (
        listener.held is not None or listener.clock() < listener.armed_until
    ):
        return "Listening"
    if not app.busy:
        return None
    return app.busy if app.busy in ACTIVITY_LABELS else "Working"


def placement(cursor, size, work):
    """Top-left of the badge: below-right of the pointer, flipped to the other
    side of it at the right or bottom edge of the work area."""

    (x, y), (width, height), (left, top, right, bottom) = cursor, size, work
    px, py = x + OFFSET[0], y + OFFSET[1]
    if px + width > right:
        px = x - OFFSET[0] - width
    if py + height > bottom:
        py = y - OFFSET[1] - height
    return max(left, px), max(top, py)


def pulse(elapsed: float) -> float:
    """0..1, one breath every 1.2 s."""

    return 0.5 - 0.5 * math.cos(elapsed * 2 * math.pi / 1.2)


def _brush(color):
    if color not in _brushes:
        _brushes[color] = win32gui.CreateSolidBrush(color)
    return _brushes[color]


class Companion:
    def __init__(self, cursor):
        global _font
        self.cursor = cursor  # () -> (x, y): the OS pointer, never a model point
        self.text: str | None = None
        self.started = time.monotonic()
        self.at = None
        if _font is None:
            font = win32gui.LOGFONT()
            font.lfHeight, font.lfWeight, font.lfFaceName = -13, 600, "Segoe UI"
            _font = win32gui.CreateFontIndirect(font)
        ensure_class(CLASS, _wnd_proc, _brush(COLOR_KEY))
        self.hwnd = win32gui.CreateWindowEx(
            EX_STYLE,
            CLASS,
            "Orbyn companion",
            win32con.WS_POPUP,
            0,
            0,
            *SIZE,
            None,
            None,
            win32api.GetModuleHandle(None),
            None,
        )
        win32gui.SetLayeredWindowAttributes(
            self.hwnd, COLOR_KEY, 0, win32con.LWA_COLORKEY
        )
        _user32.SetWindowDisplayAffinity(
            self.hwnd, WDA_EXCLUDEFROMCAPTURE
        )  # best effort
        _windows[self.hwnd] = self

    def show(self, text: str | None) -> None:
        """Called on the UI thread each island tick."""

        if text == self.text:
            return
        if text is None:
            _user32.KillTimer(self.hwnd, TIMER_ID)
            win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
        elif self.text is None:
            self.started = time.monotonic()
            self.follow()
            win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
            _user32.SetTimer(self.hwnd, TIMER_ID, TIMER_MS, None)
        self.text = text
        win32gui.InvalidateRect(self.hwnd, None, True)

    def follow(self) -> None:
        try:
            cursor = self.cursor()
            monitor = win32api.MonitorFromPoint(
                cursor, win32con.MONITOR_DEFAULTTONEAREST
            )
            work = win32api.GetMonitorInfo(monitor)["Work"]
        except Exception:
            return  # secure desktop or no pointer: stay where it was
        at = placement(cursor, SIZE, work)
        if at != self.at:
            self.at = at
            win32gui.SetWindowPos(
                self.hwnd,
                win32con.HWND_TOPMOST,
                *at,
                0,
                0,
                win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
            )

    def destroy(self) -> None:
        if win32gui.IsWindow(self.hwnd):
            win32gui.DestroyWindow(self.hwnd)


def _paint(companion, hdc) -> None:
    width, height = SIZE
    win32gui.FillRect(hdc, (0, 0, width, height), _brush(COLOR_KEY))
    if not companion.text:
        return
    old_font = win32gui.SelectObject(hdc, _font)
    text_width = win32gui.GetTextExtentPoint32(hdc, companion.text)[0]
    right = min(width, 30 + text_width + 12)
    old_brush = win32gui.SelectObject(hdc, _brush(BG))
    old_pen = win32gui.SelectObject(hdc, win32gui.GetStockObject(win32con.NULL_PEN))
    win32gui.RoundRect(hdc, 0, 0, right, height, height, height)
    color = BLUE if companion.text == "Listening" else AMBER
    r = 4 + round(2 * pulse(time.monotonic() - companion.started))
    win32gui.SelectObject(hdc, _brush(color))
    win32gui.Ellipse(hdc, 15 - r, 14 - r, 15 + r, 14 + r)
    win32gui.SelectObject(hdc, old_pen)
    win32gui.SelectObject(hdc, old_brush)
    win32gui.SetBkMode(hdc, win32con.TRANSPARENT)
    win32gui.SetTextColor(hdc, TEXT)
    win32gui.DrawText(
        hdc,
        companion.text,
        -1,
        (28, 0, right - 8, height),
        win32con.DT_SINGLELINE | win32con.DT_VCENTER | win32con.DT_END_ELLIPSIS,
    )
    win32gui.SelectObject(hdc, old_font)


def _wnd_proc(hwnd, msg, wparam, lparam):
    companion = _windows.get(hwnd)
    if msg == win32con.WM_PAINT:
        hdc, paint = win32gui.BeginPaint(hwnd)
        if companion is not None:
            _paint(companion, hdc)
        win32gui.EndPaint(hwnd, paint)
        return 0
    if msg == win32con.WM_ERASEBKGND:
        return 1  # WM_PAINT fills every pixel; no flash between frames
    if msg == win32con.WM_TIMER and wparam == TIMER_ID and companion is not None:
        companion.follow()
        win32gui.InvalidateRect(hwnd, None, False)
        return 0
    if msg == win32con.WM_DESTROY:
        _user32.KillTimer(hwnd, TIMER_ID)
        _windows.pop(hwnd, None)
        return 0
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
