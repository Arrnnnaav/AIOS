"""Small, movable workspace presence. It has no screen-targeting authority."""

from __future__ import annotations

import ctypes
import time
import threading

import win32api
import win32con
import win32gui

from ghostcursor.overlay.window import ensure_class

CLASS = "OrbynWorkspaceIsland"
ID_OPEN, ID_STOP, ID_QUIT, ID_HIDE = 1, 2, 3, 4
HOTKEY_ID = 5
SHOW_MESSAGE = win32con.WM_APP + 1
COMPACT = (320, 56)
EXPANDED = (440, 72)
BG = win32api.RGB(25, 27, 34)
TEXT = win32api.RGB(245, 247, 250)
MUTED = win32api.RGB(172, 181, 195)
ACCENT = win32api.RGB(106, 188, 255)
_windows = {}
_brush = None


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _Message(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_ulong), ("pt", _Point), ("lPrivate", ctypes.c_ulong),
    ]


def _pump_dialog(hwnd):
    """Dispatch mouse events and let Windows handle Tab/Shift-Tab for the buttons."""
    user32 = ctypes.windll.user32
    message = _Message()
    while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, win32con.PM_REMOVE):
        if not user32.IsDialogMessageW(hwnd, ctypes.byref(message)):
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))


def _last_job(app):
    with app._job_lock:
        return dict(app.background_jobs[-1]) if app.background_jobs else None


def _status(app, job):
    if app.busy:
        from ghostcursor.workspace.app import ACTIVITY_LABELS

        return "Working", app.busy if app.busy in ACTIVITY_LABELS else "Task in progress"
    if job and job.get("state") in ("finished", "failed", "stopped", "interrupted"):
        state = job["state"]
        return ("Ready" if state == "finished" else state.title()), "Research " + state
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
            edge = 236 if island.expanded else 135
            win32gui.DrawText(hdc, heading, -1, (37, 9, edge, 30), win32con.DT_SINGLELINE | win32con.DT_END_ELLIPSIS)
            win32gui.SetTextColor(hdc, MUTED)
            detail = island.detail if island.expanded else island.title
            win32gui.DrawText(hdc, detail, -1, (37, 33, edge, 54), win32con.DT_SINGLELINE | win32con.DT_END_ELLIPSIS)
        win32gui.EndPaint(hwnd, paint)
        return 0
    if island is not None:
        if msg == win32con.WM_ERASEBKGND:
            return 1
        if msg == win32con.WM_NCHITTEST:
            return win32con.HTCAPTION  # drag the background; child buttons keep their own clicks
        if msg == win32con.WM_COMMAND and win32api.HIWORD(wparam) == win32con.BN_CLICKED:
            action = win32api.LOWORD(wparam)
            if action == ID_OPEN:
                island.open()
            elif action == ID_STOP:
                island.app.stop.set()
            elif action == ID_HIDE:
                island.hide()
            elif action == ID_QUIT:
                island.app.handle("quit", {})
                win32gui.DestroyWindow(hwnd)
            return 0
        if msg == win32con.WM_HOTKEY and wparam == HOTKEY_ID:
            island.hide() if not island.hidden else island.show()
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
            _windows.pop(hwnd, None)
            return 0
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


class Island:
    """The Win32 UI thread owns this window; jobs stay on the existing worker."""

    def __init__(self, app, url, open_window, *, clock=time.monotonic):
        global _brush
        self.app, self.url, self.open_window = app, url, open_window
        self.clock = clock
        self._opening = threading.Event()
        self.closed = False
        self.hidden = False
        self.auto_revealed = False
        self.expanded = False
        self._notice_until = 0.0
        job = _last_job(app)
        self._last_job_state = (job.get("id"), job.get("state")) if job else None
        self.title, self.detail = "Ready", "Open your workspace"
        if _brush is None:
            _brush = win32gui.CreateSolidBrush(BG)
        ensure_class(CLASS, _wnd_proc, _brush)
        screen = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        width, height = COMPACT
        self.hwnd = win32gui.CreateWindowEx(
            win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW,
            CLASS, "Orbyn · Ready", win32con.WS_POPUP,
            max(0, (screen - width) // 2), 16, width, height,
            None, None, win32api.GetModuleHandle(None), None,
        )
        _windows[self.hwnd] = self
        self.hotkey_available = bool(ctypes.windll.user32.RegisterHotKey(
            self.hwnd, HOTKEY_ID,
            win32con.MOD_CONTROL | win32con.MOD_ALT | win32con.MOD_NOREPEAT,
            win32con.VK_SPACE,
        ))
        win32gui.SetWindowRgn(self.hwnd, win32gui.CreateRoundRectRgn(0, 0, width, height, 30, 30), True)
        style = win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_TABSTOP | win32con.BS_PUSHBUTTON
        module = win32api.GetModuleHandle(None)
        self.open_button = win32gui.CreateWindowEx(0, "BUTTON", "Open", style, 139, 9, 56, 38, self.hwnd, ID_OPEN, module, None)
        self.stop_button = win32gui.CreateWindowEx(0, "BUTTON", "Stop", style, 309, 17, 56, 38, self.hwnd, ID_STOP, module, None)
        self.hide_button = win32gui.CreateWindowEx(0, "BUTTON", "Hide", style, 201, 9, 45, 38, self.hwnd, ID_HIDE, module, None)
        self.quit_button = win32gui.CreateWindowEx(0, "BUTTON", "Quit", style, 252, 9, 54, 38, self.hwnd, ID_QUIT, module, None)
        win32gui.ShowWindow(self.stop_button, win32con.SW_HIDE)
        if not self.hotkey_available:
            win32gui.ShowWindow(self.hide_button, win32con.SW_HIDE)
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
        win32gui.UpdateWindow(self.hwnd)

    def open(self):
        if self._opening.is_set():
            return
        self._opening.set()
        destination = self.url + "#work" if self.clock() < self._notice_until or getattr(self.app, "background_id", None) else self.url

        def launch():
            try:
                self.open_window(destination)
            finally:
                self._opening.clear()

        threading.Thread(target=launch, daemon=True, name="orbyn-open-workspace").start()

    def hide(self):
        if self.app.busy or not self.hotkey_available:
            return  # the Stop surface stays reachable during work
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
        job = _last_job(self.app)
        job_state = (job.get("id"), job.get("state")) if job else None
        if job_state != self._last_job_state:
            if job and job.get("state") in ("finished", "failed", "stopped", "interrupted"):
                self._notice_until = self.clock() + 12
            self._last_job_state = job_state
        expanded = bool(self.app.busy) or self.clock() < self._notice_until
        if self.hidden and expanded:
            self.show(automatic=True)
        elif self.auto_revealed and not expanded:
            self.hide()
        if expanded != self.expanded:
            self._resize(expanded)
        title, detail = _status(self.app, job)
        if (title, detail) != (self.title, self.detail):
            self.title, self.detail = title, detail
            win32gui.SetWindowText(self.hwnd, "Orbyn · " + title + " · " + detail)
            win32gui.InvalidateRect(self.hwnd, None, True)
        busy = bool(self.app.busy)
        win32gui.ShowWindow(self.stop_button, win32con.SW_SHOWNA if busy else win32con.SW_HIDE)
        if self.hotkey_available:
            win32gui.ShowWindow(self.hide_button, win32con.SW_HIDE if busy else win32con.SW_SHOWNA)
        _pump_dialog(self.hwnd)

    def _resize(self, expanded):
        old_width = EXPANDED[0] if self.expanded else COMPACT[0]
        width, height = EXPANDED if expanded else COMPACT
        left, top, _, _ = win32gui.GetWindowRect(self.hwnd)
        left -= (width - old_width) // 2
        monitor = win32api.MonitorFromWindow(self.hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        work_left, work_top, work_right, work_bottom = win32api.GetMonitorInfo(monitor)["Work"]
        left = max(work_left, min(left, work_right - width))
        top = max(work_top, min(top, work_bottom - height))
        win32gui.SetWindowPos(self.hwnd, 0, left, top, width, height, win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
        win32gui.SetWindowRgn(self.hwnd, win32gui.CreateRoundRectRgn(0, 0, width, height, 30, 30), True)
        y = 17 if expanded else 9
        win32gui.MoveWindow(self.open_button, 247 if expanded else 139, y, 56, 38, True)
        win32gui.MoveWindow(self.hide_button, 309 if expanded else 201, y, 56 if expanded else 45, 38, True)
        win32gui.MoveWindow(self.quit_button, 371 if expanded else 252, y, 52 if expanded else 54, 38, True)
        self.expanded = expanded
        win32gui.InvalidateRect(self.hwnd, None, True)
