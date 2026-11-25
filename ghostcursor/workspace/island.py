"""Small, movable workspace presence. It has no screen-targeting authority.

Ask (the button or Ctrl+Alt+O) unfolds a type-to-ask panel, as in HeyClicky's
notch: the question goes through the same Chat path as the workspace page
(``App.handle("say")``, or ``"research"`` with Research on), so nothing new
leaves the device, and the reply shows on a card under the bar for follow-ups.
Escape folds it. Talk arms the existing voice listener, and anything it hears
lands on the same card. Finished background research is shown there too, and
the bar steps aside while a full-screen app is in front.

At rest the bar is tucked into a thin pill at the top edge that clicks pass
through, so it never covers what is under it (HeyClicky's notch). Resting the
pointer on the pill, Ctrl+Alt+O, work running or a new result bring the bar
out; it tucks away again once the pointer has left it."""

from __future__ import annotations

import ctypes
import functools
import time
import threading

import win32api
import win32con
import win32gui
from PIL import Image, ImageDraw

from ghostcursor.overlay.window import ensure_class
from ghostcursor.workspace.companion import Companion, label as companion_label

CLASS = "OrbynWorkspaceIsland"
# Above IDOK/IDCANCEL: IsDialogMessage turns Enter into the default button
# (DM_GETDEFID) and Escape into IDCANCEL.
(
    ID_OPEN,
    ID_STOP,
    ID_QUIT,
    ID_HIDE,
    ID_ASK,
    ID_SEND,
    ID_INPUT,
    ID_REPLY,
    ID_TALK,
    ID_RESEARCH,
) = range(11, 21)
HOTKEY_ID = 5
SHOW_MESSAGE = win32con.WM_APP + 1
DM_GETDEFID, DC_HASDEFID = win32con.WM_USER, 0x534B
COMPACT = (326, 56)
EXPANDED = (440, 72)
ASKING = (440, 360)
#: The tucked pill at the top edge; the whole bar shows only when wanted.
TUCKED = (110, 6)
#: The pointer rests on the pill this long before the bar comes out, so
#: passing over the top of the screen (to a tab, say) does not open it.
PEEK_DWELL_S = 0.2
#: The bar tucks away once the pointer has been off it this long.
TUCK_AFTER_S = 0.8
PILL = win32api.RGB(92, 100, 114)
MAX_TRANSCRIPT = 20_000
HINT = (
    "Replies show here. Type again to follow up; Esc folds; Open shows the full chat."
)
#: Background job kind -> the name on its result card (app.JOB_KINDS).
JOB_LABELS = {"research": "Research", "deep": "Deep research", "crew": "Crew"}
#: Peek: the bar comes back while the pointer rests within this many pixels
#: of it (or above it, up to the screen edge), as HeyClicky's notch does.
PEEK_MARGIN = 24
SHOWN_ANSWER = 1500  # a finished job's answer on the card; Open › Work has all of it
BG = win32api.RGB(22, 26, 34)
TEXT = win32api.RGB(249, 247, 242)
MUTED = win32api.RGB(166, 174, 186)
ACCENT = win32api.RGB(239, 182, 96)
SECONDARY = win32api.RGB(48, 54, 64)
PRESSED = win32api.RGB(202, 147, 67)
STOP = win32api.RGB(105, 55, 53)
SECONDARY_PRESSED = win32api.RGB(70, 77, 89)
STOP_PRESSED = win32api.RGB(132, 70, 67)
LINE = win32api.RGB(48, 54, 64)
HOVER = win32api.RGB(247, 199, 124)
SECONDARY_HOVER = win32api.RGB(59, 66, 78)
STOP_HOVER = win32api.RGB(119, 62, 60)
_windows = {}
_brush = None
_field_brush = None
_font = None  # body text, Segoe UI
_bold = None  # the heading and the buttons, Segoe UI Semibold
_scale = 1.0  # display scaling (DPI / 96); layout is in 96-DPI design units
SMOOTH = 4  # shapes are drawn this many times larger, then scaled down smoothly
DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND, DWMWCP_DONOTROUND = 33, 2, 1
DWMWA_COLOR_NONE = 0xFFFFFFFE
DWMWA_BORDER_COLOR = 34
WM_DPICHANGED = 0x02E0


def _px(*values):
    """Design units (96 DPI) to device pixels at the display's scaling."""
    scaled = tuple(round(v * _scale) for v in values)
    return scaled[0] if len(scaled) == 1 else scaled


def scaled(size):
    """A design-unit size (COMPACT, EXPANDED, ASKING) in device pixels."""
    return _px(*size)


def _make_font(height, weight):
    font = win32gui.LOGFONT()
    font.lfHeight, font.lfWeight = -_px(height), weight
    font.lfFaceName = "Segoe UI"
    font.lfQuality = 5  # CLEARTYPE_QUALITY
    return win32gui.CreateFontIndirect(font)


def _make_fonts():
    return _make_font(13, win32con.FW_NORMAL), _make_font(13, win32con.FW_SEMIBOLD)


def _rgb(color):
    """A win32 COLORREF (0x00BBGGRR) as an (r, g, b) tuple."""
    return color & 0xFF, color >> 8 & 0xFF, color >> 16 & 0xFF


@functools.lru_cache(maxsize=128)
def _shape(width, height, back, color, ring, round_, radius):
    """The shape's pixels as top-down BGRA rows: drawn SMOOTH times larger
    and box-averaged down (Image.reduce), so every edge pixel is an exact mix
    of the two colours -- soft, with no dark fringe."""

    big_w, big_h = width * SMOOTH, height * SMOOTH
    image = Image.new("RGB", (big_w, big_h), _rgb(back))
    draw = ImageDraw.Draw(image)
    inset = 0
    for fill in (ring, color) if ring is not None else (color,):
        bounds = (inset, inset, big_w - 1 - inset, big_h - 1 - inset)
        if round_:
            corner = radius * SMOOTH if radius else (min(big_w, big_h) - 2 * inset) // 2
            draw.rounded_rectangle(bounds, radius=corner, fill=_rgb(fill))
        else:
            draw.ellipse(bounds, fill=_rgb(fill))
        inset = _px(2) * SMOOTH
    return image.reduce(SMOOTH).convert("RGBA").tobytes("raw", "BGRA")


class _BitmapHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


def _smooth(hdc, box, back, color, *, ring=None, round_=True, radius=None):
    """Fill ``box`` with an anti-aliased pill (or circle, when square) of
    ``color`` on a known ``back`` colour, instead of GDI's stair-stepped
    RoundRect. ``ring``, if given, is a 2-unit outline; ``radius`` gives a
    rounded rectangle instead of a pill."""

    left, top, right, bottom = box
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return
    pixels = _shape(width, height, back, color, ring, round_, radius)
    header = _BitmapHeader(ctypes.sizeof(_BitmapHeader), width, -height, 1, 32)
    ctypes.windll.gdi32.SetDIBitsToDevice(
        ctypes.c_void_p(hdc),
        left,
        top,
        width,
        height,
        0,
        0,
        0,
        height,
        pixels,
        ctypes.byref(header),
        0,  # DIB_RGB_COLORS
    )


def _smooth_well(hdc, box):
    """A field's background: a rounded rectangle (radius 10) in SECONDARY."""

    _smooth(hdc, box, BG, SECONDARY, radius=_px(10))


def _round_corners(hwnd, round_=True):
    """Windows 11 draws the bar's corners anti-aliased, with its shadow and a
    hairline border. False before Windows 11, where a (stepped) region is
    the only way to round them. ``round_=False`` turns all of it off, for the
    tucked pill: a frame and shadow around a few pixels look like a box."""

    dwm = ctypes.windll.dwmapi
    if not round_:
        for attribute, value in (
            (DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_DONOTROUND),
            (DWMWA_BORDER_COLOR, DWMWA_COLOR_NONE),
        ):
            setting = ctypes.c_uint(value)
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attribute, ctypes.byref(setting), 4)
        return True
    preference = ctypes.c_int(DWMWCP_ROUND)
    if dwm.DwmSetWindowAttribute(
        ctypes.c_void_p(hwnd), DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(preference), 4
    ):
        return False
    border = ctypes.c_uint(LINE)
    dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), DWMWA_BORDER_COLOR, ctypes.byref(border), 4)
    return True


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _Message(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_ulong),
        ("pt", _Point),
        ("lPrivate", ctypes.c_ulong),
    ]


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _DrawItem(ctypes.Structure):
    _fields_ = [
        ("CtlType", ctypes.c_uint),
        ("CtlID", ctypes.c_uint),
        ("itemID", ctypes.c_uint),
        ("itemAction", ctypes.c_uint),
        ("itemState", ctypes.c_uint),
        ("hwndItem", ctypes.c_void_p),
        ("hDC", ctypes.c_void_p),
        ("rcItem", _Rect),
        ("itemData", ctypes.c_size_t),
    ]


def _cursor():
    return win32api.GetCursorPos()


def _fullscreen():
    """A full-screen app, game or presentation is in front (Windows says so)."""
    state = ctypes.c_int(0)
    if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)):
        return False
    return state.value in (
        2,
        3,
        4,
    )  # QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE


def _draw_button(lparam, island):
    item = ctypes.cast(lparam, ctypes.POINTER(_DrawItem)).contents
    hdc = int(item.hDC)
    rect = item.rcItem
    bounds = (rect.left, rect.top, rect.right, rect.bottom)
    win32gui.FillRect(hdc, bounds, _brush)
    # One amber action at a time: Send while the Ask panel is open, else Ask.
    primary = item.CtlID == (ID_SEND if island.asking else ID_ASK) or (
        item.CtlID == ID_RESEARCH and island.research
    )
    pressed = bool(item.itemState & win32con.ODS_SELECTED)
    focused = bool(item.itemState & win32con.ODS_FOCUS)
    state = 1 if pressed else 2 if (item.hwndItem or 0) == island.hot else 0
    if primary:
        color = (ACCENT, PRESSED, HOVER)[state]
    elif item.CtlID == ID_STOP:
        color = (STOP, STOP_PRESSED, STOP_HOVER)[state]
    else:
        color = (SECONDARY, SECONDARY_PRESSED, SECONDARY_HOVER)[state]
    _smooth(hdc, bounds, BG, color, ring=TEXT if focused else None)
    old_font = win32gui.SelectObject(hdc, _bold)
    win32gui.SetBkMode(hdc, win32con.TRANSPARENT)
    win32gui.SetTextColor(hdc, BG if primary else TEXT)
    win32gui.DrawText(
        hdc,
        win32gui.GetWindowText(item.hwndItem),
        -1,
        bounds,
        win32con.DT_CENTER | win32con.DT_VCENTER | win32con.DT_SINGLELINE,
    )
    win32gui.SelectObject(hdc, old_font)


def _wait(seconds):
    """Sleep until a message arrives (a click, a key, a timer) or the time is
    up, so input is handled at once and an idle bar costs nothing."""

    failed = 0xFFFFFFFF == ctypes.windll.user32.MsgWaitForMultipleObjectsEx(
        0, None, max(0, int(seconds * 1000)), 0x04FF, 0x0004
    )  # QS_ALLINPUT, MWMO_INPUTAVAILABLE
    if failed:
        time.sleep(min(seconds, 0.03))  # never spin if the wait is refused


def _pump_dialog(hwnd):
    """Dispatch mouse events and let Windows handle Tab/Shift-Tab for the buttons."""
    user32 = ctypes.windll.user32
    message = _Message()
    while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, win32con.PM_REMOVE):
        if not user32.IsDialogMessageW(hwnd, ctypes.byref(message)):
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))


def _jobs(app):
    with app._job_lock:
        return [dict(job) for job in app.background_jobs]


def _last_job(app):
    with app._job_lock:
        return dict(app.background_jobs[-1]) if app.background_jobs else None


def _status(app, job):
    if app.busy:
        from ghostcursor.workspace.app import ACTIVITY_LABELS

        return (
            "Working",
            app.busy if app.busy in ACTIVITY_LABELS else "Task in progress",
        )
    if job and job.get("state") in ("finished", "failed", "stopped", "interrupted"):
        state = job["state"]
        label = JOB_LABELS.get(job.get("kind"), "Research")
        return ("Ready" if state == "finished" else state.title()), f"{label} {state}"
    return "Ready", "Open your workspace"


def _wnd_proc(hwnd, msg, wparam, lparam):
    island = _windows.get(hwnd)
    if msg == win32con.WM_PAINT:
        hdc, paint = win32gui.BeginPaint(hwnd)
        win32gui.FillRect(hdc, win32gui.GetClientRect(hwnd), _brush)
        if island is not None and island.hidden:  # the tucked pill (its region shapes it)
            color = win32gui.CreateSolidBrush(ACCENT if island.strip else PILL)
            win32gui.FillRect(hdc, win32gui.GetClientRect(hwnd), color)
            win32gui.DeleteObject(color)
        elif island is not None:
            wide = island.expanded or island.asking
            middle = 36 if wide else 28  # the top row's centre line
            _smooth(hdc, _px(17, middle - 5, 27, middle + 5), BG, ACCENT, round_=False)
            if island.asking:  # rounded wells behind the field and the card
                _smooth_well(hdc, _px(12, 74, 360, 110))
                _smooth_well(hdc, _px(12, 154, 428, 346))
            win32gui.SetBkMode(hdc, win32con.TRANSPARENT)
            line = win32con.DT_SINGLELINE | win32con.DT_END_ELLIPSIS | win32con.DT_VCENTER
            edge = 182 if wide else 132
            old_font = win32gui.SelectObject(hdc, _bold)
            win32gui.SetTextColor(hdc, TEXT)
            heading = "Orbyn · " + island.title if island.expanded else "Orbyn"
            win32gui.DrawText(hdc, heading, -1, _px(36, middle - 19, edge, middle + 1), line)
            win32gui.SelectObject(hdc, _font)
            win32gui.SetTextColor(hdc, MUTED)
            detail = island.detail if island.expanded else island.title
            win32gui.DrawText(hdc, detail, -1, _px(36, middle, edge, middle + 18), line)
            if island.asking:
                win32gui.DrawText(hdc, island.strip, -1, _px(192, 116, 424, 146), line)
            win32gui.SelectObject(hdc, old_font)
        win32gui.EndPaint(hwnd, paint)
        return 0
    if island is not None:
        if msg == win32con.WM_ERASEBKGND:
            return 1
        if msg in (win32con.WM_CTLCOLOREDIT, win32con.WM_CTLCOLORSTATIC):
            win32gui.SetTextColor(wparam, TEXT)
            win32gui.SetBkColor(wparam, SECONDARY)
            return _field_brush
        if msg == DM_GETDEFID:
            return (DC_HASDEFID << 16) | (ID_SEND if island.asking else ID_ASK)
        if msg == win32con.WM_DRAWITEM and lparam:
            _draw_button(lparam, island)
            return 1
        if msg == win32con.WM_SETCURSOR:  # sent as the pointer crosses a child
            island.hover(wparam if wparam != hwnd else None)
        if msg == win32con.WM_NCHITTEST:
            return (
                win32con.HTCAPTION
            )  # drag the background; child buttons keep their own clicks
        if (
            msg == win32con.WM_COMMAND
            and win32api.HIWORD(wparam) == win32con.BN_CLICKED
        ):
            action = win32api.LOWORD(wparam)
            if action == ID_OPEN:
                island.open()
            elif action == ID_ASK:
                island.fold() if island.asking else island.unfold()
            elif action == ID_SEND:
                island.submit()
            elif action == ID_TALK:
                island.talk()
            elif action == ID_RESEARCH:
                island.research = not island.research
                win32gui.SetWindowText(
                    island.ask_research,
                    "Research on" if island.research else "Research",
                )
            elif action == win32con.IDCANCEL:
                if island.asking:
                    island.fold()
                elif island.app.busy:
                    island.app.stop.set()
            elif action == ID_STOP:
                island.app.stop.set()
            elif action == ID_HIDE:
                island.hide()
            elif action == ID_QUIT:
                island.app.handle("quit", {})
                win32gui.DestroyWindow(hwnd)
            return 0
        if msg == win32con.WM_HOTKEY and wparam == HOTKEY_ID:
            if island.asking:
                island.fold()
                island.hide()
            else:
                island.unfold()
            return 0
        if msg == SHOW_MESSAGE:
            island.show()
            return 0
        if msg == WM_DPICHANGED:  # dragged onto a monitor with other scaling
            left, top, right, bottom = ctypes.cast(
                lparam, ctypes.POINTER(ctypes.c_long * 4)
            ).contents
            win32gui.SetWindowPos(  # Windows' suggestion keeps it under the pointer
                hwnd, 0, left, top, right - left, bottom - top,
                win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
            )
            island.rescale((wparam & 0xFFFF) / 96)
            return 0
        if msg == win32con.WM_DISPLAYCHANGE:
            island._resize(island.expanded)
            return 0
        if msg == win32con.WM_CLOSE:
            island.app.handle("quit", {})
            win32gui.DestroyWindow(hwnd)
            return 0
        if msg == win32con.WM_DESTROY:
            if island.hotkey_available:
                ctypes.windll.user32.UnregisterHotKey(hwnd, HOTKEY_ID)
            island.closed = True
            island.companion.destroy()
            _windows.pop(hwnd, None)
            return 0
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


class Island:
    """The Win32 UI thread owns this window; jobs stay on the existing worker."""

    def __init__(
        self, app, url, open_window, *, clock=time.monotonic, voice_hotkey=None
    ):
        global _brush, _field_brush, _font, _bold, _scale
        self.app, self.url, self.open_window = app, url, open_window
        self.clock = clock
        self._opening = threading.Event()
        self.closed = False
        self.hidden = False
        self.peek_armed = False  # set once the pointer has left the bar after Hide
        self.auto_revealed = False
        self.expanded = False
        self.asking = False
        self.covered = False  # stepped aside for a full-screen app
        self.research = False
        self.hot = None  # the button under the pointer
        self.listener = None  # the voice Listener, when listening is on
        self.strip = ""
        self.transcript = ""
        self._reply = None  # set by the ask thread, shown by tick() on the UI thread
        self._heard = None  # set by the voice thread, asked by tick() on the UI thread
        self._notice_until = 0.0
        job = _last_job(app)
        self._last_job_state = (job.get("id"), job.get("state")) if job else None
        self._shown_jobs = {j["id"] for j in _jobs(app) if j.get("state") != "running"}
        self.title, self.detail = "Ready", "Open your workspace"
        if _brush is None:
            _scale = ctypes.windll.user32.GetDpiForSystem() / 96  # dpi aware (rule 4)
            _brush = win32gui.CreateSolidBrush(BG)
            _field_brush = win32gui.CreateSolidBrush(SECONDARY)
            _font, _bold = _make_fonts()
        # Before the bar: if this fails no bar window is left behind.
        self.companion = Companion(lambda: _cursor())  # the OS pointer only
        try:
            ensure_class(CLASS, _wnd_proc, _brush)
            screen = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            width, height = scaled(COMPACT)
            self.hwnd = win32gui.CreateWindowEx(
                win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW,
                CLASS,
                "Orbyn · Ready",
                win32con.WS_POPUP,
                max(0, (screen - width) // 2),
                16,
                width,
                height,
                None,
                None,
                win32api.GetModuleHandle(None),
                None,
            )
        except BaseException:
            self.companion.destroy()  # no orphan badge window
            raise
        _windows[self.hwnd] = self
        voice_owns_hotkey = False
        if voice_hotkey:
            from ghostcursor.listen import parse_hotkey

            try:
                voice_owns_hotkey = parse_hotkey(voice_hotkey) == (
                    win32con.MOD_CONTROL | win32con.MOD_ALT | win32con.MOD_NOREPEAT,
                    ord("O"),
                )
            except ValueError:
                pass  # Listener reports a malformed configured shortcut.
        self.hotkey_available = not voice_owns_hotkey and bool(
            ctypes.windll.user32.RegisterHotKey(
                self.hwnd,
                HOTKEY_ID,
                win32con.MOD_CONTROL | win32con.MOD_ALT | win32con.MOD_NOREPEAT,
                ord("O"),
            )
        )
        self.dwm_corners = _round_corners(self.hwnd)
        style = (
            win32con.WS_CHILD
            | win32con.WS_VISIBLE
            | win32con.WS_TABSTOP
            | win32con.BS_OWNERDRAW
        )
        module = win32api.GetModuleHandle(None)
        self.ask_button = win32gui.CreateWindowEx(
            0, "BUTTON", "Ask", style, 0, 0, 0, 0, self.hwnd, ID_ASK, module, None
        )
        self.open_button = win32gui.CreateWindowEx(
            0, "BUTTON", "Open", style, 0, 0, 0, 0, self.hwnd, ID_OPEN, module, None
        )
        self.send_button = win32gui.CreateWindowEx(
            0,
            "BUTTON",
            "Send",
            style,
            0,
            0,
            0,
            0,
            self.hwnd,
            ID_SEND,
            module,
            None,
        )
        field = win32con.WS_CHILD | win32con.WS_TABSTOP | win32con.ES_AUTOHSCROLL
        self.input = win32gui.CreateWindowEx(
            0, "EDIT", "", field, 0, 0, 0, 0, self.hwnd, ID_INPUT, module, None
        )
        panel = style & ~win32con.WS_VISIBLE
        self.talk_button = win32gui.CreateWindowEx(
            0,
            "BUTTON",
            "Talk",
            panel,
            0,
            0,
            0,
            0,
            self.hwnd,
            ID_TALK,
            module,
            None,
        )
        self.ask_research = win32gui.CreateWindowEx(
            0,
            "BUTTON",
            "Research",
            panel,
            0,
            0,
            0,
            0,
            self.hwnd,
            ID_RESEARCH,
            module,
            None,
        )
        card = (
            win32con.WS_CHILD
            | win32con.WS_VSCROLL
            | win32con.ES_MULTILINE
            | win32con.ES_READONLY
            | win32con.ES_AUTOVSCROLL
        )
        self.reply = win32gui.CreateWindowEx(
            0, "EDIT", "", card, 0, 0, 0, 0, self.hwnd, ID_REPLY, module, None
        )
        self._set_field_fonts()
        ctypes.windll.uxtheme.SetWindowTheme(
            self.reply, "DarkMode_Explorer", None
        )  # dark scrollbar
        win32gui.SetWindowText(self.reply, HINT)
        win32gui.SendMessage(
            self.input, 0x1501, 1, "Ask Orbyn, then press Enter"
        )  # EM_SETCUEBANNER
        self.stop_button = win32gui.CreateWindowEx(
            0,
            "BUTTON",
            "Stop",
            style,
            0,
            0,
            0,
            0,
            self.hwnd,
            ID_STOP,
            module,
            None,
        )
        self.hide_button = win32gui.CreateWindowEx(
            0, "BUTTON", "Hide", style, 0, 0, 0, 0, self.hwnd, ID_HIDE, module, None
        )
        self.quit_button = win32gui.CreateWindowEx(
            0, "BUTTON", "Quit", style, 0, 0, 0, 0, self.hwnd, ID_QUIT, module, None
        )
        for hidden in (self.stop_button, self.send_button, self.hide_button):
            win32gui.ShowWindow(hidden, win32con.SW_HIDE)  # tucking is automatic now
        self._hover_since = self._left_since = None
        self._resize(False)  # initial placement must respect a top/side taskbar
        self.hidden, self.peek_armed = True, True
        self._tuck()  # at rest: a pill at the top edge, not a bar over the page
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
        win32gui.UpdateWindow(self.hwnd)

    def open(self):
        if self._opening.is_set():
            return
        self._opening.set()
        destination = (
            self.url + "#work"
            if self.clock() < self._notice_until
            or getattr(self.app, "background_id", None)
            else self.url
        )

        def launch():
            try:
                self.open_window(destination)
            finally:
                self._opening.clear()

        threading.Thread(
            target=launch, daemon=True, name="orbyn-open-workspace"
        ).start()

    def unfold(self):
        """Show the ask panel and put the caret in it."""
        if self.hidden:
            self.show()
        self.asking = True
        self._resize(self.expanded)
        win32gui.SetWindowText(self.ask_button, "Done")
        for child in self._panel():
            win32gui.ShowWindow(child, win32con.SW_SHOW)
        try:
            win32gui.SetForegroundWindow(self.hwnd)
        except win32gui.error:
            pass  # Windows may refuse focus theft; a click in the field still works
        win32gui.SetFocus(self.input)

    def fold(self):
        self.asking = False
        win32gui.SetWindowText(self.ask_button, "Ask")
        for child in self._panel():
            win32gui.ShowWindow(child, win32con.SW_HIDE)
        self._resize(self.expanded)

    def _panel(self):
        return (
            self.input,
            self.send_button,
            self.talk_button,
            self.ask_research,
            self.reply,
        )

    def voice(self, text):
        """The Listener heard a request (its own thread); tick() asks it."""
        self._heard = text

    def talk(self):
        if self.listener is None:
            self._show(
                'Voice is off. Turn on "hotkey" or "wake_word" in settings.json.'
            )
            return
        self.listener.arm("Talk")  # the next thing said is the request
        self._show("Listening… say what you need.")

    def submit(self, spoken=None):
        text = " ".join((spoken or win32gui.GetWindowText(self.input)).split())
        if not text:
            return
        if self.app.busy:
            self._show(f"Orbyn is busy ({self.app.busy}); try again when it finishes.")
            return
        if spoken is None:
            win32gui.SetWindowText(self.input, "")
        action, field = ("research", "answer") if self.research else ("say", "reply")
        self._show(f"You{' (voice)' if spoken else ''}: {text}\r\nOrbyn: …")

        def ask():
            try:
                reply = self.app.handle(action, {"text": text})[field]
            except (
                Exception
            ) as exc:  # busy, no model, provider error: say it on the card
                reply = f"Could not answer: {exc}"
            self._reply = str(reply)

        threading.Thread(target=ask, daemon=True, name="orbyn-island-ask").start()

    def _show(self, text):
        text = text.replace("\r\n", "\n").replace(
            "\n", "\r\n"
        )  # an EDIT control breaks lines only on CRLF
        self.transcript = (
            self.transcript + "\r\n\r\n" if self.transcript else ""
        ) + text
        self._render()

    def _render(self):
        self.transcript = self.transcript[-MAX_TRANSCRIPT:]
        win32gui.SetWindowText(self.reply, self.transcript or HINT)
        self._fit_scrollbar()
        win32gui.SendMessage(
            self.reply, win32con.EM_SETSEL, len(self.transcript), len(self.transcript)
        )
        win32gui.SendMessage(self.reply, win32con.EM_SCROLLCARET, 0, 0)

    def _hovered(self):
        """The pointer is on the bar, or between it and the top of the screen."""

        try:
            x, y = _cursor()
            left, top, right, bottom = win32gui.GetWindowRect(self.hwnd)
            monitor = win32api.MonitorFromWindow(
                self.hwnd, win32con.MONITOR_DEFAULTTONEAREST
            )
            screen_top = win32api.GetMonitorInfo(monitor)["Monitor"][1]
        except Exception:
            return False
        return (
            left - PEEK_MARGIN <= x <= right + PEEK_MARGIN
            and screen_top <= y <= bottom + PEEK_MARGIN
        )

    def hide(self):
        """Tuck the bar into the pill. Never while work runs: Stop stays."""

        if self.app.busy:
            return
        if self.asking:
            self.fold()
        self.peek_armed = False  # the pointer is on the bar now; peek after it leaves
        self._notice_until = 0.0
        self.auto_revealed = False
        self.hidden = True
        self._hover_since = self._left_since = None
        self._tuck()

    def _bar_children(self):
        return (self.ask_button, self.open_button, self.quit_button)

    def _tuck(self):
        for child in (*self._bar_children(), self.stop_button, *self._panel()):
            win32gui.ShowWindow(child, win32con.SW_HIDE)
        style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
        # Click-through: the pill never takes a click meant for what is under
        # it; it is found by where the pointer rests, not by clicks.
        win32gui.SetWindowLong(
            self.hwnd,
            win32con.GWL_EXSTYLE,
            style | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT,
        )
        win32gui.SetLayeredWindowAttributes(self.hwnd, 0, 235, win32con.LWA_ALPHA)
        width, height = scaled(TUCKED)
        left, _, right, _ = win32gui.GetWindowRect(self.hwnd)
        monitor = win32api.MonitorFromWindow(
            self.hwnd, win32con.MONITOR_DEFAULTTONEAREST
        )
        top = win32api.GetMonitorInfo(monitor)["Monitor"][1]
        win32gui.SetWindowPos(
            self.hwnd, 0, (left + right - width) // 2, top, width, height,
            win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
        )
        _round_corners(self.hwnd, round_=False)
        win32gui.SetWindowRgn(  # the pill's own shape, ends fully round
            self.hwnd,
            win32gui.CreateRoundRectRgn(0, 0, width + 1, height + 1, height, height),
            True,
        )
        win32gui.InvalidateRect(self.hwnd, None, True)

    def show(self, *, automatic=False):
        was_tucked = self.hidden
        self.hidden = False
        self.auto_revealed = automatic
        self._hover_since = self._left_since = None
        if was_tucked:
            style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(
                self.hwnd,
                win32con.GWL_EXSTYLE,
                style & ~(win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT),
            )
            left, top, _, _ = win32gui.GetWindowRect(self.hwnd)
            work_top = win32api.GetMonitorInfo(
                win32api.MonitorFromWindow(self.hwnd, win32con.MONITOR_DEFAULTTONEAREST)
            )["Work"][1]
            win32gui.SetWindowPos(  # out from the pill, just below the top edge
                self.hwnd, 0, left, work_top + _px(8), 0, 0,
                win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE | win32con.SWP_NOSIZE,
            )
            for child in self._bar_children():
                win32gui.ShowWindow(child, win32con.SW_SHOWNA)
            if self.dwm_corners:  # Windows 11 rounds and frames the bar again
                win32gui.SetWindowRgn(self.hwnd, None, True)
                _round_corners(self.hwnd)
        self._resize(self.expanded)  # a disconnected monitor may have held it
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)

    def tick(self):
        reply, self._reply = self._reply, None
        if reply is not None:
            # an EDIT control breaks lines only on CRLF
            self.transcript = self.transcript.removesuffix("…") + reply.replace(
                "\r\n", "\n"
            ).replace("\n", "\r\n")
            self._render()
        heard, self._heard = self._heard, None
        if heard:
            self.unfold()
            self.submit(heard)
        jobs = _jobs(self.app)
        for done in jobs:
            if (
                done.get("state") != "running"
                and done.get("id") not in self._shown_jobs
            ):
                self._shown_jobs.add(done.get("id"))
                if done.get("state") == "finished" and done.get("answer"):
                    answer = done["answer"]
                    more = (
                        "\n… (Open › Work for the rest)"
                        if len(answer) > SHOWN_ANSWER
                        else ""
                    )
                    label = JOB_LABELS.get(done.get("kind"), "Research")
                    self._show(
                        f"{label} finished: {done.get('question', '')}\n{answer[:SHOWN_ANSWER]}{more}"
                    )
        running = sum(j.get("state") == "running" for j in jobs)
        strip = f"{running} job{'s' * (running != 1)} running" if running else ""
        if strip != self.strip:
            self.strip = strip
            win32gui.InvalidateRect(self.hwnd, None, True)
        job = _last_job(self.app)
        job_state = (job.get("id"), job.get("state")) if job else None
        if job_state != self._last_job_state:
            if job and job.get("state") in (
                "finished",
                "failed",
                "stopped",
                "interrupted",
            ):
                self._notice_until = self.clock() + 12
            self._last_job_state = job_state
        listening = (
            self.listener is not None and self.listener.held is not None
        )  # hold-to-talk
        expanded = bool(self.app.busy) or listening or self.clock() < self._notice_until
        hovered = self._hovered()
        now = self.clock()
        if hovered:
            self._left_since = None
            if self._hover_since is None:
                self._hover_since = now
        else:
            self._hover_since = None
            if self._left_since is None:
                self._left_since = now
        if self.hidden and not hovered:
            self.peek_armed = True
        rested = hovered and now - self._hover_since >= PEEK_DWELL_S
        if self.hidden and (expanded or (rested and self.peek_armed)):
            self.show(automatic=True)
        elif (
            not self.hidden
            and not expanded
            and not self.asking
            and not hovered
            and now - self._left_since >= TUCK_AFTER_S
        ):
            self.hide()
        if expanded != self.expanded and not self.hidden:
            self._resize(expanded)
        elif self.hidden:
            self.expanded = expanded
        win32gui.ShowWindow(
            self.ask_button,
            win32con.SW_HIDE
            if self.hidden or (self.app.busy and not self.asking)
            else win32con.SW_SHOWNA,
        )
        title, detail = (
            ("Listening", "Release to send") if listening else _status(self.app, job)
        )
        if (title, detail) != (self.title, self.detail):
            self.title, self.detail = title, detail
            win32gui.SetWindowText(self.hwnd, "Orbyn · " + title + " · " + detail)
            win32gui.InvalidateRect(self.hwnd, None, True)
        busy = bool(self.app.busy)
        # Step aside for a full-screen app, never while work runs (Stop stays reachable).
        covered = not busy and not self.asking and _fullscreen()
        if covered != self.covered:
            self.covered = covered
            win32gui.ShowWindow(
                self.hwnd, win32con.SW_HIDE if covered else win32con.SW_SHOWNOACTIVATE
            )
        win32gui.ShowWindow(
            self.stop_button,
            win32con.SW_SHOWNA if busy and not self.hidden else win32con.SW_HIDE,
        )
        self.companion.show(
            companion_label(
                self.app,
                self.listener,
                fullscreen=_fullscreen(),
                idle=self.app.companion_idle,
            )
        )
        _pump_dialog(self.hwnd)

    def idle(self, seconds):
        """Wait between ticks, handling messages as they arrive: clicks and
        typing are answered at once, and the badge's timer moves it smoothly,
        not at the 4 Hz tick. Never waits past ``seconds``."""

        until = time.monotonic() + seconds
        while not self.closed:
            left = until - time.monotonic()
            if left <= 0:
                break
            _wait(min(left, 0.05) if self.hot else left)
            _pump_dialog(self.hwnd)
            if self.hot and not self.closed and not self._over(self.hot):
                self.hover(None)  # the pointer left the bar: no message says so

    def _over(self, child):
        try:
            return win32gui.WindowFromPoint(_cursor()) == child
        except Exception:
            return False  # secure desktop (UAC, lock): no pointer to read

    def hover(self, child):
        """Light the button under the pointer."""

        buttons = (
            self.ask_button,
            self.open_button,
            self.hide_button,
            self.quit_button,
            self.stop_button,
            self.send_button,
            self.talk_button,
            self.ask_research,
        )
        child = child if child in buttons else None
        if child != self.hot:
            for button in (self.hot, child):
                if button and win32gui.IsWindow(button):  # not during Quit
                    win32gui.InvalidateRect(button, None, False)
            self.hot = child

    def _fit_scrollbar(self):
        """Show the reply card's scrollbar only when the text overflows."""

        show = ctypes.windll.user32.ShowScrollBar
        show(self.reply, win32con.SB_VERT, False)  # measure at the full width
        lines = win32gui.SendMessage(self.reply, win32con.EM_GETLINECOUNT, 0, 0)
        hdc = win32gui.GetDC(self.reply)
        old = win32gui.SelectObject(hdc, _font)
        line = win32gui.GetTextExtentPoint32(hdc, "Ag")[1]
        win32gui.SelectObject(hdc, old)
        win32gui.ReleaseDC(self.reply, hdc)
        if lines * line > win32gui.GetClientRect(self.reply)[3]:
            show(self.reply, win32con.SB_VERT, True)

    def _set_field_fonts(self):
        for child in (self.input, self.reply):
            win32gui.SendMessage(child, win32con.WM_SETFONT, _font, 1)
            win32gui.SendMessage(  # EM_SETMARGINS: breathing room inside the well
                child, win32con.EM_SETMARGINS, 3, _px(4) | (_px(4) << 16)
            )

    def rescale(self, scale):
        """Redo fonts, size and layout for a new display scaling."""

        global _scale, _font, _bold
        if scale == _scale:
            return
        old = _font, _bold
        _scale = scale
        _font, _bold = _make_fonts()
        self._set_field_fonts()
        for font in old:
            win32gui.DeleteObject(font)
        self._resize(self.expanded)

    def _layout(self):
        """Place every control, in design units scaled to the display."""

        wide = self.expanded or self.asking
        y = 17 if wide else 9
        places = {
            self.ask_button: (189 if wide else 139, y, 52, 38),
            self.open_button: (247 if wide else 197, y, 56, 38),
            self.hide_button: (0, 0, 0, 0),  # tucking is automatic
            self.quit_button: (371 if wide else 259, y, 52 if wide else 54, 38),
            self.stop_button: (309, 17, 56, 38),
            self.input: (20, 83, 332, 22),
            self.send_button: (366, 73, 58, 36),
            self.talk_button: (16, 114, 60, 30),
            self.ask_research: (82, 114, 100, 30),
            self.reply: (18, 158, 404, 184),
        }
        for child, box in places.items():
            win32gui.MoveWindow(child, *_px(*box), True)
        self._fit_scrollbar()

    def _size(self, expanded):
        return ASKING if self.asking else EXPANDED if expanded else COMPACT

    def _resize(self, expanded):
        old_width = (
            win32gui.GetWindowRect(self.hwnd)[2] - win32gui.GetWindowRect(self.hwnd)[0]
        )
        width, height = scaled(self._size(expanded))
        left, top, _, _ = win32gui.GetWindowRect(self.hwnd)
        left -= (width - old_width) // 2
        monitor = win32api.MonitorFromWindow(
            self.hwnd, win32con.MONITOR_DEFAULTTONEAREST
        )
        work_left, work_top, work_right, work_bottom = win32api.GetMonitorInfo(monitor)[
            "Work"
        ]
        left = max(work_left, min(left, work_right - width))
        top = max(work_top, min(top, work_bottom - height))
        win32gui.SetWindowPos(
            self.hwnd,
            0,
            left,
            top,
            width,
            height,
            win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
        )
        if not self.dwm_corners:  # before Windows 11: a stepped region
            radius = _px(30)
            win32gui.SetWindowRgn(
                self.hwnd,
                win32gui.CreateRoundRectRgn(0, 0, width, height, radius, radius),
                True,
            )
        self.expanded = expanded
        self._layout()
        win32gui.InvalidateRect(self.hwnd, None, True)
