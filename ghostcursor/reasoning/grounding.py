"""Turn a step's description of a target into a live screen rectangle.

Cheapest and most stable matcher first, mirroring the perception ladder
(DECISIONS.md D005). See spec §5.

    rung 1  confirmed automation_id   survives renames AND translation
    rung 2  control_type + exact name
    rung 3  fuzzy name / synonyms

Rungs 2-3 match on displayed text and are therefore locale-scoped. Rung 1 is
language-independent by construction and must never be filtered by locale —
doing so would defeat the promotion mechanism it exists to enable.

Scope note for this milestone: `locale` is threaded through but does not
filter live matching, and that is correct rather than incomplete. The live UI
renders in whatever language the app is running in, so rungs 2-3 match the
text actually on screen — there is nothing to filter against. Locale becomes
load-bearing when *selecting between stored observations and recipe variants*,
which is knowledge-base territory (spec sections 8-10) and deliberately out of
scope here. The parameter exists now so that `promote()` records which locale
an observation came from, which is the data that later selection will need.
"""

from __future__ import annotations

from dataclasses import dataclass

from ghostcursor.perception.uia import Element, iter_elements
from ghostcursor.reasoning.schema import Step

RUNG_AUTOMATION_ID = 1
RUNG_TYPE_AND_NAME = 2
RUNG_FUZZY_NAME = 3


@dataclass(frozen=True)
class GroundedTarget:
    bbox: tuple[int, int, int, int]
    rung: int
    automation_id: str
    control_type: str
    name: str


def _as_target(element: Element, rung: int) -> GroundedTarget:
    return GroundedTarget(
        bbox=element.bbox,
        rung=rung,
        automation_id=element.automation_id,
        control_type=element.control_type,
        name=element.name,
    )


def _disambiguate(matches: list[Element], step: Step) -> Element:
    """Pick between equally-good matches using the path hint.

    The hint is a tie-breaker only — never identity — because a tree path
    breaks whenever layout changes.
    """
    if len(matches) == 1:
        return matches[0]
    hints = {
        segment
        for obs in step.target_descriptor.confirmed
        for segment in obs.accessibility_path_hint
    }
    if hints:
        for element in matches:
            if hints & set(element.path):
                return element
    return matches[0]


def ground(
    step: Step,
    title_re: str,
    locale: str = "en-US",
    elements: list[Element] | None = None,
) -> GroundedTarget | None:
    """Resolve step's target to a live rectangle, or None if not found."""
    if elements is None:
        elements = iter_elements(title_re)
    if not elements:
        return None

    claimed = step.target_descriptor.claimed

    # Rung 1 — confirmed AutomationId. Locale-independent on purpose.
    known_ids = {
        obs.automation_id
        for obs in step.target_descriptor.confirmed
        if obs.automation_id
    }
    if known_ids:
        matches = [e for e in elements if e.automation_id in known_ids]
        if matches:
            return _as_target(_disambiguate(matches, step), RUNG_AUTOMATION_ID)

    # Rung 2 — control type plus exact displayed name.
    wanted_type = next(
        (
            obs.control_type
            for obs in step.target_descriptor.confirmed
            if obs.control_type
        ),
        None,
    )
    if claimed.name:
        # First try: exact name with type constraint (if available).
        matches = [
            e
            for e in elements
            if e.name == claimed.name
            and (wanted_type is None or e.control_type == wanted_type)
        ]
        if matches:
            return _as_target(_disambiguate(matches, step), RUNG_TYPE_AND_NAME)

        # Fallback: exact name without type constraint if type was stale.
        # The displayed name is stronger evidence than a remembered type hint.
        if wanted_type:
            matches = [e for e in elements if e.name == claimed.name]
            if matches:
                return _as_target(_disambiguate(matches, step), RUNG_TYPE_AND_NAME)

    # Rung 3 — synonyms and case-insensitive substring.
    candidates = [claimed.name, *claimed.name_synonyms]
    for candidate in filter(None, candidates):
        needle = candidate.casefold()
        matches = [e for e in elements if e.name and needle in e.name.casefold()]
        if matches:
            return _as_target(_disambiguate(matches, step), RUNG_FUZZY_NAME)

    return None
