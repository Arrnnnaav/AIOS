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
from ghostcursor.reasoning.verification import Snapshot


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
        grounder: Callable[[Step, int], GroundedTarget | None],
        snapshotter: Callable[[], Snapshot],
        verifier: Callable[..., bool],
        renderer: Renderer,
        clock: Callable[[], float] = time.monotonic,
        idle_timeout_s: float = 30.0,
    ) -> None:
        self.recipe = recipe
        self.grounder = grounder
        self.snapshotter = snapshotter
        self.verifier = verifier
        self.renderer = renderer
        self.clock = clock
        self.idle_timeout_s = idle_timeout_s

        self.state = State.IDLE
        self.step_index = 0
        self.rehint_count = 0
        self.failure_reason: str | None = None

        self._before: Snapshot | None = None
        self._grounded: GroundedTarget | None = None
        self._waiting_since = 0.0
        self._confirmed = False
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
            self._grounded = self.grounder(step, self.step_index)
            if self._grounded is None:
                # Never guess a coordinate. Say so instead.
                self.renderer.clear()
                self.failure_reason = (
                    f"cannot find {step.target_descriptor.claimed.name!r} on screen"
                )
                self.state = State.FAILED
            else:
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

            if step.verification_rule.kind is VerificationKind.USER_CONFIRMS:
                satisfied = self._confirmed
            else:
                satisfied = self.verifier(step.verification_rule, self._before, after)

            if satisfied:
                self.state = State.VERIFYING
            elif after != self._before:
                # The world changed, but not into what we predicted — the user
                # did something else. Re-observe and re-ground: the target may
                # have moved or be gone. AndroidWorld-style interrupt handling.
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
