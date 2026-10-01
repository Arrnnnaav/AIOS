"""Read one bound window's controls through UI Automation, within a time budget.

Runs ONLY on the perception worker thread (D021): it touches COM, and a hung
target can block a UIA call for tens of seconds. The budget is checked between
elements; a read that runs out returns what it has and says so, and a window
that has gone returns nothing. Only frozen primitives leave this module.
"""

from __future__ import annotations

import time
from typing import Callable

from ghostcursor.harness.frame import ALLOWED_TYPES, RawControl, Rect

#: Default per-window read budget in seconds.
DEFAULT_BUDGET_S = 2.5


def _rect(value) -> Rect | None:
    try:
        return (int(value.left), int(value.top), int(value.right), int(value.bottom))
    except Exception:
        return None


def _is_password(info) -> bool:
    try:
        return bool(info.element.CurrentIsPassword)
    except Exception:
        return False


def _is_offscreen(info) -> bool:
    try:
        return bool(info.element.CurrentIsOffscreen)
    except Exception:
        return not getattr(info, "visible", True)


def read_window(
    hwnd: int,
    *,
    budget_s: float = DEFAULT_BUDGET_S,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[Rect | None, tuple[RawControl, ...], bool]:
    """``(window_rect, controls, timed_out)`` for one top-level window."""

    try:
        from pywinauto import Desktop

        window = Desktop(backend="uia").window(handle=hwnd)
        root = window.element_info
        window_rect = _rect(root.rectangle)
        descendants = root.iter_descendants()
    except Exception:
        return None, (), False

    deadline = clock() + budget_s
    controls: list[RawControl] = []
    timed_out = False
    try:
        for info in descendants:
            if clock() > deadline:
                timed_out = True
                break
            try:
                control_type = info.control_type or ""
                if control_type not in ALLOWED_TYPES:
                    continue
                rect = _rect(info.rectangle)
                runtime_id = tuple(int(v) for v in (info.runtime_id or ()))
                if rect is None or not runtime_id:
                    continue
                controls.append(
                    RawControl(
                        runtime_id=runtime_id,
                        name=info.name or "",
                        control_type=control_type,
                        rect=rect,
                        enabled=bool(info.enabled),
                        offscreen=_is_offscreen(info),
                        is_password=_is_password(info),
                    )
                )
            except Exception:
                continue  # controls vanish mid-walk
    except Exception:
        pass  # the window went away mid-walk; return what was read
    return window_rect, tuple(controls), timed_out


def is_minimized(hwnd: int) -> bool:
    """A minimized window exposes only its title bar; the frame says so."""

    try:
        import win32gui

        return bool(win32gui.IsIconic(hwnd))
    except Exception:
        return False
