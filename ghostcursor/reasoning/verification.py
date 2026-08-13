"""Decide whether the user actually completed a step.

Verification checks *world state, never the route taken* (spec §7). If the
recipe said "click File > Save" and the user pressed Ctrl+S, they achieved the
goal and verification must pass. Grading the method instead of the outcome
makes the teacher wrong exactly when the student is efficient.

This mirrors OSWorld's execution-based grading: inspect real state, don't
grade a transcript.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ghostcursor.perception.uia import Element, iter_elements
from ghostcursor.reasoning.schema import VerificationKind, VerificationRule


@dataclass(frozen=True)
class Snapshot:
    title: str
    elements: tuple[Element, ...]
    focused_automation_id: str = ""


def take_snapshot(title_re: str) -> Snapshot:
    import win32gui

    elements = tuple(iter_elements(title_re))
    try:
        title = win32gui.GetWindowText(win32gui.GetForegroundWindow())
    except Exception:
        title = ""
    return Snapshot(title=title, elements=elements, focused_automation_id="")


def _matches(element: Element, descriptor: dict) -> bool:
    if "automation_id" in descriptor:
        return element.automation_id == descriptor["automation_id"]
    if "name" in descriptor:
        return element.name == descriptor["name"]
    return False


def _find(snapshot: Snapshot, descriptor: dict) -> Element | None:
    return next((e for e in snapshot.elements if _matches(e, descriptor)), None)


def _identity(snapshot: Snapshot) -> set[tuple[str, str, str]]:
    """Which elements exist, ignoring position — moving a window is not
    progress."""
    return {(e.automation_id, e.name, e.control_type) for e in snapshot.elements}


def verify(rule: VerificationRule, before: Snapshot, after: Snapshot) -> bool:
    kind = rule.kind
    args = rule.args

    if kind is VerificationKind.USER_CONFIRMS:
        # Resolved by a keypress in the loop, never by looking at the screen.
        return False

    if kind is VerificationKind.ELEMENT_APPEARS:
        descriptor = args["target_descriptor"]
        return (
            _find(before, descriptor) is None and _find(after, descriptor) is not None
        )

    if kind is VerificationKind.ELEMENT_DISAPPEARS:
        descriptor = args["target_descriptor"]
        return (
            _find(before, descriptor) is not None and _find(after, descriptor) is None
        )

    if kind is VerificationKind.WINDOW_TITLE_MATCHES:
        return re.search(args["pattern"], after.title) is not None

    if kind is VerificationKind.FOCUS_MOVES_TO:
        wanted = args["target_descriptor"].get("automation_id")
        return (
            after.focused_automation_id == wanted
            and before.focused_automation_id != wanted
        )

    if kind is VerificationKind.PROPERTY_CHANGES:
        descriptor = args["target_descriptor"]
        prop = args["property"]
        old, new = _find(before, descriptor), _find(after, descriptor)
        if old is None or new is None:
            return False
        return getattr(old, prop) != getattr(new, prop)

    if kind is VerificationKind.ANY_MEANINGFUL_CHANGE:
        return _identity(before) != _identity(after)

    return False
