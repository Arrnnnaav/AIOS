"""The worker accumulates which controls focus VISITED between observations.

Resting focus is not enough. The motivating case is a wrong click the user
corrects themselves, where focus has already moved on by the time the next
walk completes -- so the worker records what focus touched during the wait,
not where it ended up.
"""

import time

from ghostcursor.perception.service import PerceptionService


def _wait_for(service, predicate, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        observation = service.latest()
        if observation is not None and predicate(observation):
            return observation
        time.sleep(0.01)
    raise AssertionError("condition never held within the timeout")


def test_focus_visited_records_ids_seen_during_the_wait():
    """Focus moves to 'b' and back to 'a' between walks. Both must be
    recorded -- recording only the final value is exactly the miss this
    slicing exists to prevent."""
    sequence = iter(["a", "b", "a", "a", "a", "a", "a", "a"])

    def reader(_hwnd):
        try:
            return next(sequence)
        except StopIteration:
            return "a"

    service = PerceptionService(
        title_re=".*Target.*",
        walker=lambda _: [],
        hwnd_source=lambda _: 4242,
        focus_reader=reader,
        focus_slice_s=0.001,
        interval_s=0.05,
    )
    service.start()
    try:
        observation = _wait_for(service, lambda o: "b" in o.focus_visited)
    finally:
        service.stop()
    assert "b" in observation.focus_visited


def test_empty_ids_are_never_recorded():
    """'' means 'focus is somewhere we cannot name'. It must never enter the
    list, or the loop would compare against it and could report a wrong
    action it cannot describe.

    The wait predicate is load-bearing. An earlier version waited on
    `observed_at > 0`, which resolves on the FIRST observation -- and `_run`
    publishes BEFORE it samples (publish, then `visited.clear()`, then
    `_sample_focus_while_waiting`), so that first observation's
    `focus_visited` is always `()` no matter what the filter does: it is
    built from `visited` as it stood before any sampling for this interval
    happened. That version passed even with the empty-id filter deleted
    entirely (D031: a false green, an invariant that merely correlated with
    the property instead of implying it).

    This version waits for a SECOND, strictly-newer observation. That one's
    `focus_visited` is built from the wait that followed the first publish --
    a wait during which the reader was actually sampled -- so a leaked '' has
    somewhere to show up.
    """
    service = PerceptionService(
        title_re=".*Target.*",
        walker=lambda _: [],
        hwnd_source=lambda _: 4242,
        focus_reader=lambda _hwnd: "",
        focus_slice_s=0.001,
        interval_s=0.05,
    )
    service.start()
    try:
        first = _wait_for(service, lambda o: o.observed_at > 0)
        second = _wait_for(service, lambda o: o.observed_at > first.observed_at)
    finally:
        service.stop()
    assert second.focus_visited == ()


def test_focus_visited_is_capped_and_deduplicated():
    """A control cycling focus must not grow the payload without bound."""
    counter = iter(range(1000))
    service = PerceptionService(
        title_re=".*Target.*",
        walker=lambda _: [],
        hwnd_source=lambda _: 4242,
        focus_reader=lambda _hwnd: f"id{next(counter)}",
        focus_slice_s=0.001,
        interval_s=0.2,
    )
    service.start()
    try:
        observation = _wait_for(service, lambda o: len(o.focus_visited) > 0)
    finally:
        service.stop()
    assert len(observation.focus_visited) <= 8
    assert len(set(observation.focus_visited)) == len(observation.focus_visited)


def test_focus_visited_resets_between_observations():
    """Each observation describes the interval that produced it. Carrying ids
    forward would let one wrong click be reported on every later tick."""
    calls = {"n": 0}

    def reader(_hwnd):
        calls["n"] += 1
        return "early" if calls["n"] <= 2 else ""

    service = PerceptionService(
        title_re=".*Target.*",
        walker=lambda _: [],
        hwnd_source=lambda _: 4242,
        focus_reader=reader,
        focus_slice_s=0.001,
        interval_s=0.05,
    )
    service.start()
    try:
        _wait_for(service, lambda o: "early" in o.focus_visited)
        later = _wait_for(
            service,
            lambda o: o.focus_visited == () and calls["n"] > 10,
        )
    finally:
        service.stop()
    assert later.focus_visited == ()


def test_a_raising_focus_reader_does_not_kill_the_walk():
    """The walk is the product; focus is a nicety."""

    def boom(_hwnd):
        raise OSError("focus exploded")

    service = PerceptionService(
        title_re=".*Target.*",
        walker=lambda _: [],
        hwnd_source=lambda _: 4242,
        focus_reader=boom,
        focus_slice_s=0.001,
        interval_s=0.05,
    )
    service.start()
    try:
        observation = _wait_for(service, lambda o: o.ok)
    finally:
        service.stop()
    assert observation.ok is True
    assert observation.focus_visited == ()
