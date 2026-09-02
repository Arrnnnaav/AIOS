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
returns 0 (failure) here even as the very first call in the process, so the
older SetProcessDPIAware() is the one that takes effect and this process runs
SYSTEM aware, not per-monitor-v2.

That failure was originally attributed to the machine. It is not: the call is
made with a plain Python int, which ctypes marshals as a 32-bit C int, while
the parameter is a pointer-sized DPI_AWARENESS_CONTEXT handle. Measured on
2 September 2026, same machine, first call in a fresh process --
`SetProcessDpiAwarenessContext(-4)` returns 0 with GetLastError 87
(ERROR_INVALID_PARAMETER), and `SetProcessDpiAwarenessContext(c_void_p(-4))`
returns True and leaves the process per-monitor-v2.

The call is left as it is on purpose. Correcting it would change the
coordinate space every window, UIA rect, hint and capture in this project
shares, and D010 exists because changing that silently is how a working
overlay starts reporting confidently wrong numbers. On this desktop -- one
monitor at 100% -- system and per-monitor-v2 are indistinguishable, so the
pixel lane here could not validate the change either; it needs a scaled or
mixed-DPI display. Recorded in docs/superpowers/FOLLOWUPS.md with the
measurement, to be changed by its own reviewed decision rather than as a side
effect of adding a contract.

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
import ctypes.wintypes as wintypes

import win32api
import win32con

_HORZRES = 8
_DESKTOPHORZRES = 118

_PER_MONITOR_AWARE_V2 = -4


def _ensure_dpi_awareness() -> str:
    """Declare DPI awareness. Idempotent, and safe to call late — but calling
    it late defeats the point, so this runs at import."""
    try:
        # Deliberately called with an undeclared signature and a plain int.
        # Declaring it is the fix, and the fix changes this project's
        # coordinate space -- see the module docstring and FOLLOWUPS.md.
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


#: What a Win32 desktop coordinate MEANS under each awareness mode. Only a
#: per-monitor-aware process is handed true physical pixels on every monitor;
#: a system-aware one is handed the system-DPI space, which coincides with
#: physical pixels only while every display runs at the system DPI.
_UNITS_FOR_AWARENESS = {
    "per-monitor-v2": "physical_pixels",
    "per-monitor": "physical_pixels",
    "system": "system_dpi_pixels",
    "unaware": "logical_pixels",
    "unaware-gdi-scaled": "gdi_scaled_pixels",
}


def units_for_awareness(awareness: str) -> str:
    """The unit a process in ``awareness`` reports coordinates in.

    Pure, so a caller that has already measured awareness derives units from
    that exact value rather than querying a second time and risking two reads
    that disagree.
    """

    return _UNITS_FOR_AWARENESS.get(awareness, UNKNOWN_AWARENESS)


def coordinate_units() -> str:
    """The unit this process's Win32 coordinates are actually in."""

    awareness, _api = queried_thread_awareness()
    return units_for_awareness(awareness)


def virtual_screen_rect() -> tuple[int, int, int, int]:
    """(left, top, width, height) of the whole virtual desktop, spanning every
    monitor.

    In whatever unit this process's awareness makes Win32 report -- see
    `coordinate_units()`. On a per-monitor-aware process that is physical
    pixels; this process is system-aware (the setter above does not take
    effect), so it is the system-DPI space, which equals physical pixels only
    while every display runs at the system DPI. It does on the desktop this
    was measured on, which is why the distinction went unnoticed."""
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


# --- queried awareness -----------------------------------------------------
#
# `AWARENESS` above records which SETTER PATH ran, not what the process ended
# up as. Awareness cannot be changed once set, so a process where something
# already declared it -- mss does exactly this, see the module docstring --
# falls through and reports "system" whatever it actually is. Two processes
# can therefore report identical labels while occupying different coordinate
# spaces, which is precisely the comparison a cross-process geometry contract
# must not be built on.
#
# Everything below QUERIES the live state instead, and reports which API
# answered so a fallback is visible rather than silent.

def _declare_signatures() -> None:
    """Give every DPI query its real Win32 signature before it is called.

    ctypes defaults an undeclared function's return type to C `int` -- four
    bytes -- while `DPI_AWARENESS_CONTEXT` is an opaque pointer-sized handle,
    and undeclared integer arguments are marshalled 32-bit wide. That is the
    same ABI mistake this module already documents in the SETTER, where it
    makes `SetProcessDpiAwarenessContext` fail outright.

    It is latent rather than visible here: measured on this machine the thread
    context handle is 0x6010, small enough to survive truncation, so the
    comparisons happen to be right. On a build where the handle is a genuine
    pointer above 4 GB it would truncate, `AreDpiAwarenessContextsEqual` would
    match nothing, and every query would report `unknown` -- refusing all
    geometry rather than misplacing it, but for a reason that has nothing to
    do with the desktop.

    The two BOOL-returning functions use `wintypes.BOOL`, not `c_bool`. Win32
    BOOL is a 32-bit int and may hold ANY non-zero value for true, while
    `c_bool` is C `_Bool` -- one byte -- so a return whose low byte is zero and
    whose upper bytes are not would read as False.

    `SetProcessDpiAwarenessContext` is deliberately NOT declared here.
    Declaring it is precisely what makes the call succeed, which would switch
    this process to per-monitor-v2 and silently change the coordinate space
    every window rect, UIA rect, hint and capture shares. That change belongs
    to its own reviewed decision with a scaled display to validate it, not to
    a signature cleanup. See FOLLOWUPS.md.
    """

    user32 = ctypes.windll.user32
    for name, argtypes, restype in (
        ("GetThreadDpiAwarenessContext", [], ctypes.c_void_p),
        ("GetWindowDpiAwarenessContext", [ctypes.c_void_p], ctypes.c_void_p),
        ("GetDpiAwarenessContextForProcess", [ctypes.c_void_p], ctypes.c_void_p),
        (
            "AreDpiAwarenessContextsEqual",
            [ctypes.c_void_p, ctypes.c_void_p],
            wintypes.BOOL,
        ),
        ("IsProcessDPIAware", [], wintypes.BOOL),
    ):
        function = getattr(user32, name, None)
        if function is not None:
            function.argtypes = argtypes
            function.restype = restype
    try:
        shcore = ctypes.windll.shcore
    except (AttributeError, OSError):
        return
    function = getattr(shcore, "GetProcessDpiAwareness", None)
    if function is not None:
        function.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        function.restype = ctypes.c_long


_declare_signatures()


#: DPI_AWARENESS_CONTEXT sentinel values, as documented for the high-DPI API.
_CONTEXTS = {
    -1: "unaware",
    -2: "system",
    -3: "per-monitor",
    -4: "per-monitor-v2",
    -5: "unaware-gdi-scaled",
}

#: Returned when no API on this machine could answer. It is NOT a value that
#: can match another process: an unknown coordinate space is refused, never
#: assumed compatible.
UNKNOWN_AWARENESS = "unknown"

#: Every value an awareness field may canonically hold. A contract that
#: accepted an arbitrary string would let a peer name a coordinate space that
#: does not exist and have it compare equal to itself.
AWARENESS_VALUES = frozenset(
    {"unaware", "system", "per-monitor", "per-monitor-v2", "unaware-gdi-scaled"}
) | {UNKNOWN_AWARENESS}


def _canonical_context(handle) -> str | None:
    """Name a DPI_AWARENESS_CONTEXT by comparing it with the known sentinels.

    Compared with `AreDpiAwarenessContextsEqual` rather than by numeric
    identity: the handle is opaque and a process may hold an equivalent
    context that is not one of the sentinel pointers.
    """
    user32 = ctypes.windll.user32
    for value, name in _CONTEXTS.items():
        try:
            if user32.AreDpiAwarenessContextsEqual(handle, ctypes.c_void_p(value)):
                return name
        except AttributeError:
            return None
    return None


def _legacy_awareness() -> tuple[str, str] | None:
    """Older-platform fallbacks, in decreasing order of precision."""
    try:
        awareness = ctypes.c_int()
        if ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(awareness)) == 0:
            return (
                {0: "unaware", 1: "system", 2: "per-monitor"}.get(
                    awareness.value, UNKNOWN_AWARENESS
                ),
                "GetProcessDpiAwareness",
            )
    except (AttributeError, OSError):
        pass
    try:
        return (
            "system" if ctypes.windll.user32.IsProcessDPIAware() else "unaware",
            "IsProcessDPIAware",
        )
    except (AttributeError, OSError):
        return None


def queried_thread_awareness() -> tuple[str, str]:
    """The calling THREAD's actual awareness, and the API that answered."""
    try:
        handle = ctypes.windll.user32.GetThreadDpiAwarenessContext()
        name = _canonical_context(handle)
        if name is not None:
            return name, "GetThreadDpiAwarenessContext"
    except (AttributeError, OSError):
        pass
    legacy = _legacy_awareness()
    return legacy if legacy is not None else (UNKNOWN_AWARENESS, "none")


def queried_window_awareness(hwnd: int) -> tuple[str, str]:
    """The awareness a specific WINDOW was created under.

    A window keeps the awareness of the thread that created it, so this can
    disagree with the current thread even inside one process.
    """
    try:
        handle = ctypes.windll.user32.GetWindowDpiAwarenessContext(hwnd)
        name = _canonical_context(handle)
        if name is not None:
            return name, "GetWindowDpiAwarenessContext"
    except (AttributeError, OSError):
        pass
    return UNKNOWN_AWARENESS, "none"


def queried_process_awareness() -> tuple[str, str]:
    """The process DEFAULT, for diagnostics.

    Threads inherit this unless something calls SetThreadDpiAwarenessContext,
    which GhostCursor never does -- so a disagreement between this and
    `queried_thread_awareness()` means a third-party library changed it, and
    that is a finding rather than a detail.
    """
    try:
        handle = ctypes.windll.user32.GetDpiAwarenessContextForProcess(None)
        name = _canonical_context(handle)
        if name is not None:
            return name, "GetDpiAwarenessContextForProcess"
    except (AttributeError, OSError):
        pass
    legacy = _legacy_awareness()
    return legacy if legacy is not None else (UNKNOWN_AWARENESS, "none")


def monitor_topology() -> tuple[tuple[int, int, int, int], ...]:
    """Every monitor rectangle, ordered, in the virtual-desktop space.

    Sorted rather than enumeration-ordered so two processes observing the same
    desktop produce the same tuple; enumeration order is not guaranteed stable
    between processes and an order difference is not a coordinate-space
    difference.
    """
    rects = [
        (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
        for _handle, _dc, rect in win32api.EnumDisplayMonitors()
    ]
    return tuple(sorted(rects))
