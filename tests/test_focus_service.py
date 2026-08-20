"""The worker accumulates which controls focus VISITED between observations.

Resting focus is not enough. The motivating case is a wrong click the user
corrects themselves, where focus has already moved on by the time the next
walk completes -- so the worker records what focus touched during the wait,
not where it ended up.
"""

import time

from ghostcursor.perception.service import MAX_FOCUS_VISITED, PerceptionService


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


def test_focus_visited_is_capped():
    """A control cycling focus must not grow the payload without bound.

    Split out of what used to be test_focus_visited_is_capped_and_deduplicated.
    That combined test's dedup assertion was vacuous (D031): its reader
    (f"id{next(counter)}") never returns the same id twice, so
    len(set(x)) == len(x) held no matter what the dedup guard did. Confirmed
    by deleting `focused not in visited` and keeping the cap: the combined
    test stayed green. This test keeps ONLY the ever-fresh-id reader, so
    only the cap can be the thing stopping growth.
    """
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
    assert len(observation.focus_visited) <= MAX_FOCUS_VISITED


def test_focus_visited_deduplicates():
    """The SAME control keeping focus across many slices must appear once.

    Split out of what used to be test_focus_visited_is_capped_and_deduplicated
    (see that history on test_focus_visited_is_capped). An id-per-call reader
    makes dedup untestable -- there is never a duplicate to deduplicate -- so
    this reader deliberately repeats the same id on every call instead.

    The wait predicate matters for the same reason it did in
    test_empty_ids_are_never_recorded: `_run` publishes BEFORE it samples, so
    the FIRST observation's focus_visited is always built from an empty
    `visited` and would pass trivially regardless of the dedup guard. Waiting
    for a second, strictly-newer observation forces the assertion onto one
    whose focus_visited was actually built from a wait the reader was sampled
    during.
    """
    service = PerceptionService(
        title_re=".*Target.*",
        walker=lambda _: [],
        hwnd_source=lambda _: 4242,
        focus_reader=lambda _hwnd: "1001",
        focus_slice_s=0.001,
        interval_s=0.05,
    )
    service.start()
    try:
        first = _wait_for(service, lambda o: o.observed_at > 0)
        second = _wait_for(service, lambda o: o.observed_at > first.observed_at)
    finally:
        service.stop()
    assert second.focus_visited == ("1001",)


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


def test_focus_visited_survives_a_failed_walk():
    """An id visited during the interval before a failed walk must still
    reach the next SUCCESSFUL observation -- not be silently discarded by
    the failed walk in between.

    `Observation.focus_visited`'s own docstring (and design spec section
    3.2) define the contract as "since the previous observation". An
    earlier version cleared `visited` unconditionally on every loop
    iteration, whether or not a walk succeeded. That discards ids the
    instant a walk fails, even though nothing was published to carry them
    -- so a user's wrong click during a failed-walk interval was invisible
    to consumers forever, silently violating the documented contract.

    Three walks are needed to expose this, not two: walk #1 succeeds (and
    publishes an empty focus_visited, since nothing has been sampled yet);
    "wrongclick" is sampled during walk #1's wait; walk #2 FAILS, so
    nothing is published this round and, under the bug, the unconditional
    clear wipes "wrongclick" before it ever reaches an Observation; walk #3
    succeeds and publishes. Under the fix, the clear only ever runs
    alongside a successful publish, so "wrongclick" survives walk #2's
    failure intact and shows up in walk #3's observation.
    """
    walk_calls = {"n": 0}

    def walker(_):
        walk_calls["n"] += 1
        if walk_calls["n"] == 2:
            raise RuntimeError("walk failed")
        return []

    # "" covers every walk-start sample; "wrongclick" is consumed exactly
    # once, during walk #1's post-walk wait.
    focus_sequence = iter(["", "wrongclick"])

    def reader(_hwnd):
        try:
            return next(focus_sequence)
        except StopIteration:
            return ""

    service = PerceptionService(
        title_re=".*Target.*",
        walker=walker,
        hwnd_source=lambda _: 4242,
        focus_reader=reader,
        focus_slice_s=0.001,
        interval_s=0.05,
    )
    service.start()
    try:
        first = _wait_for(service, lambda o: o.observed_at > 0)
        second = _wait_for(service, lambda o: o.observed_at > first.observed_at)
    finally:
        service.stop()
    assert "wrongclick" in second.focus_visited


def test_focused_automation_id_reaches_the_snapshot():
    """`take_snapshot`'s new `focused_automation_id` parameter must actually
    be wired to what the worker read, not left at its default.

    Reverting `focused_automation_id=focused_now` in `_run` back to the old
    hardcoded `""` leaves every other test in this file green -- nothing
    else in the suite asserts on `Snapshot.focused_automation_id` coming out
    of a real worker. This is the wiring's only guard.
    """
    service = PerceptionService(
        title_re=".*Target.*",
        walker=lambda _: [],
        hwnd_source=lambda _: 4242,
        focus_reader=lambda _hwnd: "1001",
        focus_slice_s=0.001,
        interval_s=0.05,
    )
    service.start()
    try:
        observation = _wait_for(service, lambda o: o.observed_at > 0)
    finally:
        service.stop()
    assert observation.snapshot.focused_automation_id == "1001"
