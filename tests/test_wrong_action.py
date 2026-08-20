"""The loop's wrong-action decision.

Read tests/test_loop.py first for the collaborator-fake pattern this builds
on. Every fake here is deliberate: this file tests the DECISION, and Task 2
tests whether focus_visited is faithful. Neither test alone is sufficient
(D031) -- an invariant about a list only implies the property if the list is
faithful, and that is a different test.
"""

import pytest

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

from tests.test_loop import FakeRenderer, STILL, CHANGED  # reuse existing fakes


def _step():
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


class Harness:
    """Drives a GuidedTour to AWAITING_USER_ACTION and lets a test control
    focus_visited, verification satisfaction, and step completion one tick at
    a time -- exactly the surface the brief's fixture calls for.
    """

    def __init__(self, target_id: str):
        self._target_id = target_id
        self._focus_visited: tuple[str, ...] = ()
        self._satisfied = False
        self.wrong_actions: list[tuple[str, str]] = []

        recipe = Recipe(app_id="test", intent="t", steps=[_step(), _step()])
        target = GroundedTarget(
            (10, 10, 110, 40), 1, target_id, "Button", "Export", "uia"
        )

        # Snapshot changes each call after arrival so AWAITING_USER_ACTION's
        # `_is_newer` gate does not swallow the tick -- reuses the same STILL
        # / CHANGED fakes test_loop.py already defines.
        self._snaps = iter([STILL] + [CHANGED] * 200)

        self.tour = GuidedTour(
            recipe=recipe,
            grounder=lambda step, i, elements=None: target,
            snapshotter=lambda: next(self._snaps, CHANGED),
            verifier=lambda rule, before, after: self._satisfied,
            renderer=FakeRenderer(),
            clock=lambda: 0.0,
            focus_visited_source=lambda: self._focus_visited,
            on_wrong_action=self._record,
        )

    def _record(self, touched: str, target_id: str) -> None:
        self.wrong_actions.append((touched, target_id))

    def _tick_until_awaiting(self, max_ticks: int = 10) -> None:
        """Advance until the tour is AT (not through) AWAITING_USER_ACTION.

        Stops the instant the state becomes AWAITING_USER_ACTION, before that
        state's own logic runs -- ticking a fixed count is only safe starting
        from IDLE. Re-entering (e.g. after a wrong-action re-hint sent the
        tour back through OBSERVING) starts partway around the loop, and one
        tick too many would execute AWAITING_USER_ACTION's logic against
        whatever focus_visited happens to be set at that moment instead of
        what the test sets afterward.
        """
        for _ in range(max_ticks):
            if self.tour.state is State.AWAITING_USER_ACTION:
                return
            self.tour.tick()
        raise AssertionError("never reached AWAITING_USER_ACTION")

    def arrive_at_awaiting(self) -> None:
        # Stale focus from a previous attempt must not leak into the tick(s)
        # that walk back around to AWAITING_USER_ACTION.
        self._focus_visited = ()
        self._tick_until_awaiting()

    def set_focus_visited(self, ids: tuple[str, ...]) -> None:
        self._focus_visited = ids

    def satisfy_verification(self) -> None:
        self._satisfied = True

    def complete_step(self) -> None:
        """Drive the CURRENT step to completion (VERIFYING -> next OBSERVING
        -> DECIDING -> RENDERING_HINT -> AWAITING_USER_ACTION) so the counter
        reset can be observed on a genuinely fresh step."""
        self._focus_visited = ()
        self._tick_until_awaiting()
        self._satisfied = True
        self.tour.tick()  # AWAITING_USER_ACTION -> VERIFYING
        self.tour.tick()  # VERIFYING -> OBSERVING (resets the counter here)
        self._satisfied = False
        self._tick_until_awaiting()

    def tick(self) -> None:
        self.tour.tick()


@pytest.fixture
def wrong_action_tour():
    def make(target_id: str) -> Harness:
        return Harness(target_id)

    return make


def test_fires_when_focus_visited_a_non_target_control(wrong_action_tour):
    h = wrong_action_tour(target_id="1001")
    h.arrive_at_awaiting()

    h.set_focus_visited(("1002",))
    h.tick()

    assert h.wrong_actions == [("1002", "1001")]
    assert h.tour.state is State.OBSERVING


def test_silent_when_focus_visited_only_the_target(wrong_action_tour):
    h = wrong_action_tour(target_id="1001")
    h.arrive_at_awaiting()

    h.set_focus_visited(("1001",))
    h.tick()

    assert h.wrong_actions == []


def test_silent_when_nothing_was_focused(wrong_action_tour):
    h = wrong_action_tour(target_id="1001")
    h.arrive_at_awaiting()

    h.set_focus_visited(())
    h.tick()

    assert h.wrong_actions == []


def test_satisfied_wins_over_a_detour(wrong_action_tour):
    """The user touched the wrong control and then did the right thing. The
    step succeeded; interrupting a success to criticise it is the Clippy
    failure this loop is built to avoid."""
    h = wrong_action_tour(target_id="1001")
    h.arrive_at_awaiting()

    h.set_focus_visited(("1002",))
    h.satisfy_verification()
    h.tick()

    assert h.tour.state is State.VERIFYING
    assert h.wrong_actions == [], "scolded the user for a step they completed"


def test_silent_when_the_target_was_grounded_by_ocr(wrong_action_tour):
    """OCR elements carry no AutomationId, so there is nothing to compare
    against. Firing here would report a wrong action on every focus change."""
    h = wrong_action_tour(target_id="")
    h.arrive_at_awaiting()

    h.set_focus_visited(("1002",))
    h.tick()

    assert h.wrong_actions == []


def test_rehints_are_capped_at_three_but_messages_are_not(wrong_action_tour):
    """The cap counts RE-HINTS, not messages. Going quiet entirely would tell
    a user who keeps trying and failing less the harder they struggle, which
    is backwards for a teaching system."""
    h = wrong_action_tour(target_id="1001")
    seen = []
    for _ in range(5):
        h.arrive_at_awaiting()
        h.set_focus_visited(("1002",))
        h.tick()
        seen.append(h.tour.wrong_action_rehints)

    assert seen == [1, 2, 3, 3, 3], "re-hint counter is not capped at 3"
    assert len(h.wrong_actions) == 5, "stopped speaking after the re-hint cap"


def test_wrong_action_focus_source_is_read_once_per_tick():
    """focus_visited_source reads a slot the perception worker overwrites
    without a lock (D021/D022) -- two reads in the same tick are not
    guaranteed to agree. This source returns a DIFFERENT value on its first
    call than on every later call, so a buggy two-call implementation (guard
    on one call, bind the message from a second) diverges from a correct
    single-bind implementation. A static-tuple source, as the rest of this
    file uses, cannot tell the two apart -- that is why the double-call bug
    was invisible to every other test and to mutation-verify."""
    calls = {"n": 0}

    def focus_source():
        calls["n"] += 1
        # First call: the wrong control. Every call after: nothing -- as if
        # the worker had already overwritten the slot with a fresh, empty
        # read by the time a second call happened.
        return ("1002",) if calls["n"] == 1 else ()

    recipe = Recipe(app_id="test", intent="t", steps=[_step(), _step()])
    target = GroundedTarget((10, 10, 110, 40), 1, "1001", "Button", "Export", "uia")
    snaps = iter([STILL] + [CHANGED] * 20)
    seen: list[tuple[str, str]] = []

    tour = GuidedTour(
        recipe=recipe,
        grounder=lambda step, i, elements=None: target,
        snapshotter=lambda: next(snaps, CHANGED),
        verifier=lambda rule, before, after: False,
        renderer=FakeRenderer(),
        clock=lambda: 0.0,
        focus_visited_source=focus_source,
        on_wrong_action=lambda touched, target_id: seen.append((touched, target_id)),
    )
    for _ in range(4):
        tour.tick()
    assert tour.state is State.AWAITING_USER_ACTION

    tour.tick()

    assert seen == [("1002", "1001")], (
        f"on_wrong_action saw {seen!r} -- two reads of focus_visited_source "
        "disagreed within one tick"
    )


def test_falls_through_to_elements_changed_after_the_rehint_cap():
    """Past the wrong-action re-hint cap, a tick must still reach the
    elements_changed arm below it in the elif chain. Short-circuiting on
    `touched is not None` past the cap stopped the loop re-grounding at all,
    so a wrong click that moved the target would go unnoticed forever.

    Built by hand rather than with Harness because it needs precise control
    over which of the seven OBSERVING/AWAITING_USER_ACTION cycles'
    snapshotter() calls returns which value: calls 1-7 are identical (so
    elements_changed stays False while the cap ramps up from 0 to 3), and
    call 8 -- the AWAITING_USER_ACTION check made AFTER the cap is already
    reached -- introduces a new element, so elements_changed is True only on
    that final check.

    MUTATION-VERIFY (D018): restoring the short-circuit (`elif touched is
    not None:` with the cap check inside, and no separate `elif
    elements_changed(...)` reachable once `touched` is non-None) makes this
    test fail -- the state stays AWAITING_USER_ACTION instead of reaching
    OBSERVING via elements_changed.
    """
    recipe = Recipe(app_id="test", intent="t", steps=[_step(), _step()])
    target = GroundedTarget((10, 10, 110, 40), 1, "1001", "Button", "Export", "uia")

    snaps = [STILL] * 7 + [CHANGED]
    calls = {"n": 0}

    def snapshotter():
        i = calls["n"]
        calls["n"] += 1
        return snaps[i] if i < len(snaps) else CHANGED

    wrong_actions: list[tuple[str, str]] = []
    tour = GuidedTour(
        recipe=recipe,
        grounder=lambda step, i, elements=None: target,
        snapshotter=snapshotter,
        verifier=lambda rule, before, after: False,
        renderer=FakeRenderer(),
        clock=lambda: 0.0,
        focus_visited_source=lambda: ("1002",),
        on_wrong_action=lambda touched, tid: wrong_actions.append((touched, tid)),
    )

    # 16 ticks: three full wrong-action rehint cycles (ticks 1-13, ending
    # with wrong_action_rehints == 3), then a fourth cycle's OBSERVING ->
    # DECIDING -> RENDERING_HINT -> AWAITING_USER_ACTION (ticks 14-16),
    # arriving back at AWAITING_USER_ACTION with the cap already spent.
    for _ in range(16):
        tour.tick()

    assert tour.wrong_action_rehints == 3, "cap not reached as expected by tick 16"
    assert tour.state is State.AWAITING_USER_ACTION
    assert len(wrong_actions) == 3, "unexpected message count before the capped tick"

    tour.tick()  # tick 17: the capped AWAITING_USER_ACTION check

    assert tour.state is State.OBSERVING, (
        "a capped wrong-action tick did not fall through to elements_changed "
        "-- the loop stopped re-grounding entirely"
    )
    assert tour.wrong_action_rehints == 3, "the cap incremented past its bound"
    assert len(wrong_actions) == 4, "the message stopped firing past the cap"


def test_the_counter_resets_on_a_new_step(wrong_action_tour):
    h = wrong_action_tour(target_id="1001")
    h.arrive_at_awaiting()
    h.set_focus_visited(("1002",))
    h.tick()
    assert h.tour.wrong_action_rehints == 1

    h.complete_step()
    assert h.tour.wrong_action_rehints == 0, (
        "a previous step's fumbles are being counted against a fresh one"
    )
