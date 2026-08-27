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

from ghostcursor.perception.uia import (
    Element,
    SelectorAmbiguityFault,
    iter_elements,
)
from ghostcursor.reasoning.schema import VerificationKind, VerificationRule


class MissingSelectorObservation(LookupError):
    """A rule asked a snapshot for a selector that snapshot never observed.

    Raised rather than returned, for the same reason `ProviderQueryFault` is:
    a returned empty result is indistinguishable from a real absence, and a
    verification reading it would conclude the control is gone. This says the
    observation is not trustworthy, which no boolean can say.
    """


@dataclass(frozen=True)
class Snapshot:
    title: str
    elements: tuple[Element, ...]
    focused_automation_id: str = ""
    #: When the worker completed the walk that produced this, from the
    #: service's clock. 0.0 means untimestamped — a synchronous or faked
    #: perception — and is treated as always fresh.
    observed_at: float = 0.0
    #: What each selector of a compiled observation plan matched this tick, as
    #: pairs rather than a mapping: only frozen values of primitives cross the
    #: worker boundary (D021), and a dict is neither frozen nor hashable.
    #: Empty when no plan ran, which is every v1 observation.
    selector_results: tuple[tuple[str, tuple[Element, ...]], ...] = ()

    def matched(self, selector_id: str) -> tuple[Element, ...]:
        """What `selector_id` matched, or a fault when it was never observed.

        Only an explicitly published empty tuple is a clean absence. A selector
        absent from `selector_results` was not observed at all, and answering
        `()` for it would flatten "no observation" into "the control is not
        there" -- the exact collapse D069 exists to prevent, arriving one layer
        later. It passed `element_disappears` for a snapshot that simply
        omitted the selector.

        Reasoning from the tick's own invariant ("a faulted selector never
        reaches a published snapshot") is what made that look safe. That
        invariant is real but it only *correlates* with the property wanted
        here; it does not imply it. A snapshot can lack a selector for reasons
        that have nothing to do with faults -- a plan and a rule that disagree
        about a selector id, a snapshot built by a path that ran no plan -- and
        in every one of those the honest answer is that nothing is known, not
        that nothing is there (D031).
        """
        for observed_id, elements in self.selector_results:
            if observed_id == selector_id:
                return elements
        raise MissingSelectorObservation(
            f"selector {selector_id!r} was never observed; "
            f"this snapshot published {sorted(o for o, _ in self.selector_results)}"
        )


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
    focused_automation_id: str = "",
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
        focused_automation_id=focused_automation_id,
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


_SELECTOR_KINDS = {
    VerificationKind.ELEMENT_APPEARS,
    VerificationKind.ELEMENT_DISAPPEARS,
    VerificationKind.PROPERTY_CHANGES,
}


def _verify_by_selector(
    rule: VerificationRule, before: Snapshot, after: Snapshot
) -> bool:
    """Decide one of the three selector-backed kinds from observed results.

    The selector, not a descriptor, is what a compiled recipe declares, and the
    observation plan already evaluated each selector's cardinality within its
    own tick. What no plan can establish is identity ACROSS ticks: two ticks
    are two independent reads, and nothing links a control in one to a control
    in the other. So the two presence kinds -- which only ask whether any match
    exists -- are answered directly from `matched()`, while `property_changes`
    additionally requires that each side name exactly one control.
    """
    was, now = before.matched(rule.selector), after.matched(rule.selector)

    if rule.kind is VerificationKind.ELEMENT_APPEARS:
        return not was and bool(now)
    if rule.kind is VerificationKind.ELEMENT_DISAPPEARS:
        return bool(was) and not now

    # PROPERTY_CHANGES. A property can only have changed on a control that was
    # observed both before and after; anything else is an appearance or a
    # disappearance, which are different rules.
    if not was or not now:
        return False

    # One control on each side, or the question is unanswerable. Comparing two
    # result SETS can only be positional, and UIA guarantees no traversal
    # order (see `_sort_elements` above, which exists for exactly this
    # reason) -- so two unchanged controls returned in the opposite order read
    # as a change. Sorting would fix that one case and not the real problem:
    # nothing carries backend identity across ticks, so with several matches
    # there is no way to say WHICH control changed, and a rule that cannot
    # attribute a change cannot report one.
    #
    # The schema already requires `exactly_one` for this kind. This guard is
    # not a restatement of it: the schema binds what a trusted recipe may
    # declare, and this binds what the verifier will act on, so a rule reaching
    # here by any other route still fails closed rather than guessing.
    if len(was) > 1 or len(now) > 1:
        raise SelectorAmbiguityFault(
            f"property_changes selector {rule.selector!r} matched "
            f"{len(was)} controls before and {len(now)} after; a property "
            f"change cannot be attributed among several controls"
        )

    prop = rule.args["property"]
    return getattr(was[0], prop) != getattr(now[0], prop)


def _verify_title_completion(
    args: dict,
    before: Snapshot,
    after: Snapshot,
    goal_reference: str | None,
) -> bool:
    """The declarative replacement for the hardcoded VS Code title branch.

    Three conditions, in the order Design section 7 states them. Each is
    load-bearing on its own:

    1. the normalised title must CHANGE. Without this a goal already satisfied
       before the user did anything verifies immediately;
    2. the new title must END WITH one of the rule's declared suffixes. This is
       deliberately not the pack's `title_patterns`, which are broad
       window-DISCOVERY patterns -- `.*Visual Studio Code.*` is satisfied by
       every failed run too, so reusing it would weaken the check to "the
       window is still VS Code";
    3. if the derived reference is specific, the new title must CONTAIN it.

    A nonspecific reference skips condition 3 rather than failing it. That is
    what keeps `open a folder in VS Code` -- which names no folder at all --
    verifiable on conditions 1 and 2, exactly as it is today.
    """
    from ghostcursor.packs.compile import normalise_title_text

    was = normalise_title_text(before.title)
    now = normalise_title_text(after.title)
    if was == now:
        return False
    if not any(now.endswith(suffix) for suffix in args["completion_title_suffixes"]):
        return False
    minimum = args["goal_reference"]["minimum_length"]
    reference = goal_reference or ""
    if len(reference) < minimum:
        return True
    return reference in now


def verify(
    rule: VerificationRule,
    before: Snapshot,
    after: Snapshot,
    *,
    goal_reference: str | None = None,
) -> bool:
    """Decide one verification rule against two observations.

    `goal_reference` is the value a compiled workflow derived from the goal
    ONCE, during planning. It is passed in rather than recomputed here so
    there is exactly one extractor: a second implementation living in the
    verifier could disagree with the one that planned the run, and the
    disagreement would show up only as a workflow that never verifies.
    """
    kind = rule.kind
    args = rule.args

    if rule.selector is not None and kind in _SELECTOR_KINDS:
        return _verify_by_selector(rule, before, after)

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
        if "completion_title_suffixes" in args:
            return _verify_title_completion(args, before, after, goal_reference)
        return re.search(args["pattern"], after.title) is not None

    if kind is VerificationKind.FOCUS_MOVES_TO:
        # MOVES to, not IS at: a step whose target already has focus must not
        # satisfy itself before the user has done anything. "" is never a
        # match -- it means focus could not be named, which is no evidence.
        wanted = args.get("automation_id", "")
        if not wanted:
            return False
        return before.focused_automation_id != wanted and (
            after.focused_automation_id == wanted
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
