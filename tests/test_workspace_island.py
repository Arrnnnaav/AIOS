"""The workspace capsule is a view of the existing worker and Stop event."""

import ctypes
import threading
import time

import pytest

from ghostcursor.workspace import island as island_module
from ghostcursor.workspace.island import ASKING, COMPACT, EXPANDED, scaled, HOTKEY_ID, ID_ASK, ID_HIDE, ID_OPEN, ID_QUIT, ID_RESEARCH, ID_SEND, ID_STOP, ID_TALK, SHOW_MESSAGE, Island, _status, _wnd_proc


class StubApp:
    def __init__(self):
        self._job_lock = threading.RLock()
        self.background_jobs = []
        self.busy = ""
        self.companion_idle = False
        self.stop = threading.Event()
        self.background_id = None
        self.actions = []

    def handle(self, action, body):
        self.actions.append((action, body))
        if action == "say":
            return {"reply": "line one\nline two"}
        if action == "research":
            return {"answer": "cited [s1]"}


@pytest.fixture(autouse=True)
def windowed_desktop(monkeypatch):
    fullscreen = [False]  # the real desktop may have a full-screen app in front
    monkeypatch.setattr(island_module, "_fullscreen", lambda: fullscreen[0])
    monkeypatch.setattr(island_module, "_cursor", lambda: (-30000, -30000))  # never on the bar
    return fullscreen


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
        assert win32gui.GetWindowRect(island.hwnd)[2] - win32gui.GetWindowRect(island.hwnd)[0] == scaled(COMPACT)[0]
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
        assert island.asking and not island.hidden  # the shortcut opens Ask
        win32gui.PostMessage(island.hwnd, win32con.WM_HOTKEY, HOTKEY_ID, 0)
        island.tick()
        assert island.hidden and not island.asking  # pressed again: fold and hide
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
def test_island_ask_uses_the_chat_path_and_shows_the_reply_on_a_card():
    import win32con
    import win32gui

    app = StubApp()
    island = Island(app, "http://127.0.0.1:1/?t=local", lambda url: None)
    try:
        _wnd_proc(island.hwnd, win32con.WM_COMMAND, ID_ASK, 0)
        assert island.asking and win32gui.IsWindowVisible(island.input)
        rect = win32gui.GetWindowRect(island.hwnd)
        assert (rect[2] - rect[0], rect[3] - rect[1]) == scaled(ASKING)
        assert win32gui.SendMessage(island.hwnd, win32con.WM_USER, 0, 0) & 0xFFFF == ID_SEND  # Enter sends
        _wnd_proc(island.hwnd, win32con.WM_COMMAND, ID_SEND, 0)
        assert app.actions == []  # an empty box sends nothing
        win32gui.SetWindowText(island.input, "  what   next? ")
        _wnd_proc(island.hwnd, win32con.WM_COMMAND, ID_SEND, 0)
        deadline = time.monotonic() + 2
        while island._reply is None and time.monotonic() < deadline:
            time.sleep(.01)
        island.tick()
        assert app.actions == [("say", {"text": "what next?"})]
        assert win32gui.GetWindowText(island.input) == ""
        assert win32gui.GetWindowText(island.reply) == "You: what next?\r\nOrbyn: line one\r\nline two"
        assert "what next" not in win32gui.GetWindowText(island.hwnd)  # the title stays generic
        app.busy = "Thinking"
        win32gui.SetWindowText(island.input, "again")
        _wnd_proc(island.hwnd, win32con.WM_COMMAND, ID_SEND, 0)
        assert len(app.actions) == 1 and "busy" in win32gui.GetWindowText(island.reply)
        app.busy = ""
        _wnd_proc(island.hwnd, win32con.WM_COMMAND, win32con.IDCANCEL, 0)  # Escape folds
        assert not island.asking and not win32gui.IsWindowVisible(island.input)
        assert not app.stop.is_set()  # folding is not Stop
    finally:
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
                for x, y in ((work[0] + 4, work[1] + 4), (work[2] - scaled(COMPACT)[0] - 4, work[3] - scaled(COMPACT)[1] - 4)):
                    win32gui.MoveWindow(island.hwnd, x, y, *scaled(COMPACT), True)
                    island._resize(True)
                    left, top, right, bottom = win32gui.GetWindowRect(island.hwnd)
                    assert work[0] <= left and right <= work[2]
                    assert work[1] <= top and bottom <= work[3]
                    assert (right - left, bottom - top) == scaled(EXPANDED)
                    island._resize(False)
        # Replay a disconnected secondary: Windows selects the nearest live work area.
        win32gui.MoveWindow(island.hwnd, 3100, 40, *scaled(COMPACT), True)
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


def _wait_reply(island):
    deadline = time.monotonic() + 2
    while island._reply is None and time.monotonic() < deadline:
        time.sleep(.01)
    island.tick()


@pytest.mark.interactive
def test_island_research_talk_voice_results_and_fullscreen(windowed_desktop):
    import win32con
    import win32gui

    class StubListener:
        armed = []
        held = None
        armed_until = 0.0  # the real Listener's fields the companion reads
        clock = staticmethod(time.monotonic)

        def arm(self, why):
            self.armed.append(why)

    app = StubApp()
    app.background_jobs.append({"id": "old", "state": "finished", "question": "q0", "answer": "seen before"})
    island = Island(app, "http://127.0.0.1:1/?t=local", lambda url: None)
    try:
        _wnd_proc(island.hwnd, win32con.WM_COMMAND, ID_TALK, 0)
        assert "Voice is off" in win32gui.GetWindowText(island.reply)
        island.listener = StubListener()
        _wnd_proc(island.hwnd, win32con.WM_COMMAND, ID_TALK, 0)
        assert StubListener.armed == ["Talk"]  # Talk only arms the existing listener
        island.listener.held = []  # the voice hotkey is held down
        island.tick()
        assert island.expanded and (island.title, island.detail) == ("Listening", "Release to send")
        island.listener.held = None
        island.tick()
        assert island.title == "Ready"

        island.voice("what is next")  # as from the listener's thread
        island.tick()
        assert island.asking and win32gui.IsWindowVisible(island.talk_button)
        _wait_reply(island)
        assert app.actions == [("say", {"text": "what is next"})]
        assert "You (voice): what is next\r\nOrbyn: line one" in win32gui.GetWindowText(island.reply)

        _wnd_proc(island.hwnd, win32con.WM_COMMAND, ID_RESEARCH, 0)
        assert island.research and win32gui.GetWindowText(island.ask_research) == "Research on"
        win32gui.SetWindowText(island.input, "cite it")
        _wnd_proc(island.hwnd, win32con.WM_COMMAND, ID_SEND, 0)
        _wait_reply(island)
        assert app.actions[-1] == ("research", {"text": "cite it"})
        assert win32gui.GetWindowText(island.reply).endswith("Orbyn: cited [s1]")

        app.background_jobs.append({"id": "new", "state": "running", "question": "q1", "answer": ""})
        island.tick()
        assert island.strip == "1 job running"
        app.background_jobs[-1].update(state="finished", answer="line a\nline b" + "x" * 2000)
        island.tick()
        island.tick()  # shown once
        card = island.transcript  # pywin32's GetWindowText stops at 512 characters
        assert card.count("Research finished: q1\r\nline a\r\nline b") == 1
        assert "Open › Work for the rest" in card and "seen before" not in card
        assert island.strip == "" and "q1" not in win32gui.GetWindowText(island.hwnd)

        windowed_desktop[0] = True
        island.tick()
        assert not island.covered  # never while the Ask panel is open
        island.fold()
        island.tick()
        assert island.covered and not win32gui.IsWindowVisible(island.hwnd)
        app.busy = "Researching"
        island.tick()
        assert not island.covered and win32gui.IsWindowVisible(island.hwnd)  # Stop stays reachable
        app.busy = ""
        island.tick()
        windowed_desktop[0] = False
        island.tick()
        assert not island.covered and win32gui.IsWindowVisible(island.hwnd)
    finally:
        win32gui.DestroyWindow(island.hwnd)


@pytest.mark.interactive
def test_a_hidden_bar_peeks_when_the_pointer_comes_to_it(monkeypatch):
    import win32con
    import win32gui

    app = StubApp()
    island = Island(app, "http://127.0.0.1:1/?t=local", lambda url: None)
    registered = island.hotkey_available
    island.hotkey_available = True
    try:
        left, top, right, bottom = win32gui.GetWindowRect(island.hwnd)
        on_bar = ((left + right) // 2, (top + bottom) // 2)
        pointer = [on_bar]
        monkeypatch.setattr(island_module, "_cursor", lambda: pointer[0])
        _wnd_proc(island.hwnd, win32con.WM_COMMAND, ID_HIDE, 0)
        island.tick()
        assert island.hidden  # the pointer is still where Hide was clicked: no instant return
        pointer[0] = (-30000, -30000)
        island.tick()
        assert island.hidden and island.peek_armed
        pointer[0] = on_bar
        island.tick()
        assert not island.hidden and win32gui.IsWindowVisible(island.hwnd)
        island.tick()
        assert not island.hidden  # stays while the pointer rests on it
        pointer[0] = (-30000, -30000)
        island.tick()
        assert island.hidden  # and folds away when it leaves
    finally:
        island.hotkey_available = registered
        win32gui.DestroyWindow(island.hwnd)


@pytest.mark.interactive
def test_result_cards_name_the_job_kind():
    app = StubApp()
    assert _status(app, {"state": "finished", "kind": "deep"}) == ("Ready", "Deep research finished")
    assert _status(app, {"state": "failed", "kind": "crew"}) == ("Failed", "Crew failed")
    island = Island(app, "http://127.0.0.1:1/?t=local", lambda url: None)
    try:
        app.background_jobs.append({"id": "c", "state": "finished", "kind": "crew", "question": "launch", "answer": "1. [plan] ..."})
        island.tick()
        assert "Crew finished: launch" in island.transcript
    finally:
        import win32gui

        win32gui.DestroyWindow(island.hwnd)


def test_bar_shapes_are_anti_aliased_and_sizes_follow_display_scaling(monkeypatch):
    """The pills are drawn large and scaled down: the corner keeps the bar's
    colour, the middle is the fill, and the curve has blended pixels between
    (GDI's RoundRect alone gives only the two). Sizes scale with the DPI."""

    import win32gui

    monkeypatch.setattr(island_module, "_scale", 1.25)
    assert scaled(COMPACT) == (480, 70) and island_module._px(10) == 12
    width, height = 60, 24
    screen = win32gui.GetDC(0)
    memory = win32gui.CreateCompatibleDC(screen)
    bitmap = win32gui.CreateCompatibleBitmap(screen, width, height)
    old = win32gui.SelectObject(memory, bitmap)
    try:
        island_module._smooth(memory, (0, 0, width, height), island_module.BG, island_module.ACCENT)
        assert win32gui.GetPixel(memory, 0, 0) == island_module.BG
        assert win32gui.GetPixel(memory, width // 2, height // 2) == island_module.ACCENT
        edge = {win32gui.GetPixel(memory, x, 0) for x in range(height // 2)}
        blended = edge - {island_module.BG, island_module.ACCENT}
        assert blended  # not stepped

        def channels(c):
            return (c & 0xFF, c >> 8 & 0xFF, c >> 16 & 0xFF)

        ends = list(zip(channels(island_module.BG), channels(island_module.ACCENT)))
        for colour in blended:  # each is a mix of the two, not a bitwise artefact
            assert all(min(e) - 3 <= v <= max(e) + 3 for v, e in zip(channels(colour), ends))
    finally:
        win32gui.SelectObject(memory, old)
        win32gui.DeleteObject(bitmap)
        win32gui.DeleteDC(memory)
        win32gui.ReleaseDC(0, screen)


@pytest.mark.interactive
def test_the_bar_rescales_when_dragged_to_a_monitor_with_other_scaling():
    import ctypes

    import win32gui

    start = island_module._scale
    island = Island(StubApp(), "http://127.0.0.1:1/?t=local", lambda url: None)
    try:
        left, top, _, _ = win32gui.GetWindowRect(island.hwnd)
        dpi = round(start * 96 * 1.5)
        width, height = (round(v * dpi / 96) for v in COMPACT)
        rect = (ctypes.c_long * 4)(left, top, left + width, top + height)
        old_font = island_module._font
        win32gui.SendMessage(island.hwnd, island_module.WM_DPICHANGED, dpi | dpi << 16, ctypes.addressof(rect))
        assert island_module._scale == dpi / 96
        l, t, r, b = win32gui.GetWindowRect(island.hwnd)
        assert (r - l, b - t) == scaled(COMPACT) == (width, height)
        assert island_module._font != old_font
        assert win32gui.SendMessage(island.input, 0x0031, 0, 0) == island_module._font  # WM_GETFONT
        ask = win32gui.GetWindowRect(island.ask_button)
        assert ask[3] - ask[1] == island_module._px(38)
    finally:
        island.rescale(start)
        win32gui.DestroyWindow(island.hwnd)
    assert island_module._scale == start
