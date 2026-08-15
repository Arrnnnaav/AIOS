"""AWAITING_USER_ACTION must never verify against a stale observation.

With perception published into a slot, AWAITING can read back the SAME
observation OBSERVING used. Verification would then compare a state against
itself, conclude "nothing changed" forever, and every tour would stall on its
first step — the exact failure D019 warns about, reintroduced by the move to
a worker thread.

An untimestamped snapshot (observed_at == 0.0) is treated as fresh: that is
what a synchronous or faked perception is, and it keeps every existing fake
working.
"""

from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.grounding import GroundedTarget
from ghostcursor.reasoning.loop import GuidedTour, State
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor,
    Recipe,
    Risk,
    Step,
    TargetDescriptor,
    UserAction,
    VerificationKind,
    VerificationRule,
)
from ghostcursor.reasoning.verification import Snapshot

TARGET = GroundedTarget((10, 10, 110, 40), 1, "1001", "Button", "Export")
EXPORT = Element("Export", "Button", "1001", (10, 10, 110, 40))


class FakeRenderer:
    def __init__(self):
        self.shown, self.cleared = [], 0

    def show(self, grounded, instruction_text):
        self.shown.append(instruction_text)

    def clear(self):
        self.cleared += 1

    def settle(self):
        # Tick boundary (D027). Nothing to emit: this fake never draws.
        pass


def _recipe():
    return Recipe(
        app_id="t",
        intent="i",
        steps=[
            Step(
                user_action=UserAction.CLICK,
                target_descriptor=TargetDescriptor(
                    claimed=ClaimedDescriptor(name="Export")
                ),
                instruction_text="Click Export.",
                verification_rule=VerificationRule(
                    kind=VerificationKind.ELEMENT_APPEARS,
                    args={"target_descriptor": {"name": "Saved"}},
                ),
                risk=Risk.NORMAL,
            )
        ],
    )


def _tour(snapshots, verifier):
    seq = iter(snapshots)
    last = {"s": snapshots[-1]}

    def snapshotter():
        try:
            last["s"] = next(seq)
        except StopIteration:
            pass
        return last["s"]

    return GuidedTour(
        recipe=_recipe(),
        grounder=lambda step, i, elements=None: TARGET,
        snapshotter=snapshotter,
        verifier=verifier,
        renderer=FakeRenderer(),
        clock=lambda: 0.0,
    )


def test_a_stale_observation_is_not_verified_against():
    """The slot has not advanced: this is NO verification attempt, not a
    failed one."""
    stale = Snapshot("App", (EXPORT,), observed_at=100.0)
    calls = []

    def verifier(rule, before, after):
        calls.append((before.observed_at, after.observed_at))
        return True  # would advance if it were ever consulted

    tour = _tour([stale, stale, stale, stale, stale, stale], verifier)
    for _ in range(6):
        tour.tick()

    assert calls == [], "verification ran against an observation no newer than _before"
    assert tour.step_index == 0
    assert tour.state is State.AWAITING_USER_ACTION


def test_a_newer_observation_is_verified_against():
    before = Snapshot("App", (EXPORT,), observed_at=100.0)
    newer = Snapshot("App", (EXPORT,), observed_at=100.5)
    calls = []

    def verifier(rule, b, a):
        calls.append((b.observed_at, a.observed_at))
        return True

    # Each state transition (OBSERVING, DECIDING, RENDERING_HINT, then one
    # AWAITING poll per snapshot in the sequence, then VERIFYING, then the
    # step-advance back to OBSERVING) consumes exactly one tick() call, so
    # reaching the newer snapshot at the end of the sequence and then
    # advancing the step takes more than 6 ticks. Give it enough headroom.
    tour = _tour([before, before, before, before, newer, newer], verifier)
    for _ in range(12):
        tour.tick()

    assert calls, "a strictly newer observation was not verified against"
    assert tour.step_index == 1


def test_untimestamped_snapshots_are_treated_as_fresh():
    """Every existing fake returns the same untimestamped Snapshot forever.
    Those must keep verifying, or the collaborator contract was not preserved.
    """
    still = Snapshot("App", (EXPORT,))  # observed_at defaults to 0.0
    calls = []

    def verifier(rule, before, after):
        calls.append(1)
        return True

    tour = _tour([still] * 6, verifier)
    for _ in range(6):
        tour.tick()

    assert calls, "untimestamped snapshots were gated as stale"
    assert tour.step_index == 1
