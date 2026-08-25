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
from ghostcursor.reasoning.verification import Snapshot, verify

TARGET = GroundedTarget((10, 10, 110, 40), 1, "1001", "Button", "Export", "uia")


class FakeRenderer:
    def __init__(self):
        self.shown = []
        self.cleared = 0

    def show(self, grounded, instruction_text):
        self.shown.append((grounded, instruction_text))

    def clear(self):
        self.cleared += 1

    def settle(self):
        # Tick boundary (D027). This fake draws nothing, so there is nothing
        # to emit — but the loop calls it on every tick, so it must exist.
        pass


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
        grounder=grounder or (lambda step, i, elements=None: TARGET),
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
    snapshots = iter((STILL, CHANGED, CHANGED))
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
    # Finding 5: a momentarily ungroundable step (minimized window, a brief
    # alt-tab) must not fail immediately -- only once grounding has failed
    # CONTINUOUSLY past the grace period. The fake clock, not real sleeping,
    # is what makes this deterministic and fast.
    now = {"t": 0.0}
    tour = _tour(grounder=lambda step, i, elements=None: None, clock=lambda: now["t"])
    for _ in range(6):
        tour.tick()
        now["t"] += 1.0
    assert tour.state is not State.FAILED  # still inside the grace period

    now["t"] += 20.0
    for _ in range(2):
        tour.tick()
    assert tour.state is State.FAILED
    assert tour.failure_reason is not None


def test_a_temporarily_ungroundable_step_recovers_within_the_grace_period():
    # Finding 5: grounding fails for a few ticks (window minimized) then
    # succeeds again (window restored) -- the tour must keep going, and must
    # never reach FAILED.
    now = {"t": 0.0}
    attempts = iter([None, None, None, TARGET, TARGET, TARGET, TARGET, TARGET])
    tour = _tour(
        grounder=lambda step, i, elements=None: next(attempts, TARGET),
        verifier=lambda rule, before, after: False,
        clock=lambda: now["t"],
    )
    for _ in range(12):
        tour.tick()
        now["t"] += 1.0
        assert tour.state is not State.FAILED
    assert tour.state is State.AWAITING_USER_ACTION


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


def test_recipe_can_fail_after_bounded_post_action_verification_timeout():
    now = {"t": 0.0}
    step = _step()
    step.verification_rule.timeout_s = 20.0
    step.verification_rule.args["fail_after_timeout"] = True
    snapshots = iter((STILL, CHANGED, CHANGED))
    tour = _tour(
        steps=[step],
        verifier=lambda rule, before, after: False,
        clock=lambda: now["t"],
        snapshotter=lambda: next(snapshots, CHANGED),
    )
    for _ in range(4):
        tour.tick()
    assert tour.state is State.AWAITING_USER_ACTION

    now["t"] = 1.0
    tour.tick()  # changed elements mark the user action boundary
    assert tour.state is State.OBSERVING

    now["t"] = 21.1
    for _ in range(4):
        tour.tick()
    tour.tick()
    assert tour.state is State.FAILED
    assert "20s" in tour.failure_reason


def test_timeout_from_hint_bounds_a_keyboard_action_with_no_detectable_change():
    now = {"t": 0.0}
    step = _step()
    step.verification_rule.timeout_s = 20.0
    step.verification_rule.args.update(
        fail_after_timeout=True,
        timeout_from_hint=True,
    )
    tour = _tour(
        steps=[step],
        verifier=lambda rule, before, after: False,
        clock=lambda: now["t"],
        snapshotter=lambda: STILL,
    )

    for _ in range(4):
        tour.tick()
    assert tour.state is State.AWAITING_USER_ACTION

    now["t"] = 20.1
    tour.tick()

    assert tour.state is State.FAILED
    assert tour.failure_reason == "verification timed out after 20s"


def test_timeout_wins_when_the_verified_state_arrives_after_the_deadline():
    now = {"t": 0.0}
    step = _step()
    step.verification_rule.timeout_s = 20.0
    step.verification_rule.args.update(
        fail_after_timeout=True,
        timeout_from_hint=True,
    )
    save_present = Snapshot("App", (SAVE,))
    snapshots = iter((STILL, save_present))
    tour = _tour(
        steps=[step],
        verifier=verify,
        clock=lambda: now["t"],
        snapshotter=lambda: next(snapshots, save_present),
    )

    for _ in range(4):
        tour.tick()
    now["t"] = 20.1
    tour.tick()

    assert tour.state is State.FAILED


def test_already_present_goal_completes_without_rendering_or_grounding():
    step = _step()
    step.verification_rule.args["accept_if_already_present"] = True
    save_present = Snapshot("App", (SAVE,))
    ground_calls = []
    tour = _tour(
        steps=[step],
        grounder=lambda *args: ground_calls.append(args) or TARGET,
        verifier=verify,
        snapshotter=lambda: save_present,
    )

    for _ in range(5):
        tour.tick()

    assert tour.state is State.DONE
    assert ground_calls == []
    assert tour.renderer.shown == []


# --- finding 1: ordinary title churn must not bounce the tour to OBSERVING --

EXPORT = Element("Export", "Button", "1001", (10, 10, 110, 40))
SAVE = Element("Save", "Button", "1002", (10, 50, 110, 80))


def _real_step():
    # Uses the real verify() with an element_appears rule so these tests
    # exercise the actual identity comparison, not a stubbed verifier.
    return Step(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor(name="Export")),
        instruction_text="Click Export.",
        verification_rule=VerificationRule(
            kind=VerificationKind.ELEMENT_APPEARS,
            args={"target_descriptor": {"name": "Save"}},
        ),
        risk=Risk.NORMAL,
    )


def test_title_only_churn_does_not_bounce_to_observing():
    # Snapshot equality includes `title`, which take_snapshot fills from
    # GetForegroundWindow() -- so a plain alt-tab or a window retitling makes
    # `after != before` even though no element moved. Reacting to that with
    # a re-observe would unconditionally re-baseline `_before`, and if the
    # user's real change lands on the same tick, it gets folded into the new
    # baseline and can never be detected again.
    before = Snapshot(title="App", elements=(EXPORT,))
    churned = Snapshot(title="App - Untitled", elements=(EXPORT,))  # title only
    snaps = iter([before, churned, churned, churned, churned])

    tour = _tour(
        steps=[_real_step(), _real_step()],
        verifier=verify,
        snapshotter=lambda: next(snaps, churned),
    )
    for _ in range(6):
        tour.tick()

    assert tour.state is State.AWAITING_USER_ACTION
    assert tour.step_index == 0


def test_churn_then_the_users_real_change_still_advances_the_step():
    # Reproduces the original stall: an ordinary title tick happens first,
    # then the user does the thing the step asked for. If churn had
    # re-baselined `_before`, the later element_appears check would compare
    # against a baseline that already contains "Save" and never fire.
    before = Snapshot(title="App", elements=(EXPORT,))
    churned = Snapshot(title="App - Untitled", elements=(EXPORT,))  # title only
    done = Snapshot(title="App - Untitled", elements=(EXPORT, SAVE))
    snaps = iter([before, churned, churned, done, done, done])

    tour = _tour(
        steps=[_real_step(), _real_step()],
        verifier=verify,
        snapshotter=lambda: next(snaps, done),
    )
    for _ in range(8):
        tour.tick()

    assert tour.step_index == 1
