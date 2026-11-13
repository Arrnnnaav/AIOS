"""The cursor companion: a status badge beside the OS pointer (HeyClicky's
cursor companion). It says only generic state and never takes a position
from anything but the pointer."""

import ctypes
import threading
import types

import pytest

from ghostcursor.workspace import companion as companion_module
from ghostcursor.workspace.companion import (
    OFFSET,
    SIZE,
    Companion,
    label,
    placement,
    pulse,
)


def _app(busy=""):
    return types.SimpleNamespace(busy=busy, _job_lock=threading.RLock())


def _listener(held=None, armed_until=0.0, now=100.0):
    return types.SimpleNamespace(held=held, armed_until=armed_until, clock=lambda: now)


def test_label_is_generic_state_only():
    assert label(_app(), None) is None
    assert label(_app(), _listener()) is None
    assert label(_app(), _listener(held=[])) == "Listening"  # hold-to-talk
    assert (
        label(_app(), _listener(armed_until=101.0)) == "Listening"
    )  # Talk / wake word
    assert label(_app(), _listener(armed_until=100.0)) is None  # the window has passed
    assert label(_app("Thinking"), None) == "Thinking"
    assert label(_app("Researching"), _listener()) == "Researching"
    assert label(_app("Thinking"), _listener(held=[])) == "Listening"
    assert label(_app("book flights to my sister's"), None) == "Working"  # never a goal


def test_label_hides_over_a_full_screen_app():
    assert label(_app("Thinking"), _listener(held=[]), fullscreen=True) is None
    assert label(_app("Thinking"), None, fullscreen=False) == "Thinking"


def test_the_badge_window_is_click_through_and_never_takes_focus():
    import win32con

    for flag in (
        win32con.WS_EX_LAYERED,
        win32con.WS_EX_TRANSPARENT,
        win32con.WS_EX_TOPMOST,
        win32con.WS_EX_TOOLWINDOW,
        win32con.WS_EX_NOACTIVATE,
    ):
        assert companion_module.EX_STYLE & flag, flag
    assert companion_module.WDA_EXCLUDEFROMCAPTURE == 0x11


def test_placement_sits_beside_the_pointer_and_stays_on_the_work_area():
    work = (0, 0, 1920, 1040)
    assert placement((500, 400), SIZE, work) == (500 + OFFSET[0], 400 + OFFSET[1])
    right = placement((1910, 400), SIZE, work)
    assert right == (1910 - OFFSET[0] - SIZE[0], 400 + OFFSET[1])
    bottom = placement((500, 1035), SIZE, work)
    assert bottom == (500 + OFFSET[0], 1035 - OFFSET[1] - SIZE[1])
    exact = placement(
        (1920 - OFFSET[0] - SIZE[0], 1040 - OFFSET[1] - SIZE[1]), SIZE, work
    )
    assert exact == (1920 - SIZE[0], 1040 - SIZE[1])  # fits exactly: not flipped
    assert placement((90, 10), SIZE, (0, 0, 100, 1000)) == (0, 10 + OFFSET[1])  # too narrow: clamped
    second = (1920, 0, 3840, 1080)  # a monitor to the right
    assert placement((1925, 5), SIZE, second) == (1925 + OFFSET[0], 5 + OFFSET[1])


def test_pulse_breathes_between_zero_and_one():
    assert pulse(0) == 0
    assert pulse(0.6) == pytest.approx(1)
    assert pulse(1.2) == pytest.approx(0, abs=1e-9)
    assert all(0 <= pulse(t / 10) <= 1 for t in range(40))


def test_companion_position_comes_only_from_the_pointer():
    """Rule 3: nothing in the module accepts a point from a caller other than
    the cursor callable the island hands it."""
    import inspect

    source = inspect.getsource(companion_module)
    assert "self.cursor()" in source
    assert "def show(self, text: str | None)" in source  # a label, never a point


@pytest.mark.interactive
def test_native_companion_is_click_through_follows_and_hides():
    import win32con
    import win32gui

    at = [(400, 300)]
    companion = Companion(lambda: at[0])
    try:
        style = win32gui.GetWindowLong(companion.hwnd, win32con.GWL_EXSTYLE)
        for flag in (
            win32con.WS_EX_LAYERED,
            win32con.WS_EX_TRANSPARENT,
            win32con.WS_EX_TOPMOST,
            win32con.WS_EX_TOOLWINDOW,
            win32con.WS_EX_NOACTIVATE,
        ):
            assert style & flag
        affinity = ctypes.c_uint(0)
        ctypes.windll.user32.GetWindowDisplayAffinity(
            companion.hwnd, ctypes.byref(affinity)
        )
        assert affinity.value == companion_module.WDA_EXCLUDEFROMCAPTURE
        assert not win32gui.IsWindowVisible(companion.hwnd)
        companion.show("Thinking")
        assert win32gui.IsWindowVisible(companion.hwnd)
        assert win32gui.GetWindowRect(companion.hwnd)[:2] == (
            400 + round(OFFSET[0] * companion_module._scale),
            300 + round(OFFSET[1] * companion_module._scale),
        )
        at[0] = (600, 500)
        win32gui.SendMessage(
            companion.hwnd, win32con.WM_TIMER, companion_module.TIMER_ID, 0
        )
        assert win32gui.GetWindowRect(companion.hwnd)[:2] == (
            600 + round(OFFSET[0] * companion_module._scale),
            500 + round(OFFSET[1] * companion_module._scale),
        )
        companion.show("Listening")
        assert win32gui.IsWindowVisible(companion.hwnd)
        win32gui.UpdateWindow(companion.hwnd)  # paints without raising
        companion.show(None)
        assert not win32gui.IsWindowVisible(companion.hwnd)
        companion.show("")  # the resting dot
        assert win32gui.IsWindowVisible(companion.hwnd)
        win32gui.UpdateWindow(companion.hwnd)
        companion.show(None)
        assert not win32gui.IsWindowVisible(companion.hwnd)
    finally:
        companion.destroy()
    assert companion.hwnd not in companion_module._windows


def test_a_failed_move_never_ends_the_session(monkeypatch):
    """Tier-1 review 12 Nov: SetWindowPos raising would leave Island.tick
    and end the app loop."""
    import win32gui

    def refuse(*args):
        raise win32gui.error(5, "SetWindowPos", "Access is denied.")

    monkeypatch.setattr(companion_module.win32gui, "SetWindowPos", refuse)
    badge = object.__new__(Companion)
    badge.cursor, badge.hwnd, badge.at, badge.pointer = (lambda: (100, 100)), 0, None, None
    badge.arrow = 1.0
    badge.follow()
    assert badge.at is None  # retried on the next timer tick
    badge.follow()  # same pointer, but the move failed: it tries again
    assert badge.at is None
    monkeypatch.setattr(companion_module.win32gui, "SetWindowPos", lambda *a: None)
    badge.follow()
    assert badge.at is not None


def test_the_island_pumps_fast_only_while_the_badge_shows(monkeypatch):
    from ghostcursor.workspace import island as island_module

    pumps = []
    monkeypatch.setattr(island_module, "_pump_dialog", pumps.append)
    bar = object.__new__(island_module.Island)
    bar.hwnd, bar.closed = 7, False
    bar.companion = types.SimpleNamespace(text=None)
    bar.idle(0.1)
    assert pumps == []
    bar.companion.text = "Thinking"
    bar.idle(0.2)
    assert len(pumps) >= 3 and set(pumps) == {7}
    pumps.clear()
    bar.closed = True
    bar.idle(0.05)
    assert pumps == []


def test_the_resting_dot_is_opt_in_and_yields_to_activity():
    from ghostcursor.workspace.companion import blinking

    assert label(_app(), None) is None  # off by default
    assert label(_app(), None, idle=True) == ""  # a dot, no words
    assert label(_app("Thinking"), None, idle=True) == "Thinking"
    assert label(_app(), _listener(held=[]), idle=True) == "Listening"
    assert label(_app(), None, idle=True, fullscreen=True) is None
    assert not blinking(0) and not blinking(4.84)
    assert blinking(4.85) and blinking(4.99) and not blinking(5.0)
    assert blinking(9.9)


def test_companion_idle_setting_is_off_unless_literally_true(tmp_path):
    import json

    from ghostcursor import settings

    path = tmp_path / "settings.json"
    assert settings.companion_idle(path) is False
    for value, on in ((True, True), (False, False), ("true", False), (1, False)):
        path.write_text(json.dumps({"companion_idle": value}), encoding="utf-8")
        assert settings.companion_idle(path) is on, value


def test_the_island_pumps_fast_for_the_resting_dot_too(monkeypatch):
    from ghostcursor.workspace import island as island_module

    pumps = []
    monkeypatch.setattr(island_module, "_pump_dialog", pumps.append)
    bar = object.__new__(island_module.Island)
    bar.hwnd, bar.closed = 7, False
    bar.companion = types.SimpleNamespace(text="")
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    monkeypatch.setattr(island_module, "time", types.SimpleNamespace(monotonic=lambda: now[0], sleep=sleep))
    bar.idle(0.35)
    assert len(pumps) == 4  # every 100 ms for the resting dot, not every 30 ms


def test_idle_stops_pumping_when_the_badge_hides_and_never_overruns(monkeypatch):
    """Tier-1 review 13 Nov: idle() must stop fast pumping once the badge is
    hidden mid-wait, and return within its time so the main loop keeps pace."""

    from ghostcursor.workspace import island as island_module

    bar = object.__new__(island_module.Island)
    bar.hwnd, bar.closed = 7, False
    bar.companion = types.SimpleNamespace(text="Thinking")
    pumps = []

    def pump(hwnd):
        pumps.append(hwnd)
        if len(pumps) == 2:
            bar.companion.text = None  # hidden by a tick's message

    monkeypatch.setattr(island_module, "_pump_dialog", pump)
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    monkeypatch.setattr(island_module, "time", types.SimpleNamespace(monotonic=lambda: now[0], sleep=sleep))
    bar.idle(0.3)
    assert len(pumps) == 2
    assert now[0] == pytest.approx(0.3)  # waits out the rest, never more


def test_two_switches_flipped_at_once_both_stick(tmp_path):
    import threading

    from ghostcursor import settings

    path = tmp_path / "settings.json"
    keys = [f"k{i}" for i in range(16)]
    threads = [threading.Thread(target=settings._set, args=(k, True, path)) for k in keys]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(settings.load(path).get(k) is True for k in keys)


def test_the_dot_changes_only_a_few_times_a_second():
    """The timer repaints only when radius() changes (13 Nov: 1.2% of a core
    when it repainted every 30 ms)."""
    from ghostcursor.workspace.companion import radius

    for text in ("", "Thinking"):
        frames = [radius(text, t * 0.03) for t in range(200)]  # 6 s at 30 ms
        changes = sum(a != b for a, b in zip(frames, frames[1:]))
        assert 0 < changes <= 6 * 8, (text, changes)
    assert radius("", 4.9) == 0  # blink
    assert radius("", 0) == 3 and radius("Thinking", 0) == 4 and radius("Thinking", 0.6) == 6


def test_the_timer_repaints_when_the_dot_changes_and_not_otherwise(monkeypatch):
    import time

    import win32con

    painted = []
    monkeypatch.setattr(companion_module.win32gui, "InvalidateRect", lambda h, r, e: painted.append(h))
    badge = object.__new__(Companion)
    badge.text, badge.frame, badge.started = "", None, time.monotonic()
    badge.follow = lambda: None
    monkeypatch.setitem(companion_module._windows, 4242, badge)
    tick = lambda: companion_module._wnd_proc(4242, win32con.WM_TIMER, companion_module.TIMER_ID, 0)
    tick()
    assert painted == [4242]  # first frame
    tick()
    assert painted == [4242]  # same radius: no repaint
    badge.started = time.monotonic() - 4.9  # now in a blink
    tick()
    assert painted == [4242, 4242]


def test_a_badge_windows_cannot_keep_out_of_captures_never_shows():
    """EGM design review 13 Nov: if SetWindowDisplayAffinity fails the badge
    would appear in screenshots and the D179 picture, so it never shows."""
    import pytest

    def never(*a):
        raise AssertionError("a capture-visible badge was shown")

    mp = pytest.MonkeyPatch()
    mp.setattr(companion_module.win32gui, "ShowWindow", never)
    mp.setattr(companion_module.win32gui, "InvalidateRect", never)
    try:
        badge = object.__new__(Companion)
        badge.capturable, badge.text, badge.hwnd = True, None, 0
        badge.show("Thinking")
        assert badge.text is None
    finally:
        mp.undo()


def test_the_resting_dot_wait_never_overruns(monkeypatch):
    """Tier-1 review 13 Nov: the 0.1 s resting step is bounded by the time
    left. A fake clock makes this exact, not a race with Windows sleeps."""
    from ghostcursor.workspace import island as island_module

    now = [0.0]
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(island_module, "time", types.SimpleNamespace(monotonic=lambda: now[0], sleep=sleep))
    monkeypatch.setattr(island_module, "_pump_dialog", lambda hwnd: None)
    bar = object.__new__(island_module.Island)
    bar.hwnd, bar.closed = 7, False
    bar.companion = types.SimpleNamespace(text="")
    bar.idle(0.25)
    assert now[0] == pytest.approx(0.25) and max(slept) <= 0.1 + 1e-9

def test_the_badge_renders_with_soft_edges_at_the_display_scale():
    """Real per-pixel alpha: the corners are clear, the pill is solid, and
    its curve has partly transparent pixels (anti-aliased, not stepped)."""

    assert companion_module.size_px(1.25) == (165, 35)  # 132x28 design units
    for scale in (1.0, 1.25, 2.0):
        image = companion_module.render("Thinking", 5, scale)
        assert image.size == companion_module.size_px(scale)
        alpha = image.getchannel("A")
        width, height = image.size
        assert alpha.getpixel((0, 0)) == 0 and alpha.getpixel((width - 1, 0)) == 0
        assert alpha.getpixel((height // 2, height // 2)) > 200  # inside the pill
        edge = [alpha.getpixel((x, 0)) for x in range(height)]
        assert any(0 < a < 230 for a in edge)  # the curve is smoothed
    dot = companion_module.render("", 3, 1.0)
    assert dot.getchannel("A").getpixel((dot.width - 1, dot.height // 2)) == 0  # just the disc


def test_the_badge_bitmap_is_premultiplied_bgra():
    from PIL import Image

    image = Image.new("RGBA", (2, 1))
    image.putpixel((0, 0), (200, 100, 50, 255))
    image.putpixel((1, 0), (200, 100, 50, 128))
    data = companion_module._premultiplied(image)
    assert data[:4] == bytes((50, 100, 200, 255))
    assert data[4:] == bytes((25, 50, 100, 128))  # colour scaled by alpha


def test_the_badge_offset_scales_with_the_display():
    work = (0, 0, 1920, 1080)
    assert placement((100, 100), (165, 35), work, 1.25) == (
        100 + round(OFFSET[0] * 1.25),
        100 + round(OFFSET[1] * 1.25),
    )


def test_the_badge_takes_the_pointer_monitors_scaling_and_a_large_pointer(monkeypatch):
    """Dragged to a 150% monitor the badge is resized and repainted there;
    with a 2x pointer it sits twice as far off, clear of the bigger arrow."""

    moves, painted = [], []
    monkeypatch.setattr(companion_module, "_scale", 1.0)
    monkeypatch.setattr(companion_module, "monitor_scale", lambda monitor: 1.5)
    monkeypatch.setattr(companion_module.win32gui, "SetWindowPos", lambda *a: moves.append(a))
    monkeypatch.setattr(companion_module.win32gui, "InvalidateRect", lambda h, r, e: painted.append(h))
    badge = object.__new__(Companion)
    badge.cursor, badge.hwnd, badge.at, badge.pointer = (lambda: (100, 100)), 7, None, None
    badge.arrow = 2.0
    badge.follow()
    assert companion_module._scale == 1.5
    assert moves[-1][2:6] == (100 + round(OFFSET[0] * 3), 100 + round(OFFSET[1] * 3), *companion_module.size_px(1.5))
    assert painted == [7]  # repainted at the new size
    badge.pointer = None  # same monitor, moved: no repaint for the scaling
    badge.follow()
    assert painted == [7]


def test_the_pointer_size_setting_is_read_and_bounded(monkeypatch):
    import winreg

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    values = iter([(64, 4), (16, 4)])
    monkeypatch.setattr(winreg, "OpenKey", lambda *a: Key())
    monkeypatch.setattr(winreg, "QueryValueEx", lambda key, name: next(values))
    assert companion_module.pointer_scale() == 2.0
    assert companion_module.pointer_scale() == 1.0  # never smaller than standard

    def missing(*a):
        raise FileNotFoundError

    monkeypatch.setattr(winreg, "OpenKey", missing)
    assert companion_module.pointer_scale() == 1.0
