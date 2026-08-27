"""Execute a `CompiledWorkflow` through the production tour loop.

The executable half of the schema-v2 path. It exists now rather than at the
cutover because acceptance has to run a workflow before that workflow gains any
authority (D070), and a harness that only *compiles* a candidate certifies
nothing about running it. Building it later would have meant either accepting
workflows nobody ran or writing a second executor for acceptance -- and a
second executor certifies semantics production does not have.

**Implemented here, exposed nowhere.** Nothing in production planning, the
argument parser, or Ask reaches this module today; `run_tour_for_workflow()`
does, and the candidate harness does. The cutover switches which authority path
leads here, not what happens once it does.

The loop itself is `reasoning.loop.GuidedTour`, unchanged. That is the point:
the compiled path differs in where its steps and its observations come from,
not in how observe-act-verify behaves.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from types import SimpleNamespace
from typing import Callable, Sequence

from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.grounding import GroundedTarget
from ghostcursor.reasoning.loop import GuidedTour, State
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor,
    Risk,
    Step,
    TargetDescriptor,
    UserAction,
    VerificationKind,
    VerificationRule,
)
from ghostcursor.reasoning.verification import Snapshot, verify


class RunOutcome(str, Enum):
    """How one compiled run ended. Closed, because evidence cites it.

    An open string here would let a record say anything -- "passed", "mostly
    passed", "passed (manual)" -- and acceptance evidence would then be
    comparing values nothing defines.
    """

    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ABORTED = "aborted"


class GroundingProvenance(str, Enum):
    """Which perception tier actually produced a step's rectangle.

    The values match `Element.source`, so this is a narrowing of what
    perception already reports rather than a second vocabulary. Closed for the
    same reason as `RunOutcome`, and load-bearing for a different one: fallback
    OCR preserves the OUTCOME while the preferred tier is dark, so a record
    naming only the outcome cannot see a tier going dark (D069).
    """

    UIA = "uia"
    OCR = "ocr"


@dataclass(frozen=True)
class TourResult:
    """What actually happened, as the only thing a run record may be built from.

    Returned by the executor rather than described by its caller. A record
    assembled from caller-supplied strings can claim a pass that never
    happened, which makes it useless as acceptance evidence no matter how
    carefully the rest of the harness is bounded.
    """

    outcome: RunOutcome
    provenance: tuple[GroundingProvenance, ...]
    steps_completed: int
    steps_total: int
    detail: str = ""

    @property
    def grounded_by_uia_only(self) -> bool:
        """Whether every step this run grounded came from tier 1.

        Open Folder's acceptance gate turns on this and not on `outcome`.
        """
        return bool(self.provenance) and set(self.provenance) == {
            GroundingProvenance.UIA
        }


@dataclass(frozen=True)
class TickInput:
    """One observation, as the executor consumes it."""

    title: str
    selectors: dict[str, tuple[Element, ...]]
    union: tuple[Element, ...]
    focused_automation_id: str = ""


def compiled_steps(workflow) -> list[Step]:
    """Adapt compiled steps to the shape the tour loop already consumes.

    `Step` is the loop's interface, not v1 authority -- `GuidedTour` reads
    nothing from a recipe but `.steps`. Adapting here is what lets the compiled
    path reuse observe-act-verify exactly rather than reimplementing it beside
    it.
    """
    steps: list[Step] = []
    for index, step in enumerate(workflow.recipe.steps):
        rule = step.verification
        steps.append(
            Step(
                user_action=UserAction(step.user_action),
                target_descriptor=TargetDescriptor(
                    claimed=ClaimedDescriptor(name=_claimed_name(workflow, index))
                ),
                instruction_text=step.instruction_text,
                verification_rule=VerificationRule(
                    kind=VerificationKind(rule.kind),
                    args=dict(rule.args),
                    timeout_s=rule.timeout_s,
                    selector=rule.selector_id,
                ),
                risk=Risk(step.risk),
            )
        )
    return steps


def _claimed_name(workflow, index: int) -> str:
    """A human-readable name for failure text, taken from the selector.

    Only ever used in messages. Grounding uses the selector's observed results,
    never this string -- a name that decided grounding would be a second
    matching rule living beside the declared one.
    """
    step = workflow.recipe.steps[index]
    if step.target_selector is None:
        return ""
    selector = workflow.recipe.plan.selectors.get(step.target_selector)
    return selector.names[0] if selector and selector.names else step.target_selector


def _snapshot(tick: TickInput) -> Snapshot:
    return Snapshot(
        title=tick.title,
        elements=tuple(tick.union),
        focused_automation_id=tick.focused_automation_id,
        selector_results=tuple(tick.selectors.items()),
    )


class _ProvenanceLog:
    """Records which tier grounded each step, in step order, once each.

    Per step rather than per tick: a step re-hinted forty times is one piece of
    evidence about which tier can see that control, not forty.
    """

    def __init__(self) -> None:
        self._by_step: dict[int, GroundingProvenance] = {}

    def record(self, step_index: int, source: str) -> None:
        try:
            self._by_step.setdefault(step_index, GroundingProvenance(source))
        except ValueError:
            # An unknown tier is not silently folded into a known one. Tier 3
            # does not exist yet; when it does, this refuses rather than
            # reporting its rectangles as UIA-confirmed.
            raise ValueError(f"unknown grounding provenance {source!r}") from None

    def as_tuple(self) -> tuple[GroundingProvenance, ...]:
        return tuple(self._by_step[key] for key in sorted(self._by_step))


def execute_compiled_workflow(
    workflow,
    *,
    observe: Callable[[], TickInput],
    renderer,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    seconds: float = 120.0,
    tick_interval_s: float = 0.25,
    should_abort: Callable[[], bool] | None = None,
) -> TourResult:
    """Run one compiled workflow to a terminal state and report what happened.

    Every seam is injected, so this runs identically against a live desktop and
    against a scripted screen. That is what makes acceptance able to exercise
    the real executor: a harness that could only run the real thing could not
    be tested, and one that ran a simplified stand-in would certify the
    stand-in.

    Grounding is the compiled plan's own answer. A step's target selector
    already declared `exactly_one` and the observation already enforced it, so
    there is nothing left to choose here -- and choosing would mean a second
    matching rule beside the declared one.
    """
    steps = compiled_steps(workflow)
    provenance = _ProvenanceLog()

    def grounder(step: Step, index: int, elements: Sequence[Element]):
        compiled = workflow.recipe.steps[index]
        if compiled.target_selector is None:
            return None
        if _current is None:  # pragma: no cover - OBSERVING always precedes this
            return None
        matched = _current.selectors.get(compiled.target_selector, ())
        if len(matched) != 1:
            # Zero is a clean absence and the loop keeps re-observing. More
            # than one cannot reach here: the observation would have faulted.
            return None
        element = matched[0]
        provenance.record(index, element.source)
        return GroundedTarget(
            bbox=element.bbox,
            rung=1,
            automation_id=element.automation_id,
            control_type=element.control_type,
            name=element.name,
            source=element.source,
        )

    def verifier(rule, before, after):
        return verify(
            rule, before, after, goal_reference=workflow.goal_reference_for(_index[0])
        )

    # No eager observation here. The loop always runs OBSERVING before
    # DECIDING, so `snapshotter()` has always filled this before `grounder`
    # reads it -- and an extra read at setup would observe a moment the tour
    # never acted on, shifting every later observation one tick out of step
    # with the state machine that asked for it.
    _current: TickInput | None = None
    _index = [0]

    def snapshotter() -> Snapshot:
        nonlocal _current
        _current = observe()
        _index[0] = tour.step_index
        return _snapshot(_current)

    # The loop reads nothing from a recipe but `.steps`, so this is the whole
    # interface. A class body cannot close over a function local, which is why
    # this is a namespace rather than the obvious inline class.
    compiled = SimpleNamespace(steps=tuple(steps))

    tour = GuidedTour(
        recipe=compiled,
        grounder=grounder,
        snapshotter=snapshotter,
        verifier=verifier,
        renderer=renderer,
        clock=clock,
    )

    started = clock()
    while True:
        if should_abort is not None and should_abort():
            return TourResult(
                outcome=RunOutcome.ABORTED,
                provenance=provenance.as_tuple(),
                steps_completed=tour.step_index,
                steps_total=len(steps),
                detail="aborted by the operator",
            )

        _index[0] = tour.step_index
        state = tour.tick()

        if state is State.DONE:
            return TourResult(
                outcome=RunOutcome.PASSED,
                provenance=provenance.as_tuple(),
                steps_completed=len(steps),
                steps_total=len(steps),
            )
        if state is State.FAILED:
            return TourResult(
                outcome=RunOutcome.FAILED,
                provenance=provenance.as_tuple(),
                steps_completed=tour.step_index,
                steps_total=len(steps),
                detail=getattr(tour, "failure_reason", "") or "",
            )

        if clock() - started >= seconds:
            # A timeout is its own outcome, never a failure. "The user did not
            # finish in two minutes" and "the workflow cannot work" are
            # different findings, and an acceptance record that conflated them
            # would report a working workflow as broken.
            return TourResult(
                outcome=RunOutcome.TIMED_OUT,
                provenance=provenance.as_tuple(),
                steps_completed=tour.step_index,
                steps_total=len(steps),
                detail=f"no terminal state within {seconds:g}s",
            )
        sleeper(tick_interval_s)
