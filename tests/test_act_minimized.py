"""A minimized PowerPoint no longer refuses Act (D176).

Properties: at proposal time only the pack's own minimized windows are
restored; at the handoff only the exact approved window is restored, and only
while the manager still owns the foreground."""

from __future__ import annotations

from types import SimpleNamespace

import win32con
import win32gui

from ghostcursor.overlay import bar
from ghostcursor.packs.workflow import minimized_owned

PACK = SimpleNamespace(pack_value={"executable_names": ["POWERPNT.EXE"]})


def test_only_the_packs_visible_minimized_windows_are_restored():
    rows = [
        (1, True, True, "powerpnt.exe"),  # restored
        (2, True, False, "powerpnt.exe"),  # already on screen
        (3, False, True, "powerpnt.exe"),  # hidden, not a user window
        (4, True, True, "excel.exe"),  # another application
        (5, True, True, ""),  # unreadable process
    ]
    assert minimized_owned(PACK, rows) == [1]


def test_the_handoff_restores_only_the_exact_minimized_target(monkeypatch):
    current = {"hwnd": 41}
    shown = []
    monkeypatch.setattr(win32gui, "GetForegroundWindow", lambda: current["hwnd"])
    monkeypatch.setattr(win32gui, "IsWindow", lambda hwnd: hwnd in (73, 74))
    monkeypatch.setattr(win32gui, "IsIconic", lambda hwnd: hwnd != 75)
    monkeypatch.setattr(
        win32gui, "ShowWindow", lambda hwnd, cmd: shown.append((hwnd, cmd))
    )
    monkeypatch.setattr(
        win32gui, "SetForegroundWindow", lambda hwnd: current.update(hwnd=hwnd)
    )

    assert bar.restore_focus_if_safe(41, 73) is True
    assert shown == [(73, win32con.SW_RESTORE)]
    current["hwnd"] = 99  # the user left the manager: nothing is restored
    assert bar.restore_focus_if_safe(41, 74) is False and len(shown) == 1
    current["hwnd"] = 41  # a stale handle: nothing is restored
    assert bar.restore_focus_if_safe(41, 75) is False and len(shown) == 1


def test_a_target_that_is_not_minimized_is_left_as_it_is(monkeypatch):
    """SW_RESTORE on a maximized window would un-maximize it."""

    current = {"hwnd": 41}
    shown = []
    monkeypatch.setattr(win32gui, "GetForegroundWindow", lambda: current["hwnd"])
    monkeypatch.setattr(win32gui, "IsWindow", lambda hwnd: hwnd == 73)
    monkeypatch.setattr(win32gui, "IsIconic", lambda hwnd: False)
    monkeypatch.setattr(win32gui, "ShowWindow", lambda *a: shown.append(a))
    monkeypatch.setattr(
        win32gui, "SetForegroundWindow", lambda hwnd: current.update(hwnd=hwnd)
    )
    assert bar.restore_focus_if_safe(41, 73) is True and shown == []
