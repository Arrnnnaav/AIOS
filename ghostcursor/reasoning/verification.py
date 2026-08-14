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
    #: When the worker completed the walk that produced this, from the
    #: service's clock. 0.0 means untimestamped — a synchronous or faked
    #: perception — and is treated as always fresh.
    observed_at: float = 0.0


def _sort_elements(
    elements: list[Element] | tuple[Element, ...],
) -> tuple[Element, ...]:
    """Sort elements by a stable key to ensure order-independent comparisons.

    UIA tree walks have no ordering guarantee. Sorting by (automation_id,
    control_type, name, bbox) ensures two Snapshots with the same elements
    compare equal even if UIA returns them in different orders.
    """
    return tuple(
        sorted(
            elements,
            key=lambda e: (e.automation_id, e.control_type, e.name, e.bbox),
        )
    )


def take_snapshot(
    title_re: str,
    elements: list[Element] | tuple[Element, ...] | None = None,
    observed_at: float = 0.0,
) -> Snapshot:
    import win32gui

    if elements is None:
        elements = iter_elements(title_re)
    try:
        title = win32gui.GetWindowText(win32gui.GetForegroundWindow())
    except Exception:
        title = ""
    return Snapshot(
        title=title,
        elements=_sort_elements(elements),
        focused_automation_id="",
        observed_at=observed_at,
    )


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


def elements_changed(before: Snapshot, after: Snapshot) -> bool:
    """Did the set of elements change, ignoring window title and position?

    Used by the loop's "world changed unexpectedly" branch. Comparing whole
    Snapshots there is wrong: `title` ticks on ordinary window-manager churn
    (alt-tab, a retitled window) with no element ever moving, which would
    send the loop back to OBSERVING and unconditionally re-baseline
    `_before` — silently swallowing a user action that lands in the same
    tick. Identity, not the whole snapshot, is what "the world changed"
    should mean here.
    """
    return _identity(before) != _identity(after)


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
        # take_snapshot() hardcodes focused_automation_id="" — focus tracking
        # is not implemented, so both sides of this comparison always
        # mismatch and the rule would silently return False forever, never
        # advancing the tour and never saying why. The codebase's own rule
        # for unimplemented behaviour (see the raise below for unhandled
        # kinds) is to fail loudly instead.
        raise NotImplementedError(
            "focus_moves_to verification is not implemented: "
            "take_snapshot() does not populate focused_automation_id"
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

    raise ValueError(f"unhandled verification kind: {kind}")
