"""Small, movable workspace presence. It has no screen-targeting authority.

Ask (the button or Ctrl+Alt+O) unfolds a type-to-ask panel, as in HeyClicky's
notch: the question goes through the same Chat path as the workspace page
(``App.handle("say")``, or ``"research"`` with Research on), so nothing new
leaves the device, and the reply shows on a card under the bar for follow-ups.
Escape folds it. Talk arms the existing voice listener, and anything it hears
lands on the same card. Finished background research is shown there too, and
the bar steps aside while a full-screen app is in front."""

from __future__ import annotations

import ctypes
import time
import threading

import win32api
import win32con
import win32gui

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
COMPACT = (384, 56)
EXPANDED = (440, 72)
ASKING = (440, 360)
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
_windows = {}
_brush = None
_field_brush = None
_font = None


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
    primary = item.CtlID in (ID_ASK, ID_SEND) or (
        item.CtlID == ID_RESEARCH and island.research
    )
    pressed = bool(item.itemState & win32con.ODS_SELECTED)
    if primary:
        color = PRESSED if pressed else ACCENT
    elif item.CtlID == ID_STOP:
        color = STOP_PRESSED if pressed else STOP
    else:
        color = SECONDARY_PRESSED if pressed else SECONDARY
    brush = win32gui.CreateSolidBrush(color)
    old_brush = win32gui.SelectObject(hdc, brush)
    old_pen = win32gui.SelectObject(hdc, win32gui.GetStockObject(win32con.NULL_PEN))
    try:
        win32gui.RoundRect(hdc, rect.left, rect.top, rect.right, rect.bottom, 16, 16)
    finally:
        win32gui.SelectObject(hdc, old_pen)
        win32gui.SelectObject(hdc, old_brush)
        win32gui.DeleteObject(brush)
    win32gui.SetBkMode(hdc, win32con.TRANSPARENT)
    win32gui.SetTextColor(hdc, BG if primary else TEXT)
    win32gui.DrawText(
        hdc,
        win32gui.GetWindowText(item.hwndItem),
        -1,
        bounds,
        win32con.DT_CENTER | win32con.DT_VCENTER | win32con.DT_SINGLELINE,
    )
    if item.itemState & win32con.ODS_FOCUS:
        win32gui.DrawFocusRect(
            hdc, (rect.left + 3, rect.top + 3, rect.right - 3, rect.bottom - 3)
        )


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
        if island is not None:
            win32gui.SetBkMode(hdc, win32con.TRANSPARENT)
            win32gui.SetTextColor(hdc, ACCENT)
            win32gui.DrawText(hdc, "●", -1, (16, 14, 34, 47), win32con.DT_SINGLELINE)
            win32gui.SetTextColor(hdc, TEXT)
            heading = "Orbyn · " + island.title if island.expanded else "Orbyn"
            edge = 182 if island.expanded or island.asking else 135
            win32gui.DrawText(
                hdc,
                heading,
                -1,
                (37, 9, edge, 30),
                win32con.DT_SINGLELINE | win32con.DT_END_ELLIPSIS,
            )
            win32gui.SetTextColor(hdc, MUTED)
            detail = island.detail if island.expanded else island.title
            win32gui.DrawText(
                hdc,
                detail,
                -1,
                (37, 33, edge, 54),
                win32con.DT_SINGLELINE | win32con.DT_END_ELLIPSIS,
            )
            if island.asking:
                win32gui.DrawText(
                    hdc,
                    island.strip,
                    -1,
                    (192, 118, 424, 144),
                    win32con.DT_SINGLELINE | win32con.DT_END_ELLIPSIS,
                )
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
        global _brush, _field_brush, _font
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
            _brush = win32gui.CreateSolidBrush(BG)
            _field_brush = win32gui.CreateSolidBrush(SECONDARY)
            font = win32gui.LOGFONT()
            font.lfHeight, font.lfFaceName = -15, "Segoe UI"
            _font = win32gui.CreateFontIndirect(font)
        # Before the bar: if this fails no bar window is left behind.
        self.companion = Companion(lambda: _cursor())  # the OS pointer only
        ensure_class(CLASS, _wnd_proc, _brush)
        screen = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        width, height = COMPACT
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
        win32gui.SetWindowRgn(
            self.hwnd, win32gui.CreateRoundRectRgn(0, 0, width, height, 30, 30), True
        )
        style = (
            win32con.WS_CHILD
            | win32con.WS_VISIBLE
            | win32con.WS_TABSTOP
            | win32con.BS_OWNERDRAW
        )
        module = win32api.GetModuleHandle(None)
        self.ask_button = win32gui.CreateWindowEx(
            0, "BUTTON", "Ask", style, 139, 9, 52, 38, self.hwnd, ID_ASK, module, None
        )
        self.open_button = win32gui.CreateWindowEx(
            0, "BUTTON", "Open", style, 197, 9, 56, 38, self.hwnd, ID_OPEN, module, None
        )
        self.send_button = win32gui.CreateWindowEx(
            0,
            "BUTTON",
            "Send",
            style,
            364,
            73,
            60,
            36,
            self.hwnd,
            ID_SEND,
            module,
            None,
        )
        field = win32con.WS_CHILD | win32con.WS_TABSTOP | win32con.ES_AUTOHSCROLL
        self.input = win32gui.CreateWindowEx(
            0, "EDIT", "", field, 16, 76, 340, 30, self.hwnd, ID_INPUT, module, None
        )
        panel = style & ~win32con.WS_VISIBLE
        self.talk_button = win32gui.CreateWindowEx(
            0,
            "BUTTON",
            "Talk",
            panel,
            16,
            114,
            60,
            30,
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
            82,
            114,
            100,
            30,
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
            0, "EDIT", "", card, 16, 154, 408, 190, self.hwnd, ID_REPLY, module, None
        )
        for child in (self.input, self.reply):
            win32gui.SendMessage(child, win32con.WM_SETFONT, _font, 0)
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
            309,
            17,
            56,
            38,
            self.hwnd,
            ID_STOP,
            module,
            None,
        )
        self.hide_button = win32gui.CreateWindowEx(
            0, "BUTTON", "Hide", style, 259, 9, 45, 38, self.hwnd, ID_HIDE, module, None
        )
        self.quit_button = win32gui.CreateWindowEx(
            0, "BUTTON", "Quit", style, 310, 9, 54, 38, self.hwnd, ID_QUIT, module, None
        )
        for hidden in (self.stop_button, self.send_button):
            win32gui.ShowWindow(hidden, win32con.SW_HIDE)
        if not self.hotkey_available:
            win32gui.ShowWindow(self.hide_button, win32con.SW_HIDE)
        self._resize(False)  # initial placement must respect a top/side taskbar
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
        if self.app.busy or not self.hotkey_available:
            return  # the Stop surface stays reachable during work
        self.peek_armed = False  # the pointer is on the bar now; peek after it leaves
        self._notice_until = 0.0
        self.auto_revealed = False
        self.hidden = True
        win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)

    def show(self, *, automatic=False):
        self._resize(self.expanded)  # a disconnected monitor may have held it
        self.hidden = False
        self.auto_revealed = automatic
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
        if self.hidden and not hovered:
            self.peek_armed = True
        if self.hidden and (expanded or (hovered and self.peek_armed)):
            self.show(automatic=True)
        elif self.auto_revealed and not expanded and not self.asking and not hovered:
            self.hide()
        if expanded != self.expanded:
            self._resize(expanded)
        win32gui.ShowWindow(
            self.ask_button,
            win32con.SW_HIDE
            if self.app.busy and not self.asking
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
        covered = not busy and not self.asking and not self.hidden and _fullscreen()
        if covered != self.covered:
            self.covered = covered
            if covered:
                win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
            elif not self.hidden:
                win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
        win32gui.ShowWindow(
            self.stop_button, win32con.SW_SHOWNA if busy else win32con.SW_HIDE
        )
        if self.hotkey_available:
            win32gui.ShowWindow(
                self.hide_button, win32con.SW_HIDE if busy else win32con.SW_SHOWNA
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
        """Wait between ticks. While the badge shows, pump messages every
        30 ms so it follows the pointer smoothly, not at the 4 Hz tick."""

        until = time.monotonic() + seconds
        while (
            self.companion.text is not None
            and not self.closed
            and time.monotonic() < until
        ):
            _pump_dialog(self.hwnd)
            time.sleep(0.03)
        time.sleep(max(0.0, until - time.monotonic()))

    def _size(self, expanded):
        return ASKING if self.asking else EXPANDED if expanded else COMPACT

    def _resize(self, expanded):
        old_width = (
            win32gui.GetWindowRect(self.hwnd)[2] - win32gui.GetWindowRect(self.hwnd)[0]
        )
        width, height = self._size(expanded)
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
        win32gui.SetWindowRgn(
            self.hwnd, win32gui.CreateRoundRectRgn(0, 0, width, height, 30, 30), True
        )
        wide = expanded or self.asking
        y = 17 if wide else 9
        win32gui.MoveWindow(self.ask_button, 189 if wide else 139, y, 52, 38, True)
        win32gui.MoveWindow(self.open_button, 247 if wide else 197, y, 56, 38, True)
        win32gui.MoveWindow(
            self.hide_button, 309 if wide else 259, y, 56 if wide else 45, 38, True
        )
        win32gui.MoveWindow(
            self.quit_button, 371 if wide else 310, y, 52 if wide else 54, 38, True
        )
        self.expanded = expanded
        win32gui.InvalidateRect(self.hwnd, None, True)
