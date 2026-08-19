"""A standing ceiling on how long anything on the tick path may block.

This project's hardest safety rule is that the overlay is always dismissable:
it is full-screen, topmost, click-through, has no title bar and never takes
focus, so ESC and the --seconds timeout are the only ways out. ESC is polled
BETWEEN ticks, which means a tick that blocks is a period where the user
cannot escape a window covering their screen.

That invariant has now been broken twice by unbounded blocking calls:

  - drawing outside WM_PAINT left the window surface uninitialised, painting
    an opaque wash over the whole desktop (D009);
  - three pywinauto `wait("exists", timeout=3)` calls per tick meant that when
    the target window was absent — the user alt-tabbed — a single tick blocked
    for ~9.1 SECONDS with the overlay up and ESC dead.

Both were found one at a time, after the fact. Nothing enforced the invariant
structurally. These tests do: any future blocking call on the tick path — an
OCR fallback, a VLM request, a knowledge-base lookup that reaches the network
— trips a test here instead of shipping silently.

Note what this file deliberately does NOT do: run a watchdog that rescues a
blocked tick at runtime. That cannot work. Win32 windows have thread affinity,
so DestroyWindow from a watchdog thread fails with "Access is denied" (verified
on this machine), and PostMessage needs the main thread's message pump — which
is exactly what a blocked tick is not running. The only real runtime fix is to
keep perception off the UI thread entirely, which is a separate change. Until
then, the guard is this ceiling, enforced in tests.
"""

import time

from ghostcursor.overlay import dpi  # noqa: F401  DPI awareness before any window
from ghostcursor.perception.uia import iter_elements
from ghostcursor.reasoning.verification import take_snapshot

#: A tick runs every 0.25s. Anything approaching that is already too slow, and
#: anything past half a second is a window in which the user cannot press ESC.
TICK_CEILING_S = 0.5

ABSENT = ".*NoSuchWindowAnywhere1234567.*"


def _elapsed(fn) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def test_perception_is_fast_when_the_target_window_is_absent():
    """The alt-tab case: the user switched away, so there is nothing to read.

    Answering "this window is not here" must cost a cheap window enumeration,
    not a UIA existence poll that times out.
    """
    elapsed = _elapsed(lambda: iter_elements(ABSENT))
    assert elapsed < TICK_CEILING_S, (
        f"iter_elements blocked {elapsed:.2f}s on an absent window; ESC is "
        "polled between ticks, so this is time the user cannot escape the overlay"
    )


def test_snapshotting_is_fast_when_the_target_window_is_absent():
    elapsed = _elapsed(lambda: take_snapshot(ABSENT))
    assert elapsed < TICK_CEILING_S, (
        f"take_snapshot blocked {elapsed:.2f}s on an absent window"
    )


def test_a_whole_tick_stays_under_the_ceiling_when_the_target_is_absent():
    """The composite: everything one tick does when the window is gone.

    Measured before this was fixed: ~9.1 seconds, every tick, for as long as
    the user stayed in another window.
    """

    def one_tick_of_perception():
        take_snapshot(ABSENT)  # OBSERVING
        iter_elements(ABSENT)  # DECIDING / grounding
        take_snapshot(ABSENT)  # AWAITING_USER_ACTION

    elapsed = _elapsed(one_tick_of_perception)
    assert elapsed < TICK_CEILING_S, (
        f"a tick against an absent window took {elapsed:.2f}s, over the "
        f"{TICK_CEILING_S}s ceiling — the overlay is on screen and ESC is dead "
        "for that whole time"
    )


def test_perception_is_fast_against_a_real_window():
    """The happy path has a ceiling too — a slow tick is a laggy hint."""
    from tests.uia_app import SyntheticApp

    with SyntheticApp() as app:
        title_re = f".*{app.title}.*"
        iter_elements(title_re)  # warm any first-call cost
        elapsed = _elapsed(lambda: iter_elements(title_re))

    assert elapsed < TICK_CEILING_S, f"reading a small live window took {elapsed:.2f}s"


def test_observing_and_deciding_share_one_tree_walk():
    """One walk per instant, not two.

    OBSERVING and DECIDING describe the SAME moment — "here is the screen, now
    decide what to point at" — so DECIDING reuses what OBSERVING read instead
    of walking again. That is both faster and more correct: two walks meant
    grounding could act on a screen state the snapshot never saw.

    AWAITING_USER_ACTION is excluded on purpose and still takes its own
    snapshot: its entire job is to look at a LATER moment and see whether the
    user acted. Sharing there would compare a state against itself.
    """
    from ghostcursor.perception import uia as uia_module
    from ghostcursor.reasoning import grounding as grounding_module
    from ghostcursor.reasoning import verification as verification_module
    from ghostcursor.reasoning.grounding import ground
    from ghostcursor.reasoning.loop import GuidedTour, State
    from ghostcursor.reasoning.schema import (
        ClaimedDescriptor, Recipe, Step, TargetDescriptor,
        UserAction, VerificationKind, VerificationRule,
    )
    from ghostcursor.reasoning.verification import take_snapshot, verify
    from tests.uia_app import SyntheticApp

    class NullRenderer:
        def show(self, grounded, instruction_text): pass
        def clear(self): pass
        def settle(self): pass  # tick boundary (D027)

    recipe = Recipe(app_id="synthetic", intent="i", steps=[Step(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor(name="Export")),
        instruction_text="Click Export.",
        verification_rule=VerificationRule(kind=VerificationKind.USER_CONFIRMS),
    )])

    walks = {"n": 0}
    real = uia_module.iter_elements

    def counting(title_re):
        walks["n"] += 1
        return real(title_re)

    with SyntheticApp() as app:
        title_re = f".*{app.title}.*"
        for module in (uia_module, verification_module, grounding_module):
            module.iter_elements = counting
        try:
            tour = GuidedTour(
                recipe=recipe,
                grounder=lambda s, i, elements=None: ground(s, title_re, elements=elements),
                snapshotter=lambda: take_snapshot(title_re),
                verifier=verify,
                renderer=NullRenderer(),
            )
            walks["n"] = 0
            for _ in range(4):  # IDLE -> OBSERVING -> DECIDING -> RENDERING_HINT
                tour.tick()
        finally:
            for module in (uia_module, verification_module, grounding_module):
                module.iter_elements = real

    assert tour.state is State.AWAITING_USER_ACTION
    assert walks["n"] == 1, (
        f"observing through to rendering the hint walked the UI tree "
        f"{walks['n']} times; DECIDING should reuse what OBSERVING read"
    )


def test_a_window_vanishing_mid_walk_is_handled_not_raised():
    """The race the cheap existence check cannot close.

    windows_matching() says the window is there, then it closes before the UIA
    walk reaches it. Waiting could not prevent this — it would only pay for it
    — so the walk is wrapped instead. This exercises that path directly rather
    than trusting it, by passing a title that resolves at check time and is
    gone by walk time.
    """
    from ghostcursor.perception import uia as uia_module
    from tests.uia_app import SyntheticApp

    with SyntheticApp(title="GhostCursorVanishProbe") as app:
        title_re = f".*{app.title}.*"
        assert uia_module.windows_matching(title_re), "probe window should exist"

    # The context manager destroyed the window: the existence check now fails
    # fast, and nothing raises.
    assert uia_module.iter_elements(title_re) == []

    # And the same when existence succeeds but the walk finds nothing usable:
    # a real Desktop() lookup against a title that no longer resolves.
    real_matching = uia_module.windows_matching
    uia_module.windows_matching = lambda _t: [12345]  # pretend it is still there
    try:
        assert uia_module.iter_elements(title_re) == [], (
            "a window that vanished between the check and the walk must return "
            "no elements, not raise"
        )
    finally:
        uia_module.windows_matching = real_matching
