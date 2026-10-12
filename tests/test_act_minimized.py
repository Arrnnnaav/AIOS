"""A minimized PowerPoint no longer refuses Act (D176).

Properties: at proposal time, and only when the pack has no on-screen window,
only windows the pack would accept (its executables and title patterns) are
restored; at the handoff only the exact approved window is restored, only
while the manager still owns the foreground, and only if it is minimized."""

from __future__ import annotations

from types import SimpleNamespace

import win32gui

from ghostcursor.overlay import bar
from ghostcursor.packs.workflow import minimized_owned, windows_or_restored

PACK = SimpleNamespace(
    pack_value={
        "executable_names": ["POWERPNT.EXE"],
        "title_patterns": [r"PowerPoint$"],
    }
)


def test_only_windows_the_pack_would_accept_are_restored():
    rows = [
        (1, True, True, "powerpnt.exe", "Deck - PowerPoint"),  # restored
        (2, True, False, "powerpnt.exe", "Deck - PowerPoint"),  # on screen
        (3, False, True, "powerpnt.exe", "Deck - PowerPoint"),  # hidden
        (4, True, True, "excel.exe", "Book - PowerPoint"),  # another app
        (5, True, True, "", "x - PowerPoint"),  # unreadable process
        (6, True, True, "powerpnt.exe", "Set Up Show"),  # not a pack title
    ]
    assert minimized_owned(PACK, rows) == [1]


def test_restore_runs_only_when_no_pack_window_is_on_screen():
    calls = []
    on_screen = [["w"]]
    found = windows_or_restored(
        PACK, lambda p: on_screen[0], lambda p: calls.append(p) or 1
    )
    assert found == ["w"] and calls == []

    listed = iter([[], ["restored"]])
    found = windows_or_restored(
        PACK, lambda p: next(listed), lambda p: calls.append(p) or 1
    )
    assert found == ["restored"] and calls == [PACK]

    assert windows_or_restored(PACK, lambda p: [], lambda p: 0) == []


def _handoff(monkeypatch, *, live, iconic):
    current = {"hwnd": 41}
    restored = []
    monkeypatch.setattr(win32gui, "GetForegroundWindow", lambda: current["hwnd"])
    monkeypatch.setattr(win32gui, "IsWindow", lambda hwnd: hwnd in live)
    monkeypatch.setattr(win32gui, "IsIconic", lambda hwnd: hwnd in iconic)
    monkeypatch.setattr(bar, "_restore", restored.append)
    monkeypatch.setattr(
        win32gui, "SetForegroundWindow", lambda hwnd: current.update(hwnd=hwnd)
    )
    return current, restored


def test_the_handoff_restores_only_the_exact_minimized_target(monkeypatch):
    current, restored = _handoff(monkeypatch, live=(73, 74), iconic=(73, 74, 75))
    assert bar.restore_focus_if_safe(41, 73) is True and restored == [73]
    current["hwnd"] = 99  # the user left the manager: nothing is restored
    assert bar.restore_focus_if_safe(41, 74) is False and restored == [73]
    current["hwnd"] = 41  # a stale handle: nothing is restored
    assert bar.restore_focus_if_safe(41, 75) is False and restored == [73]


def test_a_target_that_is_not_minimized_is_left_as_it_is(monkeypatch):
    """SW_RESTORE on a maximized window would un-maximize it."""

    _, restored = _handoff(monkeypatch, live=(73,), iconic=())
    assert bar.restore_focus_if_safe(41, 73) is True and restored == []
