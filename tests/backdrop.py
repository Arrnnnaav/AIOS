"""An opaque, solid-colour, full-screen window used as a test backdrop.

The overlay's whole job is to be invisible except where it draws. Verifying
that against the live desktop is unreliable — the desktop changes on its own
(clocks, carets, scrolling terminals), which shows up as false differences.

So tests paint a known solid colour across the screen first, put the overlay
on top of it, and assert the screenshot is still that colour everywhere except
the hint. Any pixel that is neither the backdrop colour nor the hint means the
overlay is obscuring something.

Topmost so the backdrop is not occluded by windows already open on the desktop.
A non-topmost backdrop can be hidden by user windows, which silently invalidates
all assertions made against it. The overlay, created after the backdrop, still
composites above it because among topmost windows the more recently shown one
renders on top.
"""

import win32api
import win32con
import win32gui

from ghostcursor.overlay import dpi

BACKDROP_COLOR = win32api.RGB(0, 128, 0)
BACKDROP_BGR = (0, 128, 0)  # as sampled from a screenshot (B, G, R)

_CLASS_NAME = "GhostCursorTestBackdrop"
_brush = None
_registered = False


def _wnd_proc(hwnd, msg, wparam, lparam):
    if msg == win32con.WM_PAINT:
        hdc, ps = win32gui.BeginPaint(hwnd)
        win32gui.FillRect(hdc, win32gui.GetClientRect(hwnd), _brush)
        win32gui.EndPaint(hwnd, ps)
        return 0
    if msg == win32con.WM_ERASEBKGND:
        return 1
    if msg == win32con.WM_DESTROY:
        return 0
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


def create_backdrop(
    rect: tuple[int, int, int, int] | None = None, title: str | None = None
) -> int:
    """Full-screen by default. Pass rect=(left, top, width, height) and a
    title to instead create a smaller window that acts as a *target* for the
    perception layer to find."""
    global _brush, _registered

    h_instance = win32api.GetModuleHandle(None)
    if _brush is None:
        _brush = win32gui.CreateSolidBrush(BACKDROP_COLOR)

    if not _registered:
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = _wnd_proc
        wc.hInstance = h_instance
        wc.lpszClassName = _CLASS_NAME
        wc.hbrBackground = _brush
        win32gui.RegisterClass(wc)
        _registered = True

    left, top, width, height = rect if rect else dpi.virtual_screen_rect()

    hwnd = win32gui.CreateWindowEx(
        win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TOPMOST,
        _CLASS_NAME,
        title or "GhostCursorTestBackdrop",
        win32con.WS_POPUP,
        left,
        top,
        width,
        height,
        None,
        None,
        h_instance,
        None,
    )
    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
    win32gui.UpdateWindow(hwnd)
    return hwnd


def destroy_backdrop(hwnd: int) -> None:
    try:
        win32gui.DestroyWindow(hwnd)
    except win32gui.error:
        pass
    win32gui.PumpWaitingMessages()
