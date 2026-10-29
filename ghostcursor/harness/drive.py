"""Drive one surface toward a goal, a control at a time (D185; HeyClicky's
`drive_until` fast lane). Jev picks the next control from what is observed,
the engine validates the pick against the controls it offered, refuses the
deny list, acts, and looks again -- no model turn per click.

This increases autonomy over plan-approval Act (D182): there is no pre-
reviewed plan. So the loop REFUSES unless the caller passes ``approved=True``
(the person approved starting it), never touches a deny-listed control, stops
the moment ``stop()`` is true (ESC), and is bounded by ``max_steps``. It
returns a typed Result, never a guess; code decides what to do next.

The engine is injectable (observe/choose/act are callables), so the same loop
drives Orbyn's own browser page (D184) and, later, the desktop harness.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CONFIDENCE_FLOOR = 0.6  # below this Jev is guessing; hand back (matches teach.gate)
MARGIN = 0.2  # the top two must be at least this far apart


@dataclass(frozen=True)
class Result:
    #: done | handed_back | blocked | max_steps | not_approved | stopped
    status: str
    reason: str = ""
    steps: int = 0
    history: tuple[str, ...] = field(default_factory=tuple)


def drive_until(
    goal: str,
    *,
    observe,
    choose,
    act,
    approved: bool = False,
    deny=(),
    max_steps: int = 8,
    stop=lambda: False,
) -> Result:
    """Act toward ``goal`` on one surface until it is reached, blocked, or the
    step cap is hit.

    - ``observe()`` -> a list of controls, each with ``.name`` and an id the
      engine passes back to ``act``. An empty list ends the loop (blocked).
    - ``choose(goal, controls)`` -> a ``Choice`` over the controls' ids (plus
      ABSTAIN and a DONE sentinel the caller includes), with probabilities.
    - ``act(control)`` performs the chosen control's action; it raises to abort.
    - ``deny`` names controls never to act on (case-insensitive substrings).
    """


    if not approved:
        return Result("not_approved", "the person has not approved this loop")
    deny = tuple(d.casefold() for d in deny if d)
    history: list[str] = []
    for step in range(1, max_steps + 1):
        if stop():
            return Result("stopped", "ESC", step - 1, tuple(history))
        controls = list(observe())
        if not controls:
            return Result("blocked", "nothing to act on", step - 1, tuple(history))
        by_id = {c.id: c for c in controls}
        choice = choose(goal, controls)
        if choice.choice == "DONE":
            return Result("done", "", step - 1, tuple(history))
        if choice.abstained or choice.choice not in by_id:
            return Result(
                "handed_back", "no clear next control", step - 1, tuple(history)
            )
        top, second = choice.top_two()
        if top < CONFIDENCE_FLOOR or top - second < MARGIN:
            return Result("handed_back", "low confidence", step - 1, tuple(history))
        control = by_id[choice.choice]
        name = (control.name or "").casefold()
        if any(d in name for d in deny):
            return Result(
                "blocked",
                f"{control.name!r} is on the deny list",
                step - 1,
                tuple(history),
            )
        try:
            act(control)
        except Exception as exc:
            if getattr(exc, "retry", False):  # the user is holding a key: look again
                continue
            return Result("blocked", f"could not act: {exc}", step - 1, tuple(history))
        history.append(control.name or control.id)
    return Result("max_steps", "reached the step cap", max_steps, tuple(history))
