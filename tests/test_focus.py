"""The focus reader: what UIA says has focus, filtered to the target process.

Measured basis (recorded in the design spec, section 2): GetFocusedElement
costs a 2.66ms median, and the AutomationId it reports for a real control is
the SAME id a tree walk reports -- 1001/1002/1004 matched exactly on
SyntheticApp. That equality is what makes the wrong-action comparison
meaningful rather than approximate, so it is asserted here rather than assumed.
"""

import time

import win32gui

from ghostcursor.overlay import dpi  # noqa: F401  -- DPI before any window (D010)
from ghostcursor.perception.focus import read_focused_automation_id
from ghostcursor.perception.uia import iter_elements
from tests.uia_app import BTN_DELETE, BTN_EXPORT, EDIT_FILENAME, SyntheticApp


def _settle(app, spins=40):
    """Pump the synthetic window's queue so UIA can answer about it.

    A same-process UIA call round-trips through SendMessage to the window's
    owning thread, which is THIS thread. Without pumping, the call blocks.
    """
    for _ in range(spins):
        app.pump()
        time.sleep(0.005)


def test_reports_the_focused_controls_automation_id():
    with SyntheticApp(title="GhostCursorFocusRead") as app:
        _settle(app)
        win32gui.SetForegroundWindow(app.hwnd)
        _settle(app)
        for control_id in (BTN_EXPORT, BTN_DELETE, EDIT_FILENAME):
            win32gui.SetFocus(win32gui.GetDlgItem(app.hwnd, control_id))
            _settle(app)
            assert read_focused_automation_id(app.hwnd) == str(control_id)


def test_the_id_matches_what_a_tree_walk_calls_the_same_control():
    """If these ever diverge, the wrong-action comparison is comparing two
    different naming schemes and every result is meaningless."""
    with SyntheticApp(title="GhostCursorFocusRead") as app:
        _settle(app)
        win32gui.SetForegroundWindow(app.hwnd)
        win32gui.SetFocus(win32gui.GetDlgItem(app.hwnd, BTN_EXPORT))
        _settle(app)

        walked = {e.automation_id for e in iter_elements(f".*{app.title}.*")}
        assert read_focused_automation_id(app.hwnd) in walked


def test_returns_empty_when_focus_is_in_another_process():
    """Alt-tabbing to another application is not a mis-click. The reader is
    given a window whose process does not own focus, and must say nothing."""
    with SyntheticApp(title="GhostCursorFocusRead") as app:
        _settle(app)
        # Deliberately do NOT focus the synthetic window: focus stays with
        # whatever owns it (the test runner's console), a different process.
        assert read_focused_automation_id(app.hwnd) == ""


def test_returns_empty_for_a_dead_window_handle():
    """The window can vanish between the walk and the focus read."""
    assert read_focused_automation_id(0) == ""
    assert read_focused_automation_id(999999999) == ""
