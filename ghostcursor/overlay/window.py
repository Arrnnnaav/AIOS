"""Click-through, always-on-top Win32 overlay that draws hint shapes.

Reference: D:\\tracker\\docs\\ghostcursor\\win32-layered-transparent-overlay-windows-ws-ex-layered-ws-ex-transparent.docx,
D:\\tracker\\docs\\ghostcursor\\windows-gdi-real-time-overlay-drawing-primitives.docx

Safety boundary (see D006 in DECISIONS.md): this module only ever draws pixels.
It never calls SendInput/mouse_event and never moves the real OS cursor.

Painting model (see D012): all drawing happens inside WM_PAINT. The handler
first fills the entire client area with the colorkey colour (making it
transparent) and then draws the current hint on top. Callers never draw
directly — they call set_hint()/clear_hint(), which update state and
invalidate the window. Drawing outside WM_PAINT leaves the window surface
uninitialised, which renders as opaque garbage covering the screen.
"""

import win32api
import win32con
import win32gui

from ghostcursor.overlay import dpi

# Colour that SetLayeredWindowAttributes makes fully transparent. Any pixel
# painted in this exact colour disappears; everything else is opaque.
COLOR_KEY = win32api.RGB(255, 0, 255)
RING_COLOR = win32api.RGB(0, 200, 255)
#: A hint we can no longer confirm. Same ring, visibly muted — the user keeps
#: their guidance and can see it may be out of date (see reasoning/staleness).
DIMMED_RING_COLOR = win32api.RGB(0, 90, 115)
#: Amber. Deliberately a different HUE from the cyan family, not a dimmer
#: shade of it: DIMMED already means "possibly out of date", and INFERRED means
#: "possibly misread". A user who cannot tell those apart cannot calibrate
#: trust, which is what D006 depends on.
INFERRED_RING_COLOR = win32api.RGB(255, 170, 0)
RING_THICKNESS = 3
#: Act cue ring, drawn around the whole control rather than as a small dot.
CUE_RING_THICKNESS = 2
#: Label text and its plate. The plate is near-black rather than the cue
#: colour: white-on-cyan at 12px is unreadable, and a label nobody can read
#: is a label that is not there.
LABEL_TEXT_COLOR = win32api.RGB(255, 255, 255)
LABEL_PLATE_COLOR = win32api.RGB(24, 24, 28)
LABEL_FONT_HEIGHT = 15

_CLASS_NAME = "GhostCursorOverlay"

# Module-level so the GDI handles outlive every call that uses them.
_bg_brush = None

#: Window classes registered by this process, by name. A dict rather than a
#: per-class boolean: two globals tracking two classes is how a third one gets
#: forgotten, and RegisterClass fails if called twice for the same name.
_registered_classes: dict[str, bool] = {}


def ensure_class(name: str, wnd_proc, background_brush) -> None:
    """Register a window class once per process.

    Public (no leading underscore): both the overlay and the bar call this
    across module boundaries, and a "private" name imported by another module
    is not actually private -- naming it publicly says so honestly.
    """
    if _registered_classes.get(name):
        return
    wnd_class = win32gui.WNDCLASS()
    wnd_class.lpfnWndProc = wnd_proc
    wnd_class.hInstance = win32api.GetModuleHandle(None)
    wnd_class.lpszClassName = name
    wnd_class.hbrBackground = background_brush
    win32gui.RegisterClass(wnd_class)
    _registered_classes[name] = True


# Current hint, in *client* coordinates: (x, y, radius, freshness) or None.
_hint: tuple[int, int, int, "Freshness"] | None = None

# Current Act cue, in *screen* coordinates, or None. Held separately from
# `_hint` rather than replacing it: Teach's staleness ring and an Act cue mean
# different things, and one variable holding either would let a stale Teach
# hint survive into an Act run wearing Act's colours.
_cue: "CueScene | None" = None

# Cached label font, module-level so the GDI handle outlives every paint.
_label_font = None

# Origin of the virtual screen, so callers can pass real screen coordinates
# even on multi-monitor setups where the left/top monitor starts at a
# negative x/y.
_origin = (0, 0)


def ring_colour_for(freshness) -> int:
    """The ring colour for a drawable freshness state.

    HIDDEN never reaches here: the caller clears the hint instead, because
    this function must always return a colour and a hidden hint has none.
    """
    from ghostcursor.reasoning.staleness import Freshness

    if freshness is Freshness.INFERRED:
        return INFERRED_RING_COLOR
    if freshness is Freshness.DIMMED:
        return DIMMED_RING_COLOR
    return RING_COLOR


def _paint_ring(hdc, x: int, y: int, radius: int, freshness) -> None:
    colour = ring_colour_for(freshness)
    pen = win32gui.CreatePen(win32con.PS_SOLID, RING_THICKNESS, colour)
    old_pen = win32gui.SelectObject(hdc, pen)
    old_brush = win32gui.SelectObject(hdc, win32gui.GetStockObject(win32con.NULL_BRUSH))
    win32gui.Ellipse(hdc, x - radius, y - radius, x + radius, y + radius)
    win32gui.SelectObject(hdc, old_brush)
    win32gui.SelectObject(hdc, old_pen)
    win32gui.DeleteObject(pen)


def _wnd_proc(hwnd, msg, wparam, lparam):
    if msg == win32con.WM_PAINT:
        hdc, paint_struct = win32gui.BeginPaint(hwnd)
        # Erase to the colorkey -> the whole overlay is transparent by default.
        win32gui.FillRect(hdc, win32gui.GetClientRect(hwnd), _bg_brush)
        if _hint is not None:
            _paint_ring(hdc, *_hint)
        if _cue is not None:
            _paint_cue(hdc, _cue)
        win32gui.EndPaint(hwnd, paint_struct)
        return 0

    if msg == win32con.WM_ERASEBKGND:
        return 1  # handled in WM_PAINT; returning 1 here prevents flicker

    if msg == win32con.WM_DESTROY:
        win32gui.PostQuitMessage(0)
        return 0

    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


def create_overlay_window() -> int:
    """Create a click-through, topmost, taskbar-hidden overlay spanning the
    whole virtual desktop (all monitors). Returns its HWND."""
    global _bg_brush, _origin

    h_instance = win32api.GetModuleHandle(None)

    if _bg_brush is None:
        _bg_brush = win32gui.CreateSolidBrush(COLOR_KEY)

    ensure_class(_CLASS_NAME, _wnd_proc, _bg_brush)

    # Physical-pixel virtual-screen rect so the overlay covers every monitor,
    # including ones positioned left of / above the primary (negative origin).
    # Must not use GetSystemMetrics directly — it is DPI-scaled and would
    # leave part of the screen uncovered (see overlay/dpi.py, D013).
    left, top, width, height = dpi.virtual_screen_rect()
    _origin = (left, top)

    ex_style = (
        win32con.WS_EX_LAYERED
        | win32con.WS_EX_TRANSPARENT
        | win32con.WS_EX_TOPMOST
        | win32con.WS_EX_TOOLWINDOW
        | win32con.WS_EX_NOACTIVATE
    )

    hwnd = win32gui.CreateWindowEx(
        ex_style,
        _CLASS_NAME,
        "GhostCursor",
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

    win32gui.SetLayeredWindowAttributes(hwnd, COLOR_KEY, 0, win32con.LWA_COLORKEY)
    # SW_SHOWNOACTIVATE: appear without stealing focus from the app the user
    # is actually working in.
    win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
    win32gui.UpdateWindow(hwnd)
    return hwnd


def set_hint(
    hwnd: int,
    screen_x: int,
    screen_y: int,
    radius: int = 24,
    freshness: "Freshness" = None,
) -> None:
    """Show the hint ring centred on a *screen* coordinate, repainting now."""
    from ghostcursor.reasoning.staleness import Freshness

    global _hint
    if freshness is None:
        freshness = Freshness.FRESH
    _hint = (screen_x - _origin[0], screen_y - _origin[1], radius, freshness)
    win32gui.InvalidateRect(hwnd, None, False)
    win32gui.UpdateWindow(hwnd)


def clear_hint(hwnd: int) -> None:
    """Remove any hint, leaving the overlay fully transparent."""
    global _hint
    _hint = None
    win32gui.InvalidateRect(hwnd, None, False)
    win32gui.UpdateWindow(hwnd)



def _ensure_label_font():
    """The one font every cue label is drawn and measured in.

    Created once and kept: measuring with one font and drawing with another is
    how a label that "fits" clips its last word.
    """

    global _label_font
    if _label_font is None:
        _label_font = win32gui.CreateFont(
            LABEL_FONT_HEIGHT, 0, 0, 0, win32con.FW_SEMIBOLD,
            False, False, False,
            win32con.DEFAULT_CHARSET, win32con.OUT_DEFAULT_PRECIS,
            win32con.CLIP_DEFAULT_PRECIS, win32con.CLEARTYPE_QUALITY,
            win32con.DEFAULT_PITCH | win32con.FF_SWISS, "Segoe UI",
        )
    return _label_font


def measure_label(hwnd: int, text: str) -> "cue_layout.LabelMetrics":
    """Real metrics for the cue font, from the window's own device context.

    `cue.label_box` takes these rather than assuming them, because a guessed
    character width is how a label that fits on this machine clips on the
    user's. Averaged over the actual string, so a run of narrow characters
    does not reserve space a wide one needs.
    """

    from ghostcursor.overlay import cue as cue_layout

    hdc = win32gui.GetDC(hwnd)
    try:
        old = win32gui.SelectObject(hdc, _ensure_label_font())
        width, height = win32gui.GetTextExtentPoint32(hdc, text or " ")
        win32gui.SelectObject(hdc, old)
    finally:
        win32gui.ReleaseDC(hwnd, hdc)
    per_char = max(1, -(-width // max(1, len(text or " "))))
    return cue_layout.LabelMetrics(char_width=per_char, line_height=height)


def _paint_cue(hdc, scene) -> None:
    """Draw one Act cue: ring around the control, ghost pointer, label.

    Order matters. The ring goes down first, the pointer over it, the label
    last -- the label is the only opaque element, so anything drawn after it
    would show through the words.
    """

    from ghostcursor.overlay import cue as cue_layout

    red, green, blue = scene.colour
    colour = win32api.RGB(red, green, blue)
    ox, oy = _origin

    if scene.target is not None:
        left, top, right, bottom = scene.target
        pen = win32gui.CreatePen(win32con.PS_SOLID, CUE_RING_THICKNESS, colour)
        old_pen = win32gui.SelectObject(hdc, pen)
        old_brush = win32gui.SelectObject(
            hdc, win32gui.GetStockObject(win32con.NULL_BRUSH)
        )
        win32gui.Rectangle(hdc, left - ox, top - oy, right - ox, bottom - oy)
        win32gui.SelectObject(hdc, old_brush)
        win32gui.SelectObject(hdc, old_pen)
        win32gui.DeleteObject(pen)

    if scene.label_rect is not None:
        # Before the pointer: the plate is the only opaque element, and the
        # glyph must sit on top of it rather than behind it.
        _paint_label(hdc, scene.label_rect, scene.label, colour)

    if scene.pointer is None:
        return

    points = [
        (x - ox, y - oy)
        for x, y in cue_layout.pointer_polygon(*scene.pointer, scale=2)
    ]
    brush = win32gui.CreateSolidBrush(colour)
    pen = win32gui.CreatePen(win32con.PS_SOLID, 1, LABEL_PLATE_COLOR)
    old_pen = win32gui.SelectObject(hdc, pen)
    old_brush = win32gui.SelectObject(hdc, brush)
    win32gui.Polygon(hdc, points)
    win32gui.SelectObject(hdc, old_brush)
    win32gui.SelectObject(hdc, old_pen)
    win32gui.DeleteObject(brush)
    win32gui.DeleteObject(pen)


def _paint_label(hdc, box, text: str, colour: int) -> None:
    """The plate and its words, in screen coordinates already laid out."""

    left, top, right, bottom = box
    ox, oy = _origin
    rect = (left - ox, top - oy, right - ox, bottom - oy)

    plate = win32gui.CreateSolidBrush(LABEL_PLATE_COLOR)
    win32gui.FillRect(hdc, rect, plate)
    win32gui.DeleteObject(plate)

    pen = win32gui.CreatePen(win32con.PS_SOLID, 1, colour)
    old_pen = win32gui.SelectObject(hdc, pen)
    old_brush = win32gui.SelectObject(
        hdc, win32gui.GetStockObject(win32con.NULL_BRUSH)
    )
    win32gui.Rectangle(hdc, *rect)
    win32gui.SelectObject(hdc, old_brush)
    win32gui.SelectObject(hdc, old_pen)
    win32gui.DeleteObject(pen)

    old_font = win32gui.SelectObject(hdc, _ensure_label_font())
    win32gui.SetBkMode(hdc, win32con.TRANSPARENT)
    win32gui.SetTextColor(hdc, LABEL_TEXT_COLOR)
    win32gui.DrawText(
        hdc, text, -1, rect,
        win32con.DT_CENTER | win32con.DT_VCENTER | win32con.DT_SINGLELINE,
    )
    win32gui.SelectObject(hdc, old_font)


def set_cue(hwnd: int, scene) -> None:
    """Show one Act cue, repainting now. Replaces any previous cue."""

    global _cue
    _cue = scene
    win32gui.InvalidateRect(hwnd, None, False)
    win32gui.UpdateWindow(hwnd)


def clear_cue(hwnd: int) -> None:
    """Remove the Act cue. Always call this when a node ends -- a cue left on
    screen points at a control nothing is about to click."""

    global _cue
    _cue = None
    win32gui.InvalidateRect(hwnd, None, False)
    win32gui.UpdateWindow(hwnd)


def destroy_overlay_window(hwnd: int) -> None:
    """Tear the overlay down. Always call this on exit — a stranded
    full-screen window is exactly the failure that locks a user out."""
    try:
        win32gui.DestroyWindow(hwnd)
    except win32gui.error:
        pass
    pump_messages_nonblocking()


def pump_messages_nonblocking() -> None:
    """Process pending Win32 messages without blocking. Call once per tick
    from the caller's own loop."""
    win32gui.PumpWaitingMessages()
