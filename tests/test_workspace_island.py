"""The workspace capsule is a view of the existing worker and Stop event."""

import ctypes
import threading
import time

import pytest

from ghostcursor.workspace.island import COMPACT, EXPANDED, HOTKEY_ID, ID_HIDE, ID_OPEN, ID_QUIT, ID_STOP, SHOW_MESSAGE, Island, _status, _wnd_proc


class StubApp:
    def __init__(self):
        self._job_lock = threading.RLock()
        self.background_jobs = []
        self.busy = ""
        self.stop = threading.Event()
        self.background_id = None
        self.actions = []

    def handle(self, action, body):
        self.actions.append((action, body))


def test_island_status_uses_only_generic_worker_and_job_state():
    app = StubApp()
    assert _status(app, None) == ("Ready", "Open your workspace")
    app.busy = "Researching"
    assert _status(app, {"state": "finished"}) == ("Working", "Researching")
    app.busy = "private goal"
    assert _status(app, None) == ("Working", "Task in progress")
    app.busy = ""
    assert _status(app, {"state": "finished", "question": "private question", "result": "private answer"}) == ("Ready", "Research finished")


@pytest.mark.interactive
def test_native_island_opens_stops_and_quits_without_acting_on_desktop():
    import win32con
    import win32gui

    app = StubApp()
    opened = []
    opened_event = threading.Event()

    def open_window(url):
        opened.append(url)
        opened_event.set()

    now = [100.0]
    island = Island(app, "http://127.0.0.1:1/?t=local", open_window, clock=lambda: now[0])
    try:
        assert win32gui.IsWindow(island.hwnd)
        assert win32gui.GetWindowLong(island.hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOPMOST
        assert win32gui.GetWindowRect(island.hwnd)[2] - win32gui.GetWindowRect(island.hwnd)[0] == 320
        assert win32gui.IsWindowVisible(island.open_button)
        assert win32gui.GetWindowText(island.quit_button) == "Quit"
        assert win32gui.GetWindowLong(island.quit_button, win32con.GWL_STYLE) & win32con.WS_TABSTOP
        for button in (island.open_button, island.stop_button, island.hide_button, island.quit_button):
            assert win32gui.GetWindowLong(button, win32con.GWL_STYLE) & win32con.BS_OWNERDRAW
        app.busy = "Researching"
        island.tick()
        assert island.expanded
        assert win32gui.IsWindowVisible(island.stop_button)
        app.busy = ""
        app.background_jobs.append({"id": "1", "state": "finished"})
        island.tick()
        assert island.expanded  # the finished result remains visible briefly
        now[0] += 13
        island.tick()
        assert not island.expanded
        _wnd_proc(island.hwnd, win32con.WM_COMMAND, ID_OPEN, 0)
        _wnd_proc(island.hwnd, win32con.WM_COMMAND, ID_STOP, 0)
        assert opened_event.wait(1)
        assert opened == ["http://127.0.0.1:1/?t=local"]
        assert app.stop.is_set()
        _wnd_proc(island.hwnd, win32con.WM_COMMAND, ID_QUIT, 0)
        assert island.closed and app.actions == [("quit", {})]
    finally:
        if win32gui.IsWindow(island.hwnd):
            win32gui.DestroyWindow(island.hwnd)


@pytest.mark.interactive
def test_island_hide_recall_and_result_auto_reveal():
    import win32con
    import win32gui

    app = StubApp()
    now = [100.0]
    opened = []
    island = Island(app, "http://127.0.0.1:1/?t=local", opened.append, clock=lambda: now[0])
    registered = island.hotkey_available
    island.hotkey_available = True  # exercise visibility even if another app owns the shortcut
    try:
        _wnd_proc(island.hwnd, win32con.WM_COMMAND, ID_HIDE, 0)
        assert island.hidden and not win32gui.IsWindowVisible(island.hwnd)
        win32gui.PostMessage(island.hwnd, SHOW_MESSAGE, 0, 0)
        island.tick()
        assert not island.hidden and win32gui.IsWindowVisible(island.hwnd)
        win32gui.PostMessage(island.hwnd, win32con.WM_HOTKEY, HOTKEY_ID, 0)
        island.tick()
        assert island.hidden
        app.busy = "Researching"
        island.tick()
        assert not island.hidden and island.auto_revealed
        island.hide()
        assert win32gui.IsWindowVisible(island.hwnd)  # Stop surface cannot be hidden
        app.busy = ""
        app.background_jobs.append({"id": "new", "state": "finished"})
        island.tick()
        island.open()
        deadline = time.monotonic() + 1
        while not opened and time.monotonic() < deadline:
            time.sleep(.01)
        assert opened == ["http://127.0.0.1:1/?t=local#work"]
        now[0] += 13
        island.tick()
        assert island.hidden and not win32gui.IsWindowVisible(island.hwnd)
    finally:
        island.hotkey_available = registered
        win32gui.DestroyWindow(island.hwnd)


@pytest.mark.interactive
def test_open_wait_cannot_block_island_stop():
    import win32con
    import win32gui

    app = StubApp()
    started, release = threading.Event(), threading.Event()

    def slow_open(url):
        started.set()
        assert release.wait(2)

    island = Island(app, "http://127.0.0.1:1/?t=local", slow_open)
    try:
        _wnd_proc(island.hwnd, win32con.WM_COMMAND, ID_OPEN, 0)
        assert started.wait(1)
        before = time.monotonic()
        _wnd_proc(island.hwnd, win32con.WM_COMMAND, ID_STOP, 0)
        assert app.stop.is_set() and time.monotonic() - before < 0.5
        assert not release.is_set()  # Stop did not wait for the Edge launch
    finally:
        release.set()
        win32gui.DestroyWindow(island.hwnd)


@pytest.mark.interactive
def test_island_bounds_on_real_and_emulated_monitor_layouts(monkeypatch):
    import win32api
    import win32con
    import win32gui

    island = Island(StubApp(), "http://127.0.0.1:1/?t=local", lambda url: None)
    real_monitor = win32api.MonitorFromWindow(island.hwnd, win32con.MONITOR_DEFAULTTONEAREST)
    primary = win32api.GetMonitorInfo(real_monitor)["Work"]
    layouts = [primary, (-1920, -120, 0, 960), (primary[2], primary[1], primary[2] + 1920, primary[1] + 1080)]
    try:
        for work in layouts:
            with monkeypatch.context() as patch:
                if work != primary:
                    patch.setattr(win32api, "MonitorFromWindow", lambda *args: 1)
                    patch.setattr(win32api, "GetMonitorInfo", lambda monitor: {"Work": work})
                for x, y in ((work[0] + 4, work[1] + 4), (work[2] - COMPACT[0] - 4, work[3] - COMPACT[1] - 4)):
                    win32gui.MoveWindow(island.hwnd, x, y, *COMPACT, True)
                    island._resize(True)
                    left, top, right, bottom = win32gui.GetWindowRect(island.hwnd)
                    assert work[0] <= left and right <= work[2]
                    assert work[1] <= top and bottom <= work[3]
                    assert (right - left, bottom - top) == EXPANDED
                    island._resize(False)
        # Replay a disconnected secondary: Windows selects the nearest live work area.
        win32gui.MoveWindow(island.hwnd, 3100, 40, *COMPACT, True)
        _wnd_proc(island.hwnd, win32con.WM_DISPLAYCHANGE, 0, 0)
        left, top, right, bottom = win32gui.GetWindowRect(island.hwnd)
        assert primary[0] <= left and right <= primary[2]
        assert primary[1] <= top and bottom <= primary[3]
    finally:
        win32gui.DestroyWindow(island.hwnd)


@pytest.mark.interactive
def test_initial_island_placement_respects_a_top_taskbar(monkeypatch):
    import win32api
    import win32gui

    monkeypatch.setattr(win32api, "MonitorFromWindow", lambda *args: 1)
    monkeypatch.setattr(win32api, "GetMonitorInfo", lambda monitor: {"Work": (0, 64, 1920, 1080)})
    island = Island(StubApp(), "http://127.0.0.1:1/?t=local", lambda url: None)
    try:
        left, top, right, bottom = win32gui.GetWindowRect(island.hwnd)
        assert top == 64 and bottom <= 1080
        assert 0 <= left and right <= 1920
    finally:
        win32gui.DestroyWindow(island.hwnd)


@pytest.mark.interactive
def test_shortcut_conflict_keeps_hide_unavailable():
    import win32con
    import win32gui

    user32 = ctypes.windll.user32
    modifiers = win32con.MOD_CONTROL | win32con.MOD_ALT | win32con.MOD_NOREPEAT
    if not user32.RegisterHotKey(None, 99, modifiers, ord("O")):
        pytest.skip("another application already owns Ctrl+Alt+O")
    try:
        island = Island(StubApp(), "http://127.0.0.1:1/?t=local", lambda url: None)
        try:
            assert not island.hotkey_available
            assert not win32gui.IsWindowVisible(island.hide_button)
            _wnd_proc(island.hwnd, win32con.WM_COMMAND, ID_HIDE, 0)
            assert not island.hidden and win32gui.IsWindowVisible(island.hwnd)
        finally:
            win32gui.DestroyWindow(island.hwnd)
    finally:
        user32.UnregisterHotKey(None, 99)


@pytest.mark.interactive
def test_voice_hotkey_keeps_priority_over_island_recall():
    import win32con
    import win32gui

    island = Island(StubApp(), "http://127.0.0.1:1/?t=local", lambda url: None, voice_hotkey="ctrl+alt+o")
    try:
        assert not island.hotkey_available
        assert not win32gui.IsWindowVisible(island.hide_button)
        if not ctypes.windll.user32.RegisterHotKey(None, 98, win32con.MOD_CONTROL | win32con.MOD_ALT | win32con.MOD_NOREPEAT, ord("O")):
            pytest.skip("another application already owns Ctrl+Alt+O")
        ctypes.windll.user32.UnregisterHotKey(None, 98)
    finally:
        win32gui.DestroyWindow(island.hwnd)
