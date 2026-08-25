"""Tier 1 perception: Windows UI Automation via pywinauto.

Reference: D:\\tracker\\docs\\ghostcursor\\python-uiautomation-for-windows-uiautomation.docx,
D:\\tracker\\docs\\ghostcursor\\pywinauto-windows-gui-automation-with-python.docx
"""

import os
import re
from dataclasses import dataclass, field

import win32gui
import win32process
from pywinauto import Desktop

from ghostcursor.overlay import dpi

# Windows parks minimized windows at (-32000, -32000). Anything at or beyond
# this is not on screen, and pointing at it draws the hint into the void.
_MINIMIZED_SENTINEL = -30000


def is_on_screen(bbox: tuple[int, int, int, int] | None) -> bool:
    """True if bbox is a real, non-degenerate rect that overlaps the desktop.

    Guards three separate failure modes seen in practice:
      * minimized windows, parked at (-32000, -32000);
      * degenerate zero-area rects;
      * windows dragged fully off the edge of the virtual desktop.
    """
    if bbox is None:
        return False

    left, top, right, bottom = bbox
    if left <= _MINIMIZED_SENTINEL or top <= _MINIMIZED_SENTINEL:
        return False
    if right - left <= 0 or bottom - top <= 0:
        return False

    vl, vt, vw, vh = dpi.virtual_screen_rect()
    overlaps_x = right > vl and left < vl + vw
    overlaps_y = bottom > vt and top < vt + vh
    return overlaps_x and overlaps_y


def windows_matching(title_re: str) -> list[int]:
    """HWNDs of visible, non-minimized, on-screen top-level windows whose
    title matches title_re, in z-order.

    The single place this enumeration lives. It was duplicated in
    perception/appinfo.py, and the two copies drifted: this one excluded
    minimized and off-screen windows (a hint cannot be drawn on one) while
    the copy did not — so a minimized window could supply the app identity
    that observations are persisted under, while grounding refused that same
    window. Identity and grounding must agree on which window they mean.
    """
    pattern = re.compile(title_re)
    matches: list[int] = []

    def _collect(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return
        if pattern.search(win32gui.GetWindowText(hwnd)) and is_on_screen(
            win32gui.GetWindowRect(hwnd)
        ):
            matches.append(hwnd)

    try:
        win32gui.EnumWindows(_collect, None)
    except Exception:
        # A transient desktop/session access failure means "no visible
        # target" for this observation, not a worker-killing exception.
        return []
    return matches


def first_matching_hwnd(title_re: str) -> int:
    """The topmost visible, non-minimized, on-screen window matching title_re,
    or 0 when there is none.

    Warm-up is keyed on this, so it must agree with the window grounding walks
    on which window is meant. Both are GATED by the same windows_matching
    enumeration, but the walk (iter_elements) hands the final selection to
    pywinauto's Desktop().window(title_re=...), not to this function -- so
    with several matching windows the two can name different ones. The
    consequence is bounded: a sibling handle among the matches still gets its
    own warm-up patience, it is just not guaranteed to be the same handle
    grounding actually walked.
    """
    matches = windows_matching(title_re)
    return matches[0] if matches else 0


def _executable_name_for_hwnd(hwnd: int) -> str:
    """Owning executable basename, or an empty string when unavailable."""
    try:
        from ghostcursor.perception.appinfo import _exe_path_for_pid

        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        return os.path.basename(_exe_path_for_pid(pid) or "").casefold()
    except Exception:
        return ""


def windows_matching_executable(title_re: str, executable_name: str) -> list[int]:
    """Title matches whose owning executable also matches exactly."""
    expected = os.path.basename(executable_name).casefold()
    return [
        hwnd
        for hwnd in windows_matching(title_re)
        if _executable_name_for_hwnd(hwnd) == expected
    ]


def first_matching_hwnd_for_executable(title_re: str, executable_name: str) -> int:
    matches = windows_matching_executable(title_re, executable_name)
    return matches[0] if matches else 0


def _raw_window_rect(title_re: str) -> tuple[int, int, int, int] | None:
    """Fallback: raw win32gui geometry for a visible, non-minimized top-level
    window matching title_re, for the cases where UIA exposes no usable
    geometry at all."""
    for hwnd in windows_matching(title_re):
        return win32gui.GetWindowRect(hwnd)
    return None


def find_element(
    title_re: str, control_type: str | None = None, name_re: str | None = None
) -> tuple[int, int, int, int] | None:
    """Find one element in a top-level window matching title_re, optionally
    filtered by control_type ("Button", "Edit", ...) and name_re.

    Returns (left, top, right, bottom) in screen coordinates, or None if no
    window or no matching descendant was found.
    """
    try:
        window = Desktop(backend="uia").window(title_re=title_re)
        window.wait("exists", timeout=3)
    except Exception:
        return None

    candidates = (
        window.descendants(control_type=control_type)
        if control_type
        else window.descendants()
    )
    for ctrl in candidates:
        if name_re and name_re.lower() not in ctrl.window_text().lower():
            continue
        rect = ctrl.rectangle()
        bbox = (rect.left, rect.top, rect.right, rect.bottom)
        if is_on_screen(bbox):
            return bbox

    return None


def window_bbox(title_re: str) -> tuple[int, int, int, int] | None:
    """Fallback: bbox of the whole top-level window, when no specific
    descendant match is needed/found."""
    try:
        window = Desktop(backend="uia").window(title_re=title_re)
        window.wait("exists", timeout=3)
        rect = window.rectangle()
        bbox = (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        bbox = None

    if not is_on_screen(bbox):
        # Covers minimized, degenerate and off-desktop rects alike.
        return _raw_window_rect(title_re)
    return bbox


@dataclass(frozen=True)
class Element:
    """One on-screen UI element, normalised across perception tiers."""

    name: str
    control_type: str
    automation_id: str
    bbox: tuple[int, int, int, int]
    path: tuple[str, ...] = field(default=())
    #: Which perception tier produced this element. "uia" is a confirmed
    #: control; "ocr" is text read off pixels, which carries no AutomationId,
    #: no control_type, and no structural context. Everything downstream that
    #: decides how much to trust an element keys off THIS, not off which
    #: grounding rung matched it.
    #:
    #: Last field on purpose: existing call sites construct Element
    #: positionally, so an earlier insertion would silently shift them.
    source: str = field(default="uia")


def iter_elements(title_re: str) -> list[Element]:
    """Every on-screen element inside the window matching title_re.

    Off-screen and degenerate elements are filtered out — window chrome
    frequently reports (0, 0, 0, 0), which would otherwise ground a hint into
    the corner of the desktop.
    """
    # Ask the cheap question first. windows_matching is an EnumWindows scan
    # costing ~0.1ms; pywinauto's wait("exists", timeout=3) costs ~50ms when
    # the window IS there and a full 3 seconds when it is not. With three
    # perception calls per tick, an absent target — the user simply alt-tabbed
    # — blocked a tick for ~9.1 seconds, and ESC is only polled between ticks,
    # so the overlay sat on screen un-dismissable for that whole time.
    #
    # No wait() below either: existence is already established here, and the
    # window can still vanish between this check and the walk, which the
    # except clause handles. Waiting cannot close that race, only pay for it.
    if not windows_matching(title_re):
        return []

    try:
        window = Desktop(backend="uia").window(title_re=title_re)
        descendants = window.descendants()
    except Exception:
        # The window went away mid-walk, or exposes no usable UIA tree.
        return []

    elements: list[Element] = []
    for ctrl in descendants:
        try:
            rect = ctrl.rectangle()
            bbox = (rect.left, rect.top, rect.right, rect.bottom)
            if not is_on_screen(bbox):
                continue
            info = ctrl.element_info
            elements.append(
                Element(
                    name=ctrl.window_text() or "",
                    control_type=info.control_type or "",
                    automation_id=info.automation_id or "",
                    bbox=bbox,
                    path=(info.control_type or "",),
                )
            )
        except Exception:
            continue  # elements can vanish mid-enumeration
    return elements


def _vscode_open_folder_element_info(hwnd: int):
    """Find a directly exposed Welcome-page Open Folder action, if present."""
    from pywinauto.uia_defines import IUIA
    from pywinauto.uia_element_info import UIAElementInfo

    uia = IUIA()
    root = UIAElementInfo(hwnd)
    for name in ("Open Folder...", "Open Folder…", "Open Folder"):
        condition = uia.build_condition(title=name)
        raw = root.element.FindFirst(uia.tree_scope["descendants"], condition)
        if raw is not None:
            return UIAElementInfo(raw)
    return None


def iter_vscode_elements(title_re: str) -> list[Element]:
    """Minimal UIA perception for the trusted VS Code open-folder workflow.

    This intentionally returns only the Open Folder Welcome action. It avoids the
    unbounded full-tree walk that stalls on real VS Code windows.  If the
    provider cannot expose Open Folder, returning an empty successful observation
    lets the existing OCR tier attempt the same trusted target.
    """
    matches = windows_matching_executable(title_re, "code.exe")
    if not matches:
        return []
    try:
        info = _vscode_open_folder_element_info(matches[0])
        if info is None:
            return []
        rect = info.rectangle
        bbox = (rect.left, rect.top, rect.right, rect.bottom)
        if not is_on_screen(bbox):
            return []
        return [
            Element(
                name=info.name or "",
                control_type=info.control_type or "",
                automation_id=info.automation_id or "",
                bbox=bbox,
                path=(info.control_type or "",),
            )
        ]
    except Exception:
        return []


_VSCODE_TERMINAL_BUTTONS = {
    "Toggle Panel (Ctrl+J)",
    "Terminal Section",
}


def iter_vscode_terminal_elements(title_re: str) -> list[Element]:
    """Trusted UIA surface for the VS Code integrated-terminal workflow.

    Electron exposes the title-bar Toggle Panel control and the visible
    terminal section as Buttons, but neither has a stable AutomationId. Walk
    only Buttons and publish only these two hand-approved exact names. The
    walk remains on the bounded perception worker; a slow Electron provider
    therefore cannot freeze ESC or the control rail.
    """

    matches = windows_matching_executable(title_re, "code.exe")
    if not matches:
        return []
    try:
        window = Desktop(backend="uia").window(handle=matches[0])
        controls = window.descendants(control_type="Button")
    except Exception:
        return []

    elements: list[Element] = []
    for control in controls:
        try:
            name = control.window_text() or ""
            if name not in _VSCODE_TERMINAL_BUTTONS:
                continue
            rect = control.rectangle()
            bbox = (rect.left, rect.top, rect.right, rect.bottom)
            if not is_on_screen(bbox):
                continue
            info = control.element_info
            elements.append(
                Element(
                    name=name,
                    control_type=info.control_type or "",
                    automation_id=info.automation_id or "",
                    bbox=bbox,
                    path=(info.control_type or "",),
                )
            )
        except Exception:
            continue
    return elements
