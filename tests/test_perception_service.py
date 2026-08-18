"""Perception runs on a worker thread and publishes into a single slot.

The UI thread must never block on it, however slow the target is.

Every wait in here is a condition poll with a deadline, never a bare sleep
sized to "probably long enough". A threading test that passes because a sleep
happened to be generous is worse than no test: the bug it would catch is
itself intermittent.
"""

import threading
import time

from ghostcursor.perception.service import Observation, PerceptionService
from ghostcursor.perception.uia import Element

EXPORT = Element("Export", "Button", "1001", (10, 10, 110, 40))


def _service(walker, **kw):
    return PerceptionService(
        title_re=".*Whatever.*", walker=walker, interval_s=0.01, **kw
    )


def _wait_until(predicate, timeout=5.0, what="condition"):
    """Poll until predicate() is true. Returns its value; fails loudly."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.005)
    raise AssertionError(f"{what} never became true within {timeout}s")


def _stepping_clock():
    """A clock that advances by exactly 1.0 per call.

    time.monotonic() has ~15ms granularity on Windows, so with a 10ms tick
    two consecutive observations can legitimately share a timestamp. Any test
    asserting that time ADVANCES must not be at the mercy of that.
    """
    ticks = {"t": 0.0}

    def clock():
        ticks["t"] += 1.0
        return ticks["t"]

    return clock


def _observation_containers(service):
    """Attribute names on the service holding more than a lone Observation.

    The slot is a slot: nothing on this object may accumulate observations.
    """
    offenders = []
    for name, value in vars(service).items():
        if isinstance(value, (str, bytes)) or isinstance(value, Observation):
            continue
        items = value.values() if isinstance(value, dict) else value
        try:
            iterator = iter(items)
        except TypeError:
            continue
        if any(isinstance(x, Observation) for x in iterator):
            offenders.append(name)
    return offenders


def test_latest_is_none_before_anything_has_been_observed():
    service = _service(lambda t: [EXPORT])
    assert service.latest() is None


def test_the_worker_publishes_observations():
    service = _service(lambda t: [EXPORT])
    service.start()
    try:
        observation = _wait_until(service.latest, what="an observation")
    finally:
        service.stop()

    assert observation is not None
    assert observation.ok is True
    assert observation.elements == (EXPORT,)
    assert observation.observed_at > 0


def test_the_slot_holds_only_the_newest_observation():
    """The entire architectural claim of this service.

    Three separate things have to hold, and each catches a different way of
    getting it wrong: the timestamp ADVANCES (the slot is not frozen at the
    first observation), the payload is the NEWEST walk and only that walk
    (elements do not accumulate), and the service keeps no history anywhere
    (the slot has not quietly become a queue read from the tail).
    """
    counter = {"n": 0}

    def walker(title_re):
        counter["n"] += 1
        return [Element(f"E{counter['n']}", "Button", str(counter["n"]), (0, 0, 5, 5))]

    service = _service(walker, clock=_stepping_clock())
    service.start()
    try:
        first = _wait_until(service.latest, what="a first observation")

        def _newer_than_first():
            observation = service.latest()
            if observation is not None and observation.observed_at > first.observed_at:
                return observation
            return None

        second = _wait_until(_newer_than_first, what="a second, later observation")
    finally:
        service.stop()

    assert second.observed_at > first.observed_at, "the slot froze at the first walk"
    assert len(second.elements) == 1, "the slot accumulated instead of overwriting"
    assert second.elements[0].name != first.elements[0].name, (
        "latest() returned a stale observation — the newest walk did not "
        "overwrite the slot"
    )
    assert _observation_containers(service) == [], (
        "the service retained a collection of observations — the slot is "
        "supposed to hold exactly one, with no history"
    )


def test_an_empty_result_still_counts_as_a_successful_observation():
    """Spec: confirmed-fresh means the walk completed, not that it found
    anything. A legitimately empty window must not look frozen."""
    service = _service(lambda t: [])
    service.start()
    try:
        observation = _wait_until(service.latest, what="an observation")
    finally:
        service.stop()

    assert observation is not None
    assert observation.ok is True
    assert observation.elements == ()


def test_a_raising_walker_does_not_kill_the_worker():
    """A transient perception error must not end perception for the run."""
    calls = {"n": 0}

    def walker(title_re):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return [EXPORT]

    service = _service(walker)
    service.start()
    try:
        observation = _wait_until(
            service.latest, what="an observation after transient failures"
        )
        alive = service.is_alive()
    finally:
        service.stop()

    assert observation is not None, "the worker gave up after a transient error"
    assert alive


def test_the_heartbeat_advances_even_while_every_walk_fails():
    """Distinguishes 'looping through failures' from 'blocked in a call'."""

    def walker(title_re):
        raise RuntimeError("always fails")

    service = _service(walker)
    service.start()
    try:
        beats = _wait_until(
            lambda: service.heartbeat >= 3 and service.heartbeat,
            what="three loop iterations",
        )
        assert service.latest() is None, "a failed walk must not publish"
    finally:
        service.stop()

    assert beats > 0


def test_stop_ends_the_worker_thread():
    service = _service(lambda t: [EXPORT])
    service.start()
    service.stop()
    assert not service.is_alive()


def test_restart_replaces_a_stopped_worker_and_counts_itself():
    service = _service(lambda t: [EXPORT])
    service.start()
    try:
        _wait_until(service.latest, what="an observation")
        service.stop()
        assert not service.is_alive()
        service.restart()
        assert service.is_alive()
        assert service.restarts == 1
    finally:
        service.stop()


def test_the_ui_thread_is_never_blocked_by_a_slow_walk():
    """The property this whole change exists for."""
    started = threading.Event()
    release = threading.Event()

    def slow_walker(title_re):
        started.set()
        # Blocks until the assertions are done, standing in for a UIA call
        # against a window that has stopped pumping messages. Released
        # explicitly rather than slept through, so the test cannot pass just
        # because a sleep outlasted the reads.
        release.wait(timeout=10)
        return [EXPORT]

    service = _service(slow_walker)
    service.start()
    try:
        assert started.wait(timeout=5)
        # The caller reads the slot repeatedly while the worker is stuck.
        t0 = time.perf_counter()
        for _ in range(50):
            service.latest()
        elapsed = time.perf_counter() - t0
    finally:
        release.set()
        service.stop()

    assert elapsed < 0.5, (
        f"50 slot reads took {elapsed:.2f}s while the worker was blocked — "
        "the UI thread is still coupled to perception"
    )
# ---------------------------------------------------------------------------
# The tier-2 request slot: the UI thread's ask, crossing the other way.
#
# These exist because the `grounded` round trip -- the longest piece of new
# plumbing across the boundary -- had no coverage at all: replacing
# `report_tier2_grounded` with a no-op left the whole suite green, so nothing
# guarded that a productive OCR read spares the step's fruitless-run budget
# (D028). The budget lives on the worker now, and this slot is the only way
# the UI thread can reach it.
# ---------------------------------------------------------------------------


class _RecordingTier2:
    """A tier-2 controller that records what the worker asked it to do."""

    max_runs_per_step = 20

    def __init__(self, elements=()):
        self.elements = list(elements)
        self.reads: list[int] = []
        self.grounded_calls: list[int] = []

    def elements_for(self, step_index, title_re):
        self.reads.append(step_index)
        return self.elements

    def grounded(self, step_index):
        self.grounded_calls.append(step_index)

    def engaged(self, step_index):
        return bool(self.reads)

    def exhausted(self, step_index):
        return False


def _tier2_service(controller):
    return PerceptionService(
        title_re=".*Whatever.*", walker=lambda t: [], tier2=controller
    )


def test_a_grounded_report_reaches_the_controller_for_the_step_it_names():
    controller = _RecordingTier2([EXPORT])
    service = _tier2_service(controller)

    service.request_tier2(7)
    service.report_tier2_grounded(7)
    service._tier2_payload()

    assert controller.grounded_calls == [7], (
        "a productive OCR read was never reported to the controller, so it "
        f"spent the step's fruitless-run budget anyway: {controller.grounded_calls}"
    )


def test_a_grounded_report_resets_the_fruitless_run_budget():
    """The property the round trip exists for, through the REAL controller.

    Asserted against `exhausted()` rather than a recorded call, because what
    matters is the budget, not the message: a tour whose amber ring is sitting
    correctly on an OCR target must not be killed by the cap meant for
    unproductive re-reading.
    """
    import numpy as np

    from ghostcursor.perception.tier2 import Tier2Controller

    ticks = {"t": 0.0}

    def clock():
        ticks["t"] += 10.0  # always past the 1.0s floor
        return ticks["t"]

    frames = {"n": 0}

    def capture(title_re):
        frames["n"] += 1
        # A different frame every time, so `frames_differ` never short-circuits
        # the read -- this test is about the budget, not change detection.
        return (np.full((4, 4, 3), frames["n"] % 251, dtype=np.uint8), (0, 0, 4, 4))

    class _Ocr:
        def read(self, frame):
            return []

    controller = Tier2Controller(
        ocr=_Ocr(), capture=capture, clock=clock, max_runs_per_step=3
    )
    service = PerceptionService(
        title_re=".*Whatever.*", walker=lambda t: [], tier2=controller
    )

    service.request_tier2(0)
    for _ in range(2):
        service._tier2_payload()
    assert not controller.exhausted(0)

    # A read that DID produce a usable target, reported the only way the UI
    # thread can: through the request slot.
    service.report_tier2_grounded(0)
    service._tier2_payload()

    for _ in range(2):
        service._tier2_payload()
    assert not controller.exhausted(0), (
        "the step exhausted its budget of 3 despite a productive read in the "
        "middle -- the grounded report never reset the count, so a correctly "
        "placed OCR hint is killed by the cap meant for fruitless re-reads"
    )


def test_the_grounded_flag_is_consumed_once_not_re_applied_every_iteration():
    controller = _RecordingTier2([EXPORT])
    service = _tier2_service(controller)

    service.request_tier2(3)
    service.report_tier2_grounded(3)
    service._tier2_payload()
    service._tier2_payload()
    service._tier2_payload()

    assert controller.grounded_calls == [3], (
        "one productive read reset the budget on every later worker iteration "
        f"-- the budget would never be spendable again: {controller.grounded_calls}"
    )


def test_a_grounded_report_for_a_step_that_is_not_the_standing_one_is_ignored():
    """It must be matched to the step, not merely to the slot.

    A late report from a step the tour has left would otherwise reset the
    CURRENT step's budget, silently uncapping the tier for a step that never
    read anything successfully.
    """
    controller = _RecordingTier2([EXPORT])
    service = _tier2_service(controller)

    service.request_tier2(4)
    service.report_tier2_grounded(1)  # the previous step, reporting late
    service._tier2_payload()

    assert controller.grounded_calls == [], (
        "a report from a step the tour had left reset the current step's "
        f"budget: {controller.grounded_calls}"
    )
    assert controller.reads == [4], (
        f"the late report also disturbed which step is read: {controller.reads}"
    )


def test_the_grounded_flag_survives_a_repeated_request_for_the_same_step():
    """The UI thread re-requests every ungrounded tick, which must not lose a
    report made between two of them -- that would spend the budget of exactly
    the productive reads it exists to spare."""
    controller = _RecordingTier2([EXPORT])
    service = _tier2_service(controller)

    service.request_tier2(2)
    service.report_tier2_grounded(2)
    service.request_tier2(2)
    service._tier2_payload()

    assert controller.grounded_calls == [2]


def test_a_new_step_starts_with_a_clean_grounded_flag():
    controller = _RecordingTier2([EXPORT])
    service = _tier2_service(controller)

    service.request_tier2(2)
    service.report_tier2_grounded(2)
    service.request_tier2(3)  # the tour moved on before the worker ran
    service._tier2_payload()

    assert controller.grounded_calls == [], (
        "step 2's productive read reset step 3's budget -- tier 2's stickiness "
        f"must reset at the step boundary (D028): {controller.grounded_calls}"
    )


def test_cancelling_stops_the_worker_reading_the_screen():
    """The blocker: nothing else ends a request.

    A standing request costs capture plus OCR (0.14-0.23s) as often as the
    1.0s floor allows, for as long as it stands. Left uncancelled it goes on
    delaying the UIA observations of whatever step the user is actually on.
    """
    controller = _RecordingTier2([EXPORT])
    service = _tier2_service(controller)

    service.request_tier2(0)
    service._tier2_payload()
    assert controller.reads == [0]

    service.cancel_tier2()
    for _ in range(5):
        assert service._tier2_payload() == ((), -1, False, False, 0)

    assert controller.reads == [0], (
        f"the worker kept reading the screen for a cancelled step: {controller.reads}"
    )


def test_cancelling_a_step_already_left_cannot_discard_the_current_request():
    controller = _RecordingTier2([EXPORT])
    service = _tier2_service(controller)

    service.request_tier2(5)
    service.cancel_tier2(4)  # the previous step, cancelling late
    service._tier2_payload()

    assert controller.reads == [5], (
        f"a late cancel from a step already left threw step 5's away: {controller.reads}"
    )


def test_a_failing_walk_does_not_suppress_tier_2():
    """Tier 2 needs a capture, not a tree walk.

    The two failed together once: `_tier2_payload` sat inside the walker's
    `try`, so a window that transiently vanished, or one COM hiccup, silently
    disabled OCR -- in precisely the situation OCR exists for. The UIA half
    still publishes nothing (the previous observation ages, which is what the
    staleness ladder is for); that is a separate decision.
    """

    def broken_walker(title_re):
        raise RuntimeError("the window went away")

    controller = _RecordingTier2([EXPORT])
    service = PerceptionService(
        title_re=".*Whatever.*",
        walker=broken_walker,
        interval_s=0.01,
        tier2=controller,
    )
    service.request_tier2(0)
    service.start()
    try:
        _wait_until(lambda: len(controller.reads) >= 3, what="tier 2 reading anyway")
    finally:
        service.stop()

    assert service.latest() is None, (
        "a failed walk published an observation -- the previous one must "
        "simply age instead"
    )
