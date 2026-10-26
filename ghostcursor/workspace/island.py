"""Small, movable workspace presence. It has no screen-targeting authority."""

from __future__ import annotations

import time

import win32api
import win32con
import win32gui

from ghostcursor.overlay.window import ensure_class

CLASS = "OrbynWorkspaceIsland"
ID_OPEN, ID_STOP, ID_QUIT = 1, 2, 3
COMPACT = (252, 56)
EXPANDED = (410, 72)
BG = win32api.RGB(25, 27, 34)
TEXT = win32api.RGB(245, 247, 250)
MUTED = win32api.RGB(172, 181, 195)
ACCENT = win32api.RGB(106, 188, 255)
_windows = {}
_brush = None


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
            edge = 234 if island.expanded else 139
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
                island.open_window(island.url)
            elif action == ID_STOP:
                island.app.stop.set()
            elif action == ID_QUIT:
                island.app.handle("quit", {})
                win32gui.DestroyWindow(hwnd)
            return 0
        if msg == win32con.WM_CLOSE:
            island.app.handle("quit", {})
            win32gui.DestroyWindow(hwnd)
            return 0
        if msg == win32con.WM_DESTROY:
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
        self.closed = False
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
        win32gui.SetWindowRgn(self.hwnd, win32gui.CreateRoundRectRgn(0, 0, width, height, 30, 30), True)
        style = win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.BS_PUSHBUTTON
        module = win32api.GetModuleHandle(None)
        self.open_button = win32gui.CreateWindowEx(0, "BUTTON", "Open", style, 145, 9, 56, 38, self.hwnd, ID_OPEN, module, None)
        self.stop_button = win32gui.CreateWindowEx(0, "BUTTON", "Stop", style, 304, 17, 56, 38, self.hwnd, ID_STOP, module, None)
        self.quit_button = win32gui.CreateWindowEx(0, "BUTTON", "×", style, 210, 9, 28, 38, self.hwnd, ID_QUIT, module, None)
        win32gui.ShowWindow(self.stop_button, win32con.SW_HIDE)
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
        win32gui.UpdateWindow(self.hwnd)

    def tick(self):
        job = _last_job(self.app)
        job_state = (job.get("id"), job.get("state")) if job else None
        if job_state != self._last_job_state:
            if job and job.get("state") in ("finished", "failed", "stopped", "interrupted"):
                self._notice_until = self.clock() + 12
            self._last_job_state = job_state
        expanded = bool(self.app.busy) or self.clock() < self._notice_until
        if expanded != self.expanded:
            self._resize(expanded)
        title, detail = _status(self.app, job)
        if (title, detail) != (self.title, self.detail):
            self.title, self.detail = title, detail
            win32gui.SetWindowText(self.hwnd, "Orbyn · " + title + " · " + detail)
            win32gui.InvalidateRect(self.hwnd, None, True)
        busy = bool(self.app.busy)
        win32gui.ShowWindow(self.stop_button, win32con.SW_SHOWNA if busy else win32con.SW_HIDE)
        win32gui.PumpWaitingMessages()

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
        win32gui.MoveWindow(self.open_button, 242 if expanded else 145, y, 56, 38, True)
        win32gui.MoveWindow(self.quit_button, 368 if expanded else 210, y, 28, 38, True)
        self.expanded = expanded
        win32gui.InvalidateRect(self.hwnd, None, True)
