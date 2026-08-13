"""Tier 1 perception: Windows UI Automation via pywinauto.

Reference: D:\\tracker\\docs\\ghostcursor\\python-uiautomation-for-windows-uiautomation.docx,
D:\\tracker\\docs\\ghostcursor\\pywinauto-windows-gui-automation-with-python.docx
"""

import re
from dataclasses import dataclass, field

import win32gui
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


def _raw_window_rect(title_re: str) -> tuple[int, int, int, int] | None:
    """Fallback: raw win32gui geometry for a visible, non-minimized top-level
    window matching title_re, for the cases where UIA exposes no usable
    geometry at all."""
    pattern = re.compile(title_re)
    matches: list[tuple[int, int, int, int]] = []

    def _collect(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return
        if pattern.search(win32gui.GetWindowText(hwnd)):
            rect = win32gui.GetWindowRect(hwnd)
            if is_on_screen(rect):
                matches.append(rect)

    win32gui.EnumWindows(_collect, None)
    return matches[0] if matches else None


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


def iter_elements(title_re: str) -> list[Element]:
    """Every on-screen element inside the window matching title_re.

    Off-screen and degenerate elements are filtered out — window chrome
    frequently reports (0, 0, 0, 0), which would otherwise ground a hint into
    the corner of the desktop.
    """
    try:
        window = Desktop(backend="uia").window(title_re=title_re)
        window.wait("exists", timeout=3)
        descendants = window.descendants()
    except Exception:
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
