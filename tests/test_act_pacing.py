"""Going slower must make a run MORE stoppable, not less.

Watch Build exists so a person can follow a 255-node build. The failure it
invites is a plain `sleep` between nodes — which would put the run inside an
uninterruptible call for tenths of a second at a time while D020 allows half
a second for the whole abort path. Every case here is a way the waiting could
swallow a Stop.

Ordered-sequence on an injected clock (D026): what matters is when the
interrupt was read relative to the waiting, never the state at the end.
"""

from __future__ import annotations

import pytest

from ghostcursor.act_pacing import (
    PACES,
    POLL_INTERVAL_MS,
    QUICK,
    WATCH,
    Pace,
    PacingError,
    interruptible_wait,
    pace_by_name,
)


class Clock:
    """A clock the sleeps advance, so a paced run costs no real time."""

    def __init__(self):
        self.now = 0.0
        self.log: list[tuple[str, float]] = []

    def read(self) -> float:
        return self.now

    def sleep(self, milliseconds: float) -> None:
        self.log.append(("sleep", milliseconds))
        self.now += milliseconds


def _poller(stop_after: int | None = None, log: list | None = None):
    """A poll that stops after N calls, recording when each read happened."""

    calls = {"n": 0}

    def poll() -> bool:
        calls["n"] += 1
        if log is not None:
            log.append(("poll", calls["n"]))
        return stop_after is None or calls["n"] <= stop_after

    poll.calls = calls  # type: ignore[attr-defined]
    return poll


# --- the wait is sliced, and every slice reads the interrupt --------------


def test_no_slice_of_a_wait_exceeds_the_poll_interval():
    """The property Watch Build depends on. A 400ms pause taken in one call
    is 400ms in which Stop cannot be noticed, against D020's 0.5s for the
    whole abort path."""

    clock = Clock()

    interruptible_wait(400, poll=_poller(), clock=clock.read, sleep=clock.sleep)

    slices = [ms for kind, ms in clock.log if kind == "sleep"]
    assert max(slices) <= POLL_INTERVAL_MS
    assert sum(slices) == pytest.approx(400.0)


def test_a_long_wait_reads_the_interrupt_many_times():
    clock = Clock()
    poll = _poller()

    interruptible_wait(400, poll=poll, clock=clock.read, sleep=clock.sleep)

    assert poll.calls["n"] >= 400 // POLL_INTERVAL_MS


def test_a_stop_ends_the_wait_without_finishing_it():
    clock = Clock()

    finished = interruptible_wait(
        1000, poll=_poller(stop_after=2), clock=clock.read, sleep=clock.sleep
    )

    assert finished is False
    assert clock.now < 1000  # it did not sit out the rest of the pause


def test_the_interrupt_is_read_before_the_deadline_is_checked():
    """A zero-length wait still reads Stop once. Otherwise Quick Build, whose
    every wait is zero, would never check between nodes at all -- and the
    pacing setting would silently decide whether the run was interruptible."""

    clock = Clock()
    poll = _poller()

    assert interruptible_wait(0, poll=poll, clock=clock.read, sleep=clock.sleep)

    assert poll.calls["n"] == 1
    assert clock.log == []


def test_a_stop_on_a_zero_length_wait_is_honoured():
    clock = Clock()

    finished = interruptible_wait(
        0, poll=_poller(stop_after=0), clock=clock.read, sleep=clock.sleep
    )

    assert finished is False


def test_polls_and_sleeps_alternate():
    """Ordered sequence, not a count: two sleeps in a row is a gap twice the
    interval however many polls happened overall."""

    clock = Clock()
    log: list = []

    def sleep(ms):
        log.append(("sleep", ms))
        clock.sleep(ms)

    interruptible_wait(150, poll=_poller(log=log), clock=clock.read, sleep=sleep)

    kinds = [kind for kind, _ in log]
    assert kinds == ["poll", "sleep", "poll", "sleep", "poll", "sleep", "poll"]


def test_the_last_slice_does_not_overshoot_the_deadline():
    """A 120ms wait must not sleep 50+50+50. Overshoot is not a safety
    problem but it makes a paced run drift, and 255 nodes of drift is
    visible."""

    clock = Clock()

    interruptible_wait(120, poll=_poller(), clock=clock.read, sleep=clock.sleep)

    assert clock.now == pytest.approx(120.0)


def test_a_shorter_interval_polls_more_often():
    clock = Clock()
    poll = _poller()

    interruptible_wait(
        200, poll=poll, clock=clock.read, sleep=clock.sleep, interval_ms=10
    )

    assert poll.calls["n"] >= 20


@pytest.mark.parametrize("duration", [-1, 1.5, True, "400", None])
def test_a_malformed_duration_is_refused(duration):
    clock = Clock()

    with pytest.raises(PacingError, match="duration_ms"):
        interruptible_wait(
            duration, poll=_poller(), clock=clock.read, sleep=clock.sleep
        )


@pytest.mark.parametrize("interval", [0, -5, True, 2.5])
def test_a_malformed_interval_is_refused(interval):
    """An interval of zero would spin without ever sleeping; a negative one
    would make the slice longer than the wait."""

    clock = Clock()

    with pytest.raises(PacingError, match="interval_ms"):
        interruptible_wait(
            100,
            poll=_poller(),
            clock=clock.read,
            sleep=clock.sleep,
            interval_ms=interval,
        )


# --- the two modes --------------------------------------------------------


def test_quick_build_waits_for_nothing():
    assert QUICK.total_ms == 0
    assert QUICK.waits is False


def test_watch_build_waits_before_and_after_each_node():
    """Before, so the step can be read; after, so the change registers. A
    change that appears and is immediately replaced reads as a flicker rather
    than as an action."""

    assert WATCH.before_node_ms > 0
    assert WATCH.after_node_ms > 0
    assert WATCH.waits is True


def test_the_pace_interval_matches_the_presenters():
    """Two promises about how soon a Stop is noticed. Letting them differ
    would make the answer depend on which part of a node it was pressed in."""

    from ghostcursor.act_presenter import schedule_for

    schedule = schedule_for(
        (0, 0), (10, 10, 60, 40), traversal_ms=100, settle_ms=100, frame_budget_ms=2
    )

    assert schedule.poll_interval_ms == POLL_INTERVAL_MS


def test_a_pace_can_be_named_on_a_command_line():
    assert pace_by_name("quick") is QUICK
    assert pace_by_name("watch") is WATCH
    assert set(PACES) == {"quick", "watch"}


def test_an_unknown_pace_is_refused_and_names_the_known_ones():
    with pytest.raises(PacingError, match="known paces are"):
        pace_by_name("cinematic")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": ""},
        {"name": "   "},
        {"before_node_ms": -1},
        {"after_node_ms": True},
        {"before_node_ms": 1.5},
    ],
)
def test_a_malformed_pace_is_refused(kwargs):
    fields = {"name": "watch", "before_node_ms": 10, "after_node_ms": 10}
    fields.update(kwargs)

    with pytest.raises(PacingError):
        Pace(**fields)


def test_a_pace_is_frozen():
    with pytest.raises(Exception):
        WATCH.before_node_ms = 5


def test_watch_build_adds_a_bounded_amount_to_the_deck_build():
    """255 nodes at WATCH is roughly two and a half minutes of added pacing on
    top of a 65-second build. Asserted so a later change that made Watch Build
    unusably slow fails here rather than in front of someone."""

    added_s = 255 * WATCH.total_ms / 1000.0

    assert 60.0 <= added_s <= 240.0
