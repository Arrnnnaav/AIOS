"""Bind a session to the exact windows the user chose -- several at once.

A harness session may span applications (D164), so it binds a small set of
top-level windows. Each binding records the exact HWND, owning PID, executable
and file version at bind time; every later observation revalidates all four,
and any change ends that window's participation (``TARGET_LOST``). There is no
title matching, no rediscovery of "a similar window", and no foreground read
(D075): the user picks, the harness holds exactly what was picked.

HWNDs and PIDs stay on this machine: they are never sent to a model, written to
a tracked file, or persisted in the session store.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Sequence

from ghostcursor import policy

#: Windows a session may never bind: credential prompts, password managers,
#: the lock screen and elevation prompts.
DENYLIST = frozenset(
    {
        "keepass.exe",
        "keepassxc.exe",
        "1password.exe",
        "bitwarden.exe",
        "dashlane.exe",
        "credentialuibroker.exe",
        "consent.exe",
        "logonui.exe",
        "lockapp.exe",
    }
)

#: At most this many windows in one session.
MAX_WINDOWS = 4


def denied(executable: str) -> bool:
    """Never bound: the built-in list or the organisation's (D180)."""

    return executable in DENYLIST or executable in policy.blocked_apps()


class BindingError(ValueError):
    """The requested binding is not allowed."""


@dataclass(frozen=True)
class Identity:
    pid: int
    executable: str  # basename, casefolded
    version: str


@dataclass(frozen=True)
class WindowBinding:
    index: int  # 1..n within the session
    hwnd: int
    identity: Identity

    @property
    def label(self) -> str:
        """The only name a model ever sees for this window: ``w1``, ``w2``..."""

        return f"w{self.index}"


@dataclass(frozen=True)
class BindableWindow:
    """A window the user may choose. ``title`` is shown locally only."""

    hwnd: int
    executable: str
    title: str


def identify(hwnd: int) -> Identity | None:
    """Live identity of a top-level window, or None if it is gone."""

    try:
        import win32gui
        import win32process

        from ghostcursor.perception.appinfo import _exe_path_for_pid, _version_for

        if not win32gui.IsWindow(hwnd):
            return None
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        path = _exe_path_for_pid(pid)
        if not path:
            return None
        kind = "appx" if "WindowsApps" in path else "win32"
        return Identity(
            pid, os.path.basename(path).casefold(), _version_for(path, kind)
        )
    except Exception:
        return None


def _visible_top_level() -> list[tuple[int, str]]:
    import win32con
    import win32gui

    found: list[tuple[int, str]] = []

    def visit(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        if (
            win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            & win32con.WS_EX_TOOLWINDOW
        ):
            return True
        title = win32gui.GetWindowText(hwnd)
        if title.strip():
            found.append((hwnd, title))
        return True

    win32gui.EnumWindows(visit, None)
    return found


def bindable_windows(
    *,
    enumerate_windows: Callable[[], list[tuple[int, str]]] = _visible_top_level,
    identify_window: Callable[[int], Identity | None] = identify,
    own_pid: int | None = None,
) -> list[BindableWindow]:
    """Every window the user may choose from, in enumeration order."""

    own = os.getpid() if own_pid is None else own_pid
    choices = []
    for hwnd, title in enumerate_windows():
        identity = identify_window(hwnd)
        if identity is None or identity.pid == own or denied(identity.executable):
            continue
        choices.append(BindableWindow(hwnd, identity.executable, title))
    return choices


def bind(
    hwnds: Sequence[int],
    *,
    identify_window: Callable[[int], Identity | None] = identify,
    own_pid: int | None = None,
) -> tuple[WindowBinding, ...]:
    """Bind exactly these windows, in this order, or refuse."""

    own = os.getpid() if own_pid is None else own_pid
    if not hwnds:
        raise BindingError("choose at least one window")
    if len(hwnds) > MAX_WINDOWS:
        raise BindingError(f"at most {MAX_WINDOWS} windows per session")
    if len(set(hwnds)) != len(hwnds):
        raise BindingError("the same window was chosen twice")
    bindings = []
    for index, hwnd in enumerate(hwnds, start=1):
        identity = identify_window(hwnd)
        if identity is None:
            raise BindingError(f"window {index} is gone")
        if identity.pid == own:
            raise BindingError("Orbyn cannot bind its own windows")
        if denied(identity.executable):
            raise BindingError(f"{identity.executable} is never bound")
        bindings.append(WindowBinding(index, hwnd, identity))
    return tuple(bindings)


def still_bound(
    binding: WindowBinding,
    *,
    identify_window: Callable[[int], Identity | None] = identify,
) -> bool:
    """True only while the same HWND belongs to the same PID, executable and
    version recorded at bind time. Never rebinds."""

    return identify_window(binding.hwnd) == binding.identity
