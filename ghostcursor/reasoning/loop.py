"""The observe-act-verify state machine (spec §6).

Not plain ReAct. ReAct's observe step is passive — read a tool result — and
assumes the agent's own action changed the world. Here the *user* acts, and
they can do something entirely different from what was suggested, so
VERIFYING is an active re-perception against a predicted post-condition, and a
failed verification re-plans from real state rather than retrying blindly.

Collaborators are injected so every transition is testable without a UI.
"""

from __future__ import annotations

import time
from enum import Enum, auto
from typing import Callable, Protocol

from ghostcursor.reasoning.grounding import GroundedTarget
from ghostcursor.reasoning.schema import Recipe, Step, VerificationKind
from ghostcursor.reasoning.verification import Snapshot, elements_changed

#: How long grounding may keep failing continuously (e.g. the target window is
#: minimized or the user alt-tabbed away) before the tour gives up. Spec §11:
#: "Target window missing / minimized / off-desktop -> clear hint, wait" — a
#: momentary absence must not end the run.
DEFAULT_GROUNDING_GRACE_S = 10.0


def _is_newer(after: Snapshot, before: Snapshot | None) -> bool:
    """Whether `after` describes a genuinely later moment than `before`.

    An untimestamped snapshot (0.0) is treated as fresh: that is what a
    synchronous or faked perception is, and gating those would break every
    existing collaborator fake.
    """
    if before is None or after.observed_at == 0.0 or before.observed_at == 0.0:
        return True
    return after.observed_at > before.observed_at


class State(Enum):
    IDLE = auto()
    OBSERVING = auto()
    DECIDING = auto()
    RENDERING_HINT = auto()
    AWAITING_USER_ACTION = auto()
    VERIFYING = auto()
    DONE = auto()
    FAILED = auto()


class Renderer(Protocol):
    def show(self, grounded: GroundedTarget, instruction_text: str) -> None: ...
    def clear(self) -> None: ...

    def settle(self) -> None:
        """Close the tick: emit the display state if nothing else did.

        The loop owns the tick boundary by definition — it is the thing that
        ticks — so it is the only place that can guarantee the renderer is
        told where one ends. It learns nothing about staleness by calling
        this: what to draw stays entirely behind the renderer's own
        `freshness_source` (D027).
        """
        ...


class GuidedTour:
    def __init__(
        self,
        recipe: Recipe,
        grounder: Callable[[Step, int, list], GroundedTarget | None],
        snapshotter: Callable[[], Snapshot],
        verifier: Callable[..., bool],
        renderer: Renderer,
        clock: Callable[[], float] = time.monotonic,
        idle_timeout_s: float = 30.0,
        grounding_grace_s: float = DEFAULT_GROUNDING_GRACE_S,
        ungroundable_reason: Callable[[Step, int], str | None] | None = None,
        focus_visited_source: Callable[[], tuple[str, ...]] | None = None,
        on_wrong_action: Callable[[str, str], None] | None = None,
    ) -> None:
        self.recipe = recipe
        self.grounder = grounder
        self.snapshotter = snapshotter
        self.verifier = verifier
        self.renderer = renderer
        self.clock = clock
        self.idle_timeout_s = idle_timeout_s
        self.grounding_grace_s = grounding_grace_s
        #: Optional: asked, when the grace expires, for a reason better than
        #: "cannot find X on screen". The loop knows only that grounding kept
        #: failing; the driver may know WHY — that a perception tier was
        #: engaged and could not read the screen, say — and the difference
        #: decides whether the user is pointed at their own application or at
        #: ours (D024). It stays a callable so the loop learns nothing about
        #: perception tiers, exactly as with `freshness_source` (D027).
        self.ungroundable_reason = ungroundable_reason
        self.focus_visited_source = focus_visited_source
        self.on_wrong_action = on_wrong_action
        #: Wrong-action re-hints spent on the CURRENT step. Separate from
        #: rehint_count, which counts idle nudges: idle means the user is
        #: doing nothing and a second nudge is nagging, while a wrong action
        #: means they are actively trying and answering each attempt is help.
        self.wrong_action_rehints = 0

        self.state = State.IDLE
        self.step_index = 0
        self.rehint_count = 0
        self.failure_reason: str | None = None

        self._before: Snapshot | None = None
        self._grounded: GroundedTarget | None = None
        self._waiting_since = 0.0
        self._confirmed = False
        #: Wall-clock time grounding started failing continuously for the
        #: current step, or None while it is succeeding. Cleared the instant
        #: grounding succeeds again.
        self._grounding_fail_since: float | None = None
        #: Which step the idle clock belongs to. Re-rendering the same step
        #: after a re-observe must NOT restart it, or the timeout can never
        #: elapse during a normal poll cycle.
        self._hint_step_index: int | None = None

    @property
    def current_step(self) -> Step | None:
        if self.step_index >= len(self.recipe.steps):
            return None
        return self.recipe.steps[self.step_index]

    def confirm(self) -> None:
        """The user pressed the confirm key for a user_confirms step."""
        self._confirmed = True

    def tick(self) -> State:
        """Advance one tick, then close it.

        `settle()` is called here rather than by the driver so that a driver
        CANNOT forget it. Forgetting was silent: the hint stays exactly as it
        was drawn, never dimming and never hiding, while perception hums along
        and nothing errors (D027). Every driver ticks, by definition, so this
        covers all of them — including ones that wire a different
        `freshness_source`, or no staleness ladder at all, which the ladder's
        own unqueried detector cannot see.

        It runs on EVERY path, the DONE and FAILED ticks included. That is
        deliberate and costs nothing: both terminal paths call
        `renderer.clear()` first, which marks the tick written, so `settle()`
        emits nothing. "Every tick settles" is a simpler invariant to hold
        than "every tick except the last two", and simpler invariants survive
        the next edit.
        """
        state = self._advance()
        self.renderer.settle()
        return state

    def _advance(self) -> State:
        if self.state in (State.DONE, State.FAILED):
            return self.state

        if self.state is State.IDLE:
            self.state = State.OBSERVING

        elif self.state is State.OBSERVING:
            if self.current_step is None:
                self.renderer.clear()
                self.state = State.DONE
            else:
                self._before = self.snapshotter()
                self.state = State.DECIDING

        elif self.state is State.DECIDING:
            step = self.current_step
            # Reuse the elements OBSERVING just read rather than walking the
            # UI tree again. OBSERVING and DECIDING are meant to describe the
            # SAME instant — "here is the screen, now decide what to point at"
            # — so a second walk was both slower and slightly wrong, since the
            # screen could change between them.
            #
            # AWAITING_USER_ACTION deliberately does NOT share this: its whole
            # job is to observe a LATER moment and see whether the user acted.
            # Sharing a snapshot there would compare a state against itself.
            self._grounded = self.grounder(step, self.step_index, self._before.elements)
            if self._grounded is None:
                # Never guess a coordinate. The target window may simply be
                # minimized or the user alt-tabbed away (spec §11: "Target
                # window missing / minimized / off-desktop -> clear hint,
                # wait"), so clear the hint and keep re-observing rather than
                # failing immediately. Only give up once grounding has failed
                # CONTINUOUSLY past the grace period.
                self.renderer.clear()
                now = self.clock()
                if self._grounding_fail_since is None:
                    self._grounding_fail_since = now
                if now - self._grounding_fail_since >= self.grounding_grace_s:
                    reason = (
                        self.ungroundable_reason(step, self.step_index)
                        if self.ungroundable_reason is not None
                        else None
                    )
                    self.failure_reason = reason or (
                        f"cannot find {step.target_descriptor.claimed.name!r} on screen"
                    )
                    self.state = State.FAILED
                else:
                    self.state = State.OBSERVING
            else:
                self._grounding_fail_since = None
                self.state = State.RENDERING_HINT

        elif self.state is State.RENDERING_HINT:
            step = self.current_step
            self.renderer.show(self._grounded, step.instruction_text)
            if self._hint_step_index != self.step_index:
                # Genuinely a new step: start its idle clock.
                self._waiting_since = self.clock()
                self.rehint_count = 0
                self._confirmed = False
                self._hint_step_index = self.step_index
            self.state = State.AWAITING_USER_ACTION

        elif self.state is State.AWAITING_USER_ACTION:
            # A dwelling state, not a pass-through. The user acts on their own
            # schedule, so this polls and stays put until something happens.
            step = self.current_step
            after = self.snapshotter()

            # A slot that has not advanced is NO verification attempt, not a
            # failed one. Verifying against the same observation OBSERVING
            # used would compare a state against itself, so the rule would
            # never fire and the tour would stall on this step forever.
            if not _is_newer(after, self._before):
                return self.state

            if step.verification_rule.kind is VerificationKind.USER_CONFIRMS:
                satisfied = self._confirmed
            else:
                satisfied = self.verifier(step.verification_rule, self._before, after)

            # Bound once, like `after` above: `focus_visited_source` reads
            # `current_observation`, not a fresh `service.latest()` call (see
            # its docstring in run.py), so within one tick it is stable -- but
            # the bind-once discipline still matters, because `_wrong_action`
            # walks that same tuple and calling it twice would do the walk
            # twice for no reason. One evaluation per tick keeps the condition
            # that gates `on_wrong_action` and the message it prints from ever
            # disagreeing with each other.
            touched = self._wrong_action()

            # The message is bounded by real user actions, not by a clock, so
            # it is deliberately uncapped: capping it would tell a user who
            # keeps trying and failing LESS the harder they struggle. It is
            # hoisted above the elif chain below so that a CAPPED tick still
            # falls through to the elements_changed and idle-timeout arms --
            # short-circuiting on `touched` past the cap stopped the loop
            # re-grounding at all, so a wrong click that moved the target
            # went unnoticed and the idle re-hint never fired either.
            if (
                touched is not None
                and not satisfied
                and self.on_wrong_action is not None
            ):
                self.on_wrong_action(touched, self._target_automation_id())

            if satisfied:
                self.state = State.VERIFYING
            elif touched is not None and self.wrong_action_rehints < 3:
                # Re-hint by going back through OBSERVING, NOT by calling
                # renderer.show() here. A second overlay write path is what
                # D027 exists to prevent: set_hint ends in UpdateWindow, which
                # paints synchronously, so an extra frame definitely reaches
                # the screen. OBSERVING also re-grounds, which is right on its
                # own terms -- a wrong click may have opened a dialog and
                # moved the target.
                self.wrong_action_rehints += 1
                self.state = State.OBSERVING
            elif elements_changed(self._before, after):
                # The world changed, but not into what we predicted — the user
                # did something else. Re-observe and re-ground: the target may
                # have moved or be gone. AndroidWorld-style interrupt handling.
                #
                # Compares element IDENTITY, not the whole Snapshot. Snapshot
                # equality includes `title`, which ticks on ordinary window
                # churn (alt-tab, a retitled window) with no element ever
                # moving. Reacting to that would send the loop to OBSERVING,
                # which unconditionally re-baselines `_before` — if the
                # user's real action lands in the same tick as the churn, it
                # gets folded into the new baseline and can never be detected
                # again, permanently stalling a step already completed.
                self.state = State.OBSERVING
            elif self.clock() - self._waiting_since >= self.idle_timeout_s:
                # Clippy lesson: re-hint once, then go quiet. Never nag.
                if self.rehint_count == 0:
                    self.renderer.show(self._grounded, step.instruction_text)
                    self.rehint_count += 1
                self._waiting_since = self.clock()
            # else: keep waiting, and let the idle clock keep accumulating.

        elif self.state is State.VERIFYING:
            # Commit: the predicted post-condition held.
            self.step_index += 1
            self.renderer.clear()
            self._confirmed = False
            self.wrong_action_rehints = 0
            self.state = State.OBSERVING

        return self.state

    def _target_automation_id(self) -> str:
        grounded = self._grounded
        return getattr(grounded, "automation_id", "") if grounded else ""

    def _wrong_action(self) -> str | None:
        """The first in-app control focus touched that is not the target.

        None when there is nothing to report. Silent by construction in every
        case the design names: no source wired, nothing visited, or a target
        with no AutomationId of its own -- which is what an OCR-grounded
        target is, since OCR elements carry no id. Comparing against "" there
        would report a wrong action on every focus change.
        """
        if self.focus_visited_source is None:
            return None
        target_id = self._target_automation_id()
        if not target_id:
            return None
        for touched in self.focus_visited_source():
            if touched and touched != target_id:
                return touched
        return None
