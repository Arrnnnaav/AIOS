"""One coordinate space for windows, hints, and screen capture.

Why this exists (see D013 in DECISIONS.md).

On a display with Windows scaling enabled (125% on this machine) the screen
has two sizes: 1536x864 logical and 1920x1080 physical. Which one the Win32
APIs report depends on whether the process has declared DPI awareness — and
that is a *one-way switch that can flip underneath you mid-run*:

    metrics at process start      -> 1536 x 864     (unaware)
    after SetProcessDPIAware()    -> 1920 x 1080    (aware)

The trap is that python-mss calls SetProcessDPIAware() itself when it
initialises. So simply taking a screenshot silently changes what
GetSystemMetrics returns for the rest of the process's life. A window created
before that first screenshot is sized in logical pixels and ends up covering
only 64% of the screen; an identical call after it covers all of it. That
inconsistency is what made a working overlay look like a broken one, and it
is invisible in the code — the same function returns different numbers
depending on whether anything has grabbed a frame yet.

Note that the modern SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)
returns 0 (failure) on this machine even as the very first call in the
process, so the older SetProcessDPIAware() is the one that actually works
here. Both are attempted, newest first.

The same trap applies to *observing* from outside: querying GetWindowRect on
these windows from a separate, DPI-unaware Python process reports 1536x864 for
a window that is genuinely 1920x1080, because the answer is scaled for the
caller. Any diagnostic script that inspects the overlay must import this module
too, or it will report confidently wrong numbers.

Fix: declare awareness once, at import, before any window is created and
before mss ever runs. Importing this module is what guarantees the ordering,
so overlay code imports it even when it only needs the geometry helpers.
At 100% scaling none of this changes any number.
"""

import ctypes

import win32api
import win32con

_HORZRES = 8
_DESKTOPHORZRES = 118

_PER_MONITOR_AWARE_V2 = -4


def _ensure_dpi_awareness() -> str:
    """Declare DPI awareness. Idempotent, and safe to call late — but calling
    it late defeats the point, so this runs at import."""
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(_PER_MONITOR_AWARE_V2):
            return "per-monitor-v2"
    except AttributeError:
        pass  # pre-Windows 10 1703
    # Returns 0 if awareness was already set, which is fine either way.
    ctypes.windll.user32.SetProcessDPIAware()
    return "system"


AWARENESS = _ensure_dpi_awareness()


def scale_factor() -> float:
    """Physical pixels per logical pixel — 1.25 at 125% scaling, 1.0 at 100%.

    Diagnostic only: once awareness is declared, everything already reports
    physical pixels and nothing needs converting.
    """
    hdc = ctypes.windll.user32.GetDC(0)
    try:
        logical = ctypes.windll.gdi32.GetDeviceCaps(hdc, _HORZRES)
        physical = ctypes.windll.gdi32.GetDeviceCaps(hdc, _DESKTOPHORZRES)
    finally:
        ctypes.windll.user32.ReleaseDC(0, hdc)
    return physical / logical if logical else 1.0


def virtual_screen_rect() -> tuple[int, int, int, int]:
    """(left, top, width, height) of the whole virtual desktop, spanning every
    monitor. Physical pixels, because awareness is declared at import."""
    return (
        win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN),
        win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN),
        win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN),
        win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN),
    )


def capture_region() -> dict[str, int]:
    """An mss grab region covering the whole desktop, in the same coordinate
    space as virtual_screen_rect(). Use instead of mss.monitors[1], which
    covers only the primary monitor."""
    left, top, width, height = virtual_screen_rect()
    return {"left": left, "top": top, "width": width, "height": height}
