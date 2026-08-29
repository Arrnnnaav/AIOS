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
from dataclasses import dataclass, field
from enum import Enum
from types import SimpleNamespace
from typing import Callable, Mapping, Sequence

from ghostcursor.perception.health import PerceptionUnhealthy
from ghostcursor.perception.uia import Element, ProviderQueryFault
from ghostcursor.reasoning import grounding
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
    #: Seconds from the start of the run to each landmark, for the marks that
    #: happened. A record naming only the outcome cannot tell a user who was
    #: slower than a 20s budget from a world that never changed, and those two
    #: findings call for opposite responses -- one is operator pacing, the
    #: other is a broken workflow. Absent keys mean the mark never occurred,
    #: which is itself the answer in several failure shapes.
    timing: Mapping[str, float] = field(default_factory=dict)

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
    focus_visited: tuple[str, ...] = ()


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
        claimed = step.claimed
        claimed_name = claimed.get("name") or _claimed_name(workflow, index)
        steps.append(
            Step(
                user_action=UserAction(step.user_action),
                target_descriptor=TargetDescriptor(
                    claimed=ClaimedDescriptor(
                        name=claimed_name,
                        name_synonyms=list(claimed.get("name_synonyms", ())),
                        ocr_text=claimed.get("ocr_text"),
                        visual_description=claimed.get("visual_description"),
                    )
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
    observe: Callable[[], TickInput | None],
    renderer,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    seconds: float = 120.0,
    tick_interval_s: float = 0.25,
    should_abort: Callable[[], bool] | None = None,
    should_pause: Callable[[], bool] | None = None,
    confirmation_requested: Callable[[], bool] | None = None,
    pump: Callable[[], None] | None = None,
    on_grounding: Callable[..., None] | None = None,
    on_promoted: Callable[[int, Step, GroundedTarget], None] | None = None,
    on_step: Callable[[int, int], None] | None = None,
    runtime_steps: Sequence[Step] | None = None,
    app_version: str | None = None,
    ui_locale: str = "unknown",
) -> TourResult:
    """Run one compiled workflow to a terminal state and report what happened.

    **`observe()` READS a published observation; it must never take one.**
    Perception belongs on the worker thread (D021): a "Not Responding" target
    blocks a single UIA walk for 41 seconds measured, and this loop is what
    polls the abort signal and pumps window messages, so a walk performed here
    is 41 seconds in which the user cannot dismiss a window covering their
    whole screen. Returning `None` means nothing has been published yet -- the
    loop waits, keeps pumping, and keeps the deadline live rather than
    blocking on the first read.

    The compiled selector owns the candidate set and cardinality. The existing
    grounding ladder then evaluates only that one declared element so stable
    learned identity and rung semantics survive the cutover. It may accept or
    reject the element, but it cannot substitute a different control; a ladder
    miss returns ``None`` and leaves the step safely ungrounded.

    Every seam is injected, so this runs identically against a live desktop and
    against a scripted screen. A harness that could only run the real thing
    could not be tested, and one that ran a simplified stand-in would certify
    the stand-in.
    """
    steps = (
        list(runtime_steps)
        if runtime_steps is not None
        else compiled_steps(workflow)
    )
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
            #
            # Telling the source is the DECISION half of tier 2 (D035): only
            # this loop knows which step is current and whether grounding just
            # failed, so it is the only thing that can ask for an OCR read.
            # The worker does the reading and publishes the answer later.
            if on_grounding is not None:
                on_grounding(index, False, compiled.target_selector)
            return None
        if on_grounding is not None:
            # Cancel, not merely stop asking. Absence of a request means "not
            # wanted" -- there is no `wanted` flag -- so a success that did not
            # cancel would leave OCR running for a step that no longer needs it.
            on_grounding(index, True, compiled.target_selector)
        grounded = grounding.ground(
            step,
            "",
            locale=ui_locale,
            app_version=app_version,
            elements=list(matched),
        )
        if grounded is None:
            return None
        provenance.record(index, grounded.source)
        if on_promoted is not None:
            on_promoted(index, step, grounded)
        return grounded

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
        """The latest PUBLISHED observation, never a fresh walk.

        Reached only after `_await_observation()` has confirmed one exists, so
        a `None` here would be a slot that emptied mid-tick, which the service
        never does -- it overwrites, and never clears.
        """
        nonlocal _current
        published = observe()
        if published is not None:
            _current = published
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
        focus_visited_source=lambda: (
            _current.focus_visited if _current is not None else ()
        ),
    )

    #: Landmarks, in seconds from the start of the run. Recorded once each:
    #: a mark that keeps moving is a heartbeat, and the question these answer
    #: is WHEN something first happened.
    marks: dict[str, float] = {}
    first_title = [None]

    def _mark(name: str) -> None:
        marks.setdefault(name, clock() - started)

    def _timing() -> dict[str, float]:
        """Snapshot taken at every exit, including the failing ones.

        Especially the failing ones: a timeout that recorded nothing is the
        record that sent this milestone back to guessing about Open Folder.
        """
        out = dict(marks)
        started_at = tour.verification_started_at
        if started_at is not None:
            out.setdefault("verification_started_s", started_at - started)
        out["ended_s"] = clock() - started
        return out

    #: The step index last REPORTED, so progress is announced on change
    #: rather than on every tick. -1 rather than 0 so the first step is
    #: announced too: a run that named no step until the second one would
    #: leave the first looking like no step at all.
    _reported = [-1]

    started = clock()

    def _tend() -> None:
        """Keep the UI thread's obligations current between ticks."""
        if pump is not None:
            pump()

    # Wait for the FIRST published observation before the loop starts. The
    # worker has to complete one walk, and entering the state machine without
    # one would mean building a snapshot that observed no selector at all --
    # which is a fault, not an empty screen.
    while _current is None:
        _tend()
        if should_abort is not None and should_abort():
            return TourResult(
                outcome=RunOutcome.ABORTED,
                provenance=(),
                steps_completed=0,
                steps_total=len(steps),
                detail="aborted before the first observation",
                timing=_timing(),
            )
        if clock() - started >= seconds:
            return TourResult(
                outcome=RunOutcome.TIMED_OUT,
                provenance=(),
                steps_completed=0,
                steps_total=len(steps),
                detail=f"no observation published within {seconds:g}s",
                timing=_timing(),
            )
        try:
            _current = observe()
        except (ProviderQueryFault, PerceptionUnhealthy) as fault:
            return TourResult(
                outcome=RunOutcome.FAILED,
                provenance=(),
                steps_completed=0,
                steps_total=len(steps),
                detail=str(fault),
                timing=_timing(),
            )
        if _current is None:
            sleeper(tick_interval_s)
        else:
            _mark("first_observation_s")
            first_title[0] = _current.title

    while True:
        _tend()
        if should_abort is not None and should_abort():
            return TourResult(
                outcome=RunOutcome.ABORTED,
                provenance=provenance.as_tuple(),
                steps_completed=tour.step_index,
                steps_total=len(steps),
                detail="aborted by the operator",
                timing=_timing(),
            )

        # Pause is an operator instruction, not an empty observation and not a
        # verification result. Keep pumping the focusable control bar and keep
        # the run deadline honest, but do not advance the state machine while
        # paused. Perception may continue publishing in the background; the
        # next unpaused tick takes one coherent latest snapshot as usual.
        if should_pause is not None and should_pause():
            if clock() - started >= seconds:
                return TourResult(
                    outcome=RunOutcome.TIMED_OUT,
                    provenance=provenance.as_tuple(),
                    steps_completed=tour.step_index,
                    steps_total=len(steps),
                    detail=f"no terminal state within {seconds:g}s",
                    timing=_timing(),
                )
            sleeper(tick_interval_s)
            continue

        # Progress is REPORTED to the surface, never asked for by it. A bar
        # that computed its own step number could disagree with the executor
        # about which step is running -- which is the "invents progress"
        # failure the control rail is built to avoid. On change only: a
        # per-tick write would repaint the same string four times a second.
        if tour.step_index != _reported[0]:
            _reported[0] = tour.step_index
            # A finished tour has no current step, so there is no "step 3 of
            # 2" to announce. The terminal index is still recorded above, so
            # nothing re-announces the last step either.
            if on_step is not None and tour.step_index < len(steps):
                on_step(tour.step_index, len(steps))

        if _current is not None and _current.title != first_title[0]:
            # The Open Folder signal specifically: the title is the verified
            # outcome, so when it changed relative to the verification clock
            # is the difference between a slow operator and a dead workflow.
            _mark("title_changed_s")

        _index[0] = tour.step_index
        # Confirmation is an explicit user action, not an observation.  The
        # executor owns the step-kind check so a SPACE typed while any other
        # step is active can never invent progress, even if a caller supplies
        # an over-eager input source.
        current_step = tour.current_step
        if (
            current_step is not None
            and current_step.verification_rule.kind
            is VerificationKind.USER_CONFIRMS
            and confirmation_requested is not None
            and confirmation_requested()
        ):
            tour.confirm()
        try:
            state = tour.tick()
        except (ProviderQueryFault, PerceptionUnhealthy) as fault:
            # A faulted observation is not an empty screen. Ambiguity and an
            # over-limit read must reach the run record as a failure with a
            # reason, never as "the control is not there" -- flattening a
            # fault into absence is the collapse D069 exists to prevent, and a
            # run that ended because of one has to say so.
            return TourResult(
                outcome=RunOutcome.FAILED,
                provenance=provenance.as_tuple(),
                steps_completed=tour.step_index,
                steps_total=len(steps),
                detail=str(fault),
                timing=_timing(),
            )

        if state is State.AWAITING_USER_ACTION:
            # The hint is on screen from here, which is where a
            # `timeout_from_hint` recipe starts counting.
            _mark("first_hint_s")

        if state is State.DONE:
            return TourResult(
                outcome=RunOutcome.PASSED,
                provenance=provenance.as_tuple(),
                steps_completed=len(steps),
                steps_total=len(steps),
                timing=_timing(),
            )
        if state is State.FAILED:
            return TourResult(
                outcome=RunOutcome.FAILED,
                provenance=provenance.as_tuple(),
                steps_completed=tour.step_index,
                steps_total=len(steps),
                detail=getattr(tour, "failure_reason", "") or "",
                timing=_timing(),
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
                timing=_timing(),
            )
        sleeper(tick_interval_s)
