"""The control bar: a second, FOCUSABLE window beside the click-through overlay.

The overlay is WS_EX_TRANSPARENT | WS_EX_NOACTIVATE and must never take focus
or receive a click (D006, D009) -- which is exactly why it cannot carry its own
Stop button. This window is its deliberate inverse: it receives clicks, it can
take focus, and it is small and edge-positioned so it never covers the region a
hint might occupy.

It exists primarily as a SAFETY affordance. ESC is otherwise the only way out of
a full-screen topmost overlay and nothing on screen says so.
"""

from __future__ import annotations

import win32api
import win32con
import win32gui

from ghostcursor.overlay import dpi
from ghostcursor.overlay.window import ensure_class, pump_messages_nonblocking

BAR_CLASS_NAME = "GhostCursorBar"
BAR_BG = win32api.RGB(28, 28, 34)

#: Edge inset and size, in physical pixels.
_BAR_WIDTH = 520
_BAR_HEIGHT = 56
_BAR_MARGIN = 24

_bar_brush = None


def _bar_wnd_proc(hwnd, msg, wparam, lparam):
    """The bar's own procedure.

    Deliberately does NOT call PostQuitMessage on WM_DESTROY, unlike the
    overlay's. The overlay is destroyed once, at exit, so ending the thread's
    message loop there is right. The bar can be destroyed while the tour is
    still running, and posting WM_QUIT would take the tour's own loop down
    with it.
    """
    if msg == win32con.WM_DESTROY:
        return 0
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


def create_bar_window() -> int:
    """Create the control bar, bottom-centre of the primary monitor."""
    global _bar_brush
    if _bar_brush is None:
        _bar_brush = win32gui.CreateSolidBrush(BAR_BG)

    ensure_class(BAR_CLASS_NAME, _bar_wnd_proc, _bar_brush)

    left, top, width, height = dpi.virtual_screen_rect()
    x = left + (width - _BAR_WIDTH) // 2
    y = top + height - _BAR_HEIGHT - _BAR_MARGIN

    ex_style = win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW

    hwnd = win32gui.CreateWindowEx(
        ex_style,
        BAR_CLASS_NAME,
        "Ghost Cursor",
        win32con.WS_POPUP,
        x,
        y,
        _BAR_WIDTH,
        _BAR_HEIGHT,
        None,
        None,
        win32api.GetModuleHandle(None),
        None,
    )
    # SW_SHOWNOACTIVATE: appear without stealing focus from the app the user
    # is working in. The bar CAN take focus later, when the user clicks it --
    # it just must not grab it merely by existing.
    win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
    win32gui.UpdateWindow(hwnd)
    return hwnd


def destroy_bar_window(hwnd: int) -> None:
    """Tear the bar down. Safe to call twice."""
    try:
        win32gui.DestroyWindow(hwnd)
    except win32gui.error:
        pass
    pump_messages_nonblocking()
