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
from datetime import datetime, timezone

from ghostcursor.perception.appinfo import parse_version
from ghostcursor.perception.uia import Element, iter_elements
from ghostcursor.reasoning.schema import ConfirmedObservation, Step

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


def select_observations(
    confirmed: list[ConfirmedObservation], app_version: str | None
) -> list[tuple[ConfirmedObservation, bool]]:
    """Which stored observations apply to the running app, and which are exact.

    Spec §9's ladder: exact version, else nearest LOWER verified version, else
    unknown/global. Never a newer version — an id learned on 3.0 says nothing
    about what 2.0 displays.

    Strict equality was considered and rejected: AutomationIds survive version
    changes far more often than they break, so requiring an exact match would
    discard every learned id on each patch bump and re-learn from scratch.
    Non-exact reuse is made safe by the cross-check in ground() instead.
    """
    running = parse_version(app_version or "")

    if running is not None:
        exact = [o for o in confirmed if o.app_version == app_version]
        if exact:
            return [(o, True) for o in exact]

        lower = [
            (parse_version(o.app_version), o)
            for o in confirmed
            if parse_version(o.app_version) is not None
            and parse_version(o.app_version) < running
        ]
        if lower:
            nearest = max(v for v, _ in lower)
            return [(o, False) for v, o in lower if v == nearest]

        return [(o, False) for o in confirmed if parse_version(o.app_version) is None]

    # We do not know what is running, so nothing can be an exact match and
    # every observation is subject to the cross-check.
    return [(o, False) for o in confirmed]


def ground(
    step: Step,
    title_re: str,
    locale: str = "en-US",
    elements: list[Element] | None = None,
    app_version: str | None = None,
) -> GroundedTarget | None:
    """Resolve step's target to a live rectangle, or None if not found."""
    if elements is None:
        elements = iter_elements(title_re)
    if not elements:
        return None

    claimed = step.target_descriptor.claimed

    # Rung 1 — confirmed AutomationId. Locale-independent on purpose.
    #
    # Version-scoped (spec §9): observations from a DIFFERENT app version are
    # usable, but only if the live element's control_type still agrees with
    # what was recorded. A stale id whose control has been reassigned would
    # otherwise produce a confident hint on the wrong element — and failing to
    # ground is recoverable, whereas mis-grounding teaches the user something
    # false with no signal that anything went wrong.
    #
    # An observation with no recorded control_type cannot be cross-checked and
    # is allowed through; promote() always records one, so this only affects
    # incomplete legacy rows.
    for observation, is_exact in select_observations(
        step.target_descriptor.confirmed, app_version
    ):
        if not observation.automation_id:
            continue
        matches = [e for e in elements if e.automation_id == observation.automation_id]
        if not is_exact and observation.control_type:
            matches = [e for e in matches if e.control_type == observation.control_type]
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


def promote(
    step: Step,
    grounded: GroundedTarget | None,
    app_version: str,
    locale: str,
) -> bool:
    """Record what grounding just learned, so later runs use rung 1.

    Documentation cannot supply an AutomationId — no tutorial has ever named
    one — so the only way to get it is to observe the real application. This
    is what makes a recipe more robust every time it is used, and what lets a
    recipe confirmed by an English user ground for a Hindi one.

    Returns True when the step was modified.
    """
    if grounded is None or not grounded.automation_id:
        return False

    for observation in step.target_descriptor.confirmed:
        if (
            observation.app_version == app_version
            and observation.automation_id == grounded.automation_id
        ):
            if locale not in observation.locales_observed:
                observation.locales_observed.append(locale)
            observation.last_seen_at = _now()
            return True

    step.target_descriptor.confirmed.append(
        ConfirmedObservation(
            app_version=app_version,
            locales_observed=[locale],
            automation_id=grounded.automation_id,
            control_type=grounded.control_type,
            accessibility_path_hint=[],
            last_seen_at=_now(),
        )
    )
    return True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
