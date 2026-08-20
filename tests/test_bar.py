"""The control bar as a window: styles, coexistence, teardown.

These assert real Win32 state, not appearance -- the same discipline as
tests/test_overlay.py. Every path tears both windows down in a finally block:
a stranded full-screen window is the failure that locks a user out.
"""

import win32con
import win32gui

from ghostcursor.overlay import dpi  # noqa: F401  -- DPI before any window (D010)
from ghostcursor.overlay import bar, window as ov


def test_the_bar_can_be_clicked_and_focused_and_the_overlay_cannot():
    """The two windows are style-inverses, and that is the whole safety
    argument: the overlay must never take a click or the focus, the bar must
    be able to take both."""
    overlay = ov.create_overlay_window()
    bar_hwnd = None
    try:
        bar_hwnd = bar.create_bar_window()
        ov_ex = win32gui.GetWindowLong(overlay, win32con.GWL_EXSTYLE)
        bar_ex = win32gui.GetWindowLong(bar_hwnd, win32con.GWL_EXSTYLE)

        assert ov_ex & win32con.WS_EX_TRANSPARENT, "overlay stopped being click-through"
        assert ov_ex & win32con.WS_EX_NOACTIVATE, "overlay became focusable"
        assert not (bar_ex & win32con.WS_EX_TRANSPARENT), "bar cannot receive clicks"
        assert not (bar_ex & win32con.WS_EX_NOACTIVATE), "bar cannot take focus"
    finally:
        if bar_hwnd:
            bar.destroy_bar_window(bar_hwnd)
        ov.destroy_overlay_window(overlay)


def test_both_windows_are_visible_at_once():
    overlay = ov.create_overlay_window()
    bar_hwnd = None
    try:
        bar_hwnd = bar.create_bar_window()
        ov.pump_messages_nonblocking()
        assert win32gui.IsWindowVisible(overlay)
        assert win32gui.IsWindowVisible(bar_hwnd)
    finally:
        if bar_hwnd:
            bar.destroy_bar_window(bar_hwnd)
        ov.destroy_overlay_window(overlay)


def test_destroying_the_bar_does_not_end_the_message_loop():
    """The overlay's wnd_proc calls PostQuitMessage on WM_DESTROY. The bar's
    must NOT: collapsing or closing the bar would otherwise post WM_QUIT to
    the whole thread and take the tour down with it."""
    overlay = ov.create_overlay_window()
    try:
        bar_hwnd = bar.create_bar_window()
        # DestroyWindow directly, not bar.destroy_bar_window(): that helper
        # already calls pump_messages_nonblocking() internally, which would
        # silently dequeue a WM_QUIT before this test's own pump ever saw it,
        # making the assertion below blind to exactly the regression it
        # exists to catch.
        win32gui.DestroyWindow(bar_hwnd)
        # PumpWaitingMessages returns True when it dequeued WM_QUIT.
        assert win32gui.PumpWaitingMessages() != 1, (
            "destroying the bar posted WM_QUIT -- the tour's own loop would end"
        )
        assert win32gui.IsWindow(overlay), "overlay died with the bar"
    finally:
        ov.destroy_overlay_window(overlay)


def test_the_bar_is_not_full_screen():
    """It must never cover the region a hint could occupy."""
    bar_hwnd = bar.create_bar_window()
    try:
        left, top, right, bottom = win32gui.GetWindowRect(bar_hwnd)
        vl, vt, vw, vh = dpi.virtual_screen_rect()
        assert (right - left) < vw // 2, "bar is more than half the desktop wide"
        assert (bottom - top) < vh // 4, (
            "bar is more than a quarter of the desktop tall"
        )
    finally:
        bar.destroy_bar_window(bar_hwnd)


def test_clicking_stop_sets_the_request_without_taking_focus():
    """The button must work by mouse alone. Focus is not required, and taking
    it would pull the user out of the app they are being taught."""
    bar_hwnd = bar.create_bar_window()
    try:
        before = win32gui.GetForegroundWindow()
        bar._on_command(bar_hwnd, bar.ID_STOP)
        assert bar.bar_state(bar_hwnd).stop_requested is True
        assert win32gui.GetForegroundWindow() == before, (
            "clicking a bar button stole foreground from the user's app"
        )
    finally:
        bar.destroy_bar_window(bar_hwnd)


def test_requests_clear_so_one_click_is_one_request():
    bar_hwnd = bar.create_bar_window()
    try:
        bar._on_command(bar_hwnd, bar.ID_PAUSE)
        assert bar.bar_state(bar_hwnd).pause_requested is True
        bar.clear_requests(bar_hwnd)
        assert bar.bar_state(bar_hwnd).pause_requested is False, (
            "a single click would be read as a request on every later poll"
        )
    finally:
        bar.destroy_bar_window(bar_hwnd)


def test_status_text_round_trips():
    bar_hwnd = bar.create_bar_window()
    try:
        bar.set_status(bar_hwnd, "step 2 of 5")
        assert bar.get_status(bar_hwnd) == "step 2 of 5"
        status_hwnd = bar._bar_status_hwnd[bar_hwnd]
        assert win32gui.GetWindowText(status_hwnd) == "step 2 of 5", (
            "get_status matched the module dict but the real STATIC control "
            "on screen never received the text"
        )
    finally:
        bar.destroy_bar_window(bar_hwnd)


def test_opening_the_panel_focuses_it_and_closing_releases(monkeypatch):
    """Windows' foreground lock refuses `SetForegroundWindow` for a process
    that is not already frontmost -- measured repeatedly in this repo (D038,
    tests/test_focus.py) and reproduced here: it raises under pytest even
    though the design (spec 2026-08-21-control-bar-design.md S4.4) accepts
    that refusal silently. A bare `GetForegroundWindow() == bar_hwnd`
    assertion would therefore be red in exactly this environment regardless
    of whether open_panel is correct, and -- the more important half of the
    same coin -- it would ALSO be vacuously green if the test process
    happened to already be frontmost, since nothing here would then
    distinguish "already was" from "open_panel put it there".

    So the mutation-sensitive check is a spy on `SetForegroundWindow` that
    still calls through to the real API: it proves open_panel attempted to
    take foreground for the correct hwnd regardless of environment, and it
    fails if that call is skipped (the actual mutation this test must
    catch). The real foreground state is then asserted too, but only when
    the OS actually granted it -- best-effort, not the load-bearing check.
    """
    bar_hwnd = bar.create_bar_window()
    real_sfw = win32gui.SetForegroundWindow
    calls = []

    def spy(hwnd):
        calls.append(hwnd)
        return real_sfw(hwnd)

    monkeypatch.setattr(win32gui, "SetForegroundWindow", spy)
    try:
        assert bar.panel_is_open(bar_hwnd) is False
        bar.open_panel(bar_hwnd)
        assert bar.panel_is_open(bar_hwnd) is True
        assert calls == [bar_hwnd], (
            "open_panel did not attempt to take foreground for the bar"
        )
        bar.close_panel(bar_hwnd)
        assert bar.panel_is_open(bar_hwnd) is False
    finally:
        bar.destroy_bar_window(bar_hwnd)


def test_a_submitted_goal_is_returned_exactly_once():
    """Once, because the caller polls every tick: returning it repeatedly
    would re-announce the same goal on every tick forever."""
    bar_hwnd = bar.create_bar_window()
    try:
        bar.open_panel(bar_hwnd)
        bar.set_panel_text(bar_hwnd, "add a page number")
        bar.submit_panel(bar_hwnd)
        assert bar.take_submitted_goal(bar_hwnd) == "add a page number"
        assert bar.take_submitted_goal(bar_hwnd) is None
    finally:
        bar.destroy_bar_window(bar_hwnd)


def test_submitting_closes_the_panel():
    bar_hwnd = bar.create_bar_window()
    try:
        bar.open_panel(bar_hwnd)
        bar.set_panel_text(bar_hwnd, "export as pdf")
        bar.submit_panel(bar_hwnd)
        assert bar.panel_is_open(bar_hwnd) is False
    finally:
        bar.destroy_bar_window(bar_hwnd)


def test_closing_without_submitting_discards_nothing_and_returns_no_goal():
    bar_hwnd = bar.create_bar_window()
    try:
        bar.open_panel(bar_hwnd)
        bar.set_panel_text(bar_hwnd, "half a thought")
        bar.close_panel(bar_hwnd)
        assert bar.take_submitted_goal(bar_hwnd) is None, (
            "dismissing the box submitted the goal anyway"
        )
    finally:
        bar.destroy_bar_window(bar_hwnd)
