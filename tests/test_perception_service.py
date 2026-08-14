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
