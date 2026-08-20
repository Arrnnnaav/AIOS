"""The focus reader: what UIA says has focus, filtered to the target process.

MOST OF THIS FILE IS DELIBERATELY NOT A REAL-FOCUS TEST, and that is a
correction to an earlier version of this plan which specified only real-focus
tests. They could not pass reliably: taking focus requires
`SetForegroundWindow`, and Windows' foreground lock REFUSES it for a process
that is not already frontmost. It succeeded in an interactive probe and then
failed under pytest with `pywintypes.error: (0, 'SetForegroundWindow')`, which
would also fail in CI and any time the terminal is not frontmost.

So the POLICY -- the process filter, the empty-id rule, the never-raise
contract -- is tested deterministically against a fake automation object, and
the environmental claim gets one real-window test that SKIPS honestly when the
OS refuses foreground. A test that only passes when a human happens to be
looking at the right window is not a test.

The real-focus equivalence claim (focus reports the same AutomationId a tree
walk reports: 1001/1002/1004 matched exactly) is recorded in the design spec
section 2.2 as a measurement, which is the right home for a fact about one
machine.
"""

import time

import pytest
import win32gui

from ghostcursor.overlay import dpi  # noqa: F401  -- DPI before any window (D010)
from ghostcursor.perception import focus as focus_module
from ghostcursor.perception.focus import read_focused_automation_id
from tests.uia_app import BTN_EXPORT, SyntheticApp

TARGET_HWND = 4242
TARGET_PID = 777


class _FakeElement:
    def __init__(self, pid: int, aid: str) -> None:
        self.CurrentProcessId = pid
        self.CurrentAutomationId = aid


class _FakeAutomation:
    def __init__(self, element) -> None:
        self._element = element

    def GetFocusedElement(self):
        if isinstance(self._element, Exception):
            raise self._element
        return self._element


@pytest.fixture
def wired(monkeypatch):
    """Point the reader at a fake focused element and a known process."""

    def _wire(element):
        monkeypatch.setattr(
            focus_module, "_automation", lambda: _FakeAutomation(element)
        )
        monkeypatch.setattr(focus_module, "_process_id_for", lambda hwnd: TARGET_PID)

    return _wire


def test_reports_the_id_when_focus_is_in_the_target_process(wired):
    wired(_FakeElement(TARGET_PID, "1001"))
    assert read_focused_automation_id(TARGET_HWND) == "1001"


def test_silent_when_focus_is_in_another_process(wired):
    """Alt-tabbing to Slack is not a mis-click and must never be reported as
    one."""
    wired(_FakeElement(TARGET_PID + 1, "1001"))
    assert read_focused_automation_id(TARGET_HWND) == ""


def test_silent_when_the_focused_control_has_no_automation_id(wired):
    """Common in Chromium and Acrobat. We can see focus moved but cannot name
    where, and naming is the whole point: never accuse without naming."""
    wired(_FakeElement(TARGET_PID, ""))
    assert read_focused_automation_id(TARGET_HWND) == ""


def test_silent_when_there_is_no_focused_element(wired):
    wired(None)
    assert read_focused_automation_id(TARGET_HWND) == ""


def test_never_raises_when_the_automation_call_fails(wired):
    """The caller is the perception worker, whose product is the walk. Focus
    is a nicety and must never cost an observation."""
    wired(OSError("UIA exploded"))
    assert read_focused_automation_id(TARGET_HWND) == ""


def test_silent_for_a_dead_window_handle():
    """No monkeypatching: the guard must fire before anything is consulted."""
    assert read_focused_automation_id(0) == ""
    assert read_focused_automation_id(-1) == ""


def test_silent_when_the_window_has_no_process(monkeypatch):
    monkeypatch.setattr(focus_module, "_process_id_for", lambda hwnd: 0)
    assert read_focused_automation_id(TARGET_HWND) == ""


def test_the_hwnd_guard_holds_even_if_the_process_lookup_succeeds(monkeypatch):
    """The `hwnd <= 0` guard is currently redundant -- `_process_id_for`
    absorbs bad handles and returns 0 -- so nothing else in this file can
    tell whether it is present. That redundancy is a coincidence of the
    current implementation, not a property: make `_process_id_for` answer
    for a bogus handle, as a future change to its error handling could,
    and the guard is the only thing left saying no.

    Same reasoning as D030, where an explicit provenance guard was kept
    despite being redundant, because the redundancy rested on a
    coincidence a later tier could break.
    """
    monkeypatch.setattr(focus_module, "_process_id_for", lambda hwnd: TARGET_PID)
    monkeypatch.setattr(
        focus_module,
        "_automation",
        lambda: _FakeAutomation(_FakeElement(TARGET_PID, "1001")),
    )
    assert read_focused_automation_id(0) == ""
    assert read_focused_automation_id(-1) == ""


def test_against_a_real_window_when_the_os_permits_foreground():
    """The one genuinely end-to-end check. SKIPS rather than fails when
    Windows' foreground lock refuses -- a process that is not already
    frontmost cannot take focus, and that is OS policy, not a defect here."""
    with SyntheticApp(title="GhostCursorFocusRead") as app:
        for _ in range(40):
            app.pump()
            time.sleep(0.005)
        try:
            win32gui.SetForegroundWindow(app.hwnd)
        except Exception as exc:
            pytest.skip(f"OS refused foreground, cannot test real focus: {exc}")
        win32gui.SetFocus(win32gui.GetDlgItem(app.hwnd, BTN_EXPORT))
        for _ in range(40):
            app.pump()
            time.sleep(0.005)
        assert read_focused_automation_id(app.hwnd) == str(BTN_EXPORT)
