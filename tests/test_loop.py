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


def test_an_already_satisfied_selector_rule_completes_rather_than_faulting():
    """`accept_if_already_present` against a compiled selector (finding 4).

    The baseline the loop builds for this check must say every selector was
    observed and matched nothing. `selector_results=()` says nothing was
    observed at all, which `Snapshot.matched()` correctly treats as a fault --
    so an already-visible terminal raised instead of completing, and Open
    Terminal is precisely the recipe that uses this option.
    """
    from ghostcursor.perception.uia import Element
    from ghostcursor.reasoning.compiled_tour import compiled_steps
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
    from types import SimpleNamespace

    del compiled_steps  # imported only to prove the compiled path is in scope

    present = (Element("Terminal Section", "Pane", "", (0, 0, 10, 10), ("Pane",)),)
    step = Step(
        user_action=UserAction.PRESS_KEYS,
        target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor(name="Terminal")),
        instruction_text="Press Ctrl+`",
        verification_rule=VerificationRule(
            kind=VerificationKind.ELEMENT_APPEARS,
            args={"accept_if_already_present": True},
            selector="panel",
        ),
        risk=Risk.NORMAL,
    )

    class _Renderer:
        def show(self, grounded, instruction_text):
            raise AssertionError("an already-satisfied goal must not be re-hinted")

        def clear(self):
            pass

        def settle(self):
            pass

    def _snapshotter():
        return Snapshot(
            title="x", elements=present, selector_results=(("panel", present),)
        )

    tour = GuidedTour(
        recipe=SimpleNamespace(steps=(step,)),
        grounder=lambda s, i, e: None,
        snapshotter=_snapshotter,
        verifier=verify,
        renderer=_Renderer(),
        clock=lambda: 0.0,
    )
    states = [tour.tick() for _ in range(5)]
    assert State.DONE in states, states
# ---------------------------------------------------------------------------
# A step whose action removes its own target
# ---------------------------------------------------------------------------
#
# Reproduced live on VS Code 1.135.0.0: opening a folder replaces the Welcome
# page, so `Open Folder...` stops existing at the moment the step succeeds.
# Two runs differing only in a 0.25s gap gave opposite outcomes.
# See `docs/evidence/open-folder-target-disappearance.md`.

#: The world after the action: the old target is gone and the title has not
#: caught up yet. This is the snapshot the loop used to re-baseline against.
GONE = Snapshot("App", (Element("Editor", "Pane", "9002", (0, 0, 80, 80)),))
#: The verified outcome, arriving a moment later.
COMPLETED = Snapshot("demo - App", (Element("Editor", "Pane", "9002", (0, 0, 80, 80)),))


def _vanishing_tour(snapshots, *, clock=None, step=None):
    """A tour whose target disappears once the world stops matching STILL."""
    seen = iter(snapshots)
    latest = {"snap": STILL}

    def _snapshotter():
        latest["snap"] = next(seen, snapshots[-1])
        return latest["snap"]

    def _grounder(step_, index, elements=None):
        # Grounds only while the original control is on screen, exactly as a
        # selector does: the target is gone, so there is nothing to return.
        return TARGET if latest["snap"] is STILL else None

    def _verifier(rule, before, after):
        # The recipe's real question for Open Folder: did the title change
        # from the pre-action baseline?
        return before.title != after.title

    return _tour(
        steps=[step or _step()],
        grounder=_grounder,
        verifier=_verifier,
        clock=clock,
        snapshotter=_snapshotter,
    )


def test_a_vanished_target_does_not_fail_a_step_that_succeeded() -> None:
    """The goal was met; the run must say so.

    Before this, the grounding grace -- meant for a window minimised or
    alt-tabbed away BEFORE the action -- counted down against a step whose
    action had already worked, and reported "cannot find X on screen" ten
    seconds after the verified outcome had arrived.
    """
    now = {"t": 0.0}
    tour = _vanishing_tour([STILL, STILL, GONE, COMPLETED], clock=lambda: now["t"])

    for _ in range(20):
        now["t"] += 1.0
        tour.tick()
        if tour.state in (State.DONE, State.FAILED):
            break

    assert tour.state is State.DONE, tour.failure_reason


def test_the_grounding_grace_is_not_spent_after_the_action() -> None:
    """Past the full grace and still not failed, because the clock armed.

    The grace is 10s. This run pushes well past it with the target gone the
    whole time, and the step must still be waiting on its verification rather
    than declaring the window lost.
    """
    now = {"t": 0.0}
    tour = _vanishing_tour([STILL, STILL, GONE], clock=lambda: now["t"])

    for _ in range(30):
        now["t"] += 2.0
        tour.tick()

    assert now["t"] > 10.0 * 2, "the run did not outlast the grounding grace"
    assert tour.state is not State.FAILED, tour.failure_reason


def test_the_grounding_grace_still_fails_a_step_before_any_action() -> None:
    """The grace keeps its real job. Nothing was acted on here, so a target
    that cannot be found is a lost window and the step must give up."""
    now = {"t": 0.0}
    tour = _tour(
        steps=[_step()],
        grounder=lambda step, index, elements=None: None,
        verifier=lambda rule, before, after: False,
        clock=lambda: now["t"],
    )

    for _ in range(30):
        now["t"] += 2.0
        tour.tick()

    assert tour.state is State.FAILED
    assert "cannot find" in tour.failure_reason


def test_the_verification_baseline_stops_moving_once_an_action_is_detected() -> None:
    """The mechanism, asserted directly.

    Re-baselining after the action compares the post-action world against
    itself, so the change the rule waits for can never be seen. Whether it
    happened before or after the title caught up was a race, which is why two
    identical live runs disagreed.
    """
    now = {"t": 0.0}
    tour = _vanishing_tour([STILL, STILL, GONE, COMPLETED], clock=lambda: now["t"])

    baselines = []
    for _ in range(20):
        now["t"] += 1.0
        tour.tick()
        if tour._verification_started_at is not None and tour._before is not None:
            baselines.append(tour._before.title)
        if tour.state in (State.DONE, State.FAILED):
            break

    assert baselines, "no action was ever detected"
    assert set(baselines) == {"App"}, baselines


def test_interrupt_detection_compares_consecutive_observations() -> None:
    """Freezing the baseline must not freeze "did the world just change".

    They were one field. Freezing it made `elements_changed` true on every
    tick forever, so the loop ping-ponged between OBSERVING and AWAITING and
    never reached its idle re-hint -- a fix that swapped one stall for another.
    """
    now = {"t": 0.0}
    tour = _vanishing_tour([STILL, STILL, GONE], clock=lambda: now["t"])

    for _ in range(6):
        now["t"] += 1.0
        tour.tick()

    # Settled: the world changed once and then stopped, so the loop must stop
    # treating every later tick as a fresh interrupt.
    states = []
    for _ in range(6):
        now["t"] += 1.0
        tour.tick()
        states.append(tour.state)
    assert State.AWAITING_USER_ACTION in states, states
def test_a_republished_observation_is_not_a_new_one() -> None:
    """The newness gate must ask "has anything been published since I last
    looked", not "is this later than the baseline".

    Once the baseline is frozen, every later snapshot is trivially later than
    it, so gating on the baseline answers yes forever -- and AWAITING starts
    evaluating verification against an observation it has already judged,
    which is the compare-a-state-against-itself bug the gate exists to stop.
    """
    now = {"t": 0.0}
    first = Snapshot("App", (), observed_at=1.0)
    acted = Snapshot("App", GONE.elements, observed_at=2.0)
    #: The SAME moment republished: the worker overwrites one slot, so the
    #: loop reads the same observation many times between publications.
    stale = Snapshot("App", GONE.elements, observed_at=2.0)

    snaps = iter([first, first, acted, stale, stale, stale, stale, stale])
    calls = []

    def _verifier(rule, before, after):
        calls.append(after.observed_at)
        return False

    tour = _tour(
        steps=[_step()],
        grounder=lambda step, i, elements=None: TARGET,
        verifier=_verifier,
        clock=lambda: now["t"],
        snapshotter=lambda: next(snaps, stale),
    )
    for _ in range(10):
        now["t"] += 1.0
        tour.tick()

    assert calls, "verification never ran"
    assert calls.count(2.0) == 1, (
        f"the same observation was judged {calls.count(2.0)} times: {calls}"
    )


def test_a_vanished_target_is_never_re_hinted_at_its_old_rectangle() -> None:
    """The idle re-hint must not point at a control that is gone.

    After the action removes the target, `_grounded` is None. Re-showing the
    last rectangle would ring empty screen in the confirmed-control colour,
    which is the one thing a ring must never do (D006) -- and the real
    renderer reads `grounded.bbox`, so it would raise rather than mislead.
    `FakeRenderer` accepts anything, so assert on WHAT was shown.
    """
    now = {"t": 0.0}
    tour = _vanishing_tour([STILL, STILL, GONE], clock=lambda: now["t"])

    for _ in range(40):
        now["t"] += 2.0
        tour.tick()

    assert now["t"] > 30.0, "the run did not outlast the idle timeout"
    assert tour.renderer.shown, "no hint was ever drawn"
    assert all(grounded is not None for grounded, _text in tour.renderer.shown), (
        tour.renderer.shown
    )


def test_a_repeat_read_while_dwelling_is_not_a_new_observation() -> None:
    """AWAITING must advance its own notion of "last seen", not rely on
    OBSERVING to do it.

    OBSERVING refreshes it too, which hides the omission on any path that
    leaves and re-enters. A step that DWELLS -- the title changed but no
    element moved, so nothing sends the loop back to OBSERVING -- reads the
    same published slot several times between publications, and each repeat
    would be judged as if it were fresh.
    """
    now = {"t": 0.0}
    shared = (Element("Pane", "Pane", "9003", (0, 0, 10, 10)),)
    first = Snapshot("App", shared, observed_at=1.0)
    # Same elements, new title: nothing to interrupt on, so the loop stays put.
    titled = Snapshot("App2", shared, observed_at=2.0)

    snaps = iter([first, first, titled, titled, titled, titled])
    calls = []

    def _verifier(rule, before, after):
        calls.append(after.observed_at)
        return False

    tour = _tour(
        steps=[_step()],
        grounder=lambda step, i, elements=None: TARGET,
        verifier=_verifier,
        clock=lambda: now["t"],
        snapshotter=lambda: next(snaps, titled),
    )
    for _ in range(8):
        now["t"] += 1.0
        tour.tick()

    assert tour.state is State.AWAITING_USER_ACTION, tour.state
    assert calls.count(2.0) == 1, (
        f"the same observation was judged {calls.count(2.0)} times: {calls}"
    )
