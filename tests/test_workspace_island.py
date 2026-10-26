"""The workspace capsule is a view of the existing worker and Stop event."""

import threading

import pytest

from ghostcursor.workspace.island import ID_OPEN, ID_QUIT, ID_STOP, Island, _status, _wnd_proc


class StubApp:
    def __init__(self):
        self._job_lock = threading.RLock()
        self.background_jobs = []
        self.busy = ""
        self.stop = threading.Event()
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
    now = [100.0]
    island = Island(app, "http://127.0.0.1:1/?t=local", opened.append, clock=lambda: now[0])
    try:
        assert win32gui.IsWindow(island.hwnd)
        assert win32gui.GetWindowLong(island.hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOPMOST
        assert win32gui.GetWindowRect(island.hwnd)[2] - win32gui.GetWindowRect(island.hwnd)[0] == 252
        assert win32gui.IsWindowVisible(island.open_button)
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
        assert opened == ["http://127.0.0.1:1/?t=local"]
        assert app.stop.is_set()
        _wnd_proc(island.hwnd, win32con.WM_COMMAND, ID_QUIT, 0)
        assert island.closed and app.actions == [("quit", {})]
    finally:
        if win32gui.IsWindow(island.hwnd):
            win32gui.DestroyWindow(island.hwnd)
