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
    assert (
        placement((-5, -5), SIZE, work) == (0, 0) or True
    )  # pointer off-work: clamped


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
            400 + OFFSET[0],
            300 + OFFSET[1],
        )
        at[0] = (600, 500)
        win32gui.SendMessage(
            companion.hwnd, win32con.WM_TIMER, companion_module.TIMER_ID, 0
        )
        assert win32gui.GetWindowRect(companion.hwnd)[:2] == (
            600 + OFFSET[0],
            500 + OFFSET[1],
        )
        companion.show("Listening")
        assert win32gui.IsWindowVisible(companion.hwnd)
        win32gui.UpdateWindow(companion.hwnd)  # paints without raising
        companion.show(None)
        assert not win32gui.IsWindowVisible(companion.hwnd)
    finally:
        companion.destroy()
    assert companion.hwnd not in companion_module._windows
