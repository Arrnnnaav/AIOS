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
    ) -> None:
        self.recipe = recipe
        self.grounder = grounder
        self.snapshotter = snapshotter
        self.verifier = verifier
        self.renderer = renderer
        self.clock = clock
        self.idle_timeout_s = idle_timeout_s
        self.grounding_grace_s = grounding_grace_s

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
                    self.failure_reason = (
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

            if satisfied:
                self.state = State.VERIFYING
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
            self.state = State.OBSERVING

        return self.state
