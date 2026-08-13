from ghostcursor.perception.uia import Element  # noqa: F401  used in CHANGED
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


class FakeRenderer:
    def __init__(self):
        self.shown = []
        self.cleared = 0

    def show(self, grounded, instruction_text):
        self.shown.append((grounded, instruction_text))

    def clear(self):
        self.cleared += 1


def _step(kind=VerificationKind.ELEMENT_APPEARS, text="Click Export."):
    return Step(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor(name="Export")),
        instruction_text=text,
        verification_rule=VerificationRule(
            kind=kind, args={"target_descriptor": {"name": "Save"}}
        ),
        risk=Risk.NORMAL,
    )


STILL = Snapshot("App", ())
CHANGED = Snapshot("App", (Element("Dialog", "Window", "9001", (0, 0, 50, 50)),))


def _tour(steps=None, grounder=None, verifier=None, clock=None, snapshotter=None):
    recipe = Recipe(app_id="test", intent="t", steps=steps or [_step(), _step()])
    return GuidedTour(
        recipe=recipe,
        grounder=grounder or (lambda step, i: TARGET),
        snapshotter=snapshotter or (lambda: STILL),
        verifier=verifier or (lambda rule, before, after: True),
        renderer=FakeRenderer(),
        clock=clock or (lambda: 0.0),
    )


def test_reaches_awaiting_user_action_and_renders_the_hint():
    tour = _tour()
    for _ in range(4):
        tour.tick()
    assert tour.state is State.AWAITING_USER_ACTION
    assert tour.renderer.shown[0][1] == "Click Export."


def test_awaiting_is_a_dwelling_state_not_a_pass_through():
    # The user has not acted and nothing changed, so the tour must sit still.
    # Falling through to VERIFYING every tick is what previously made the
    # idle timer reset forever and the re-hint unreachable.
    tour = _tour(verifier=lambda rule, before, after: False)
    for _ in range(10):
        tour.tick()
    assert tour.state is State.AWAITING_USER_ACTION
    assert tour.step_index == 0
    assert len(tour.renderer.shown) == 1  # hint drawn once, not redrawn per tick


def test_successful_verification_advances_to_the_next_step():
    tour = _tour()
    for _ in range(6):
        tour.tick()
    assert tour.step_index == 1


def test_unexpected_change_reobserves_instead_of_advancing():
    # The user did something other than what was suggested. Re-plan from real
    # state rather than retrying a hint whose target may have moved.
    snaps = iter([STILL, CHANGED, CHANGED, CHANGED, CHANGED, CHANGED, CHANGED])
    tour = _tour(
        verifier=lambda rule, before, after: False,
        snapshotter=lambda: next(snaps, CHANGED),
    )
    for _ in range(5):
        tour.tick()
    assert tour.step_index == 0
    assert tour.state is State.OBSERVING


def test_completing_every_step_finishes_the_tour():
    tour = _tour(steps=[_step()])
    for _ in range(8):
        tour.tick()
    assert tour.state is State.DONE
    assert tour.renderer.cleared >= 1


def test_ungroundable_step_fails_rather_than_guessing():
    tour = _tour(grounder=lambda step, i: None)
    for _ in range(4):
        tour.tick()
    assert tour.state is State.FAILED


def test_user_confirms_step_waits_for_confirm():
    tour = _tour(
        steps=[_step(kind=VerificationKind.USER_CONFIRMS)],
        verifier=lambda rule, before, after: False,
    )
    for _ in range(5):
        tour.tick()
    assert tour.state is State.AWAITING_USER_ACTION

    tour.confirm()
    for _ in range(3):
        tour.tick()
    assert tour.state is State.DONE


def test_idle_timeout_rehints_once_then_goes_quiet():
    now = {"t": 0.0}
    tour = _tour(verifier=lambda rule, before, after: False, clock=lambda: now["t"])
    for _ in range(4):
        tour.tick()
    assert tour.state is State.AWAITING_USER_ACTION
    assert tour.rehint_count == 0

    now["t"] = 31.0
    tour.tick()
    assert tour.rehint_count == 1

    now["t"] = 62.0
    tour.tick()
    assert tour.rehint_count == 1  # never nags twice


def test_idle_timer_survives_a_reobserve_cycle():
    # Regression: re-entering RENDERING_HINT for the SAME step must not reset
    # the idle clock, or the timeout can never elapse in a real run.
    now = {"t": 0.0}
    snaps = iter([STILL, CHANGED])
    tour = _tour(
        verifier=lambda rule, before, after: False,
        clock=lambda: now["t"],
        snapshotter=lambda: next(snaps, CHANGED),
    )
    for _ in range(5):
        tour.tick()
    assert tour.state is State.OBSERVING  # unexpected change sent us back

    now["t"] = 31.0
    for _ in range(4):  # OBSERVING -> DECIDING -> RENDERING_HINT -> AWAITING
        tour.tick()
    assert tour.rehint_count == 1, "idle clock was reset by the re-observe cycle"
