"""The pointer must end where the click lands, and get there followably.

Every case here is a way the drawn position could disagree with the acted
position, or a way the movement could become something the eye cannot track —
which under D109 is the same as showing nothing.
"""

from __future__ import annotations

import pytest

from ghostcursor.pointer_path import (
    Frame,
    PointerPathError,
    centre_of,
    ease_out,
    frame_count,
    schedule_for,
    traversal,
)

TARGET = (100, 200, 300, 260)  # left, top, right, bottom -> centre (200, 230)


# --- the endpoint is the control's centre, exactly -------------------------


def test_the_centre_is_computed_from_a_right_bottom_rectangle():
    """Observed rectangles are (left, top, right, bottom). Reading them as
    (left, top, width, height) would put the pointer somewhere plausible and
    wrong."""

    assert centre_of(TARGET) == (200, 230)


def test_the_last_frame_lands_exactly_on_the_centre():
    """Not a pixel beside it. The click is dispatched to that control while
    the pointer is displayed there."""

    frames = traversal((0, 0), TARGET, traversal_ms=400, frame_budget_ms=25)

    assert (frames[-1].x, frames[-1].y) == centre_of(TARGET)
    assert frames[-1].final is True


def test_the_last_frame_lands_on_the_centre_even_if_the_easing_undershoots(
    monkeypatch,
):
    """The snap is what makes the endpoint a guarantee rather than a
    coincidence of the current easing.

    Cubic ease-out happens to return exactly 1.0 at 1.0, so with it the
    computed last frame already sits on the centre and the snap is
    unreachable. Any future easing that stops fractionally short -- an
    overshoot-and-settle, a spring, a clamped table -- would leave the pointer
    a pixel off the control the click is dispatched to, which is the one thing
    D109 forbids.
    """

    monkeypatch.setattr(
        "ghostcursor.pointer_path.ease_out", lambda fraction: fraction * 0.97
    )

    frames = traversal((0, 0), TARGET, traversal_ms=400, frame_budget_ms=25)

    assert (frames[-1].x, frames[-1].y) == centre_of(TARGET)
    # ...and only the last one is corrected: the rest still show the real path.
    assert (frames[-2].x, frames[-2].y) != centre_of(TARGET)


def test_only_the_last_frame_is_final():
    frames = traversal((0, 0), TARGET, traversal_ms=400, frame_budget_ms=25)

    assert [f.final for f in frames] == [False] * (len(frames) - 1) + [True]


@pytest.mark.parametrize(
    "rectangle", [(10, 10, 10, 20), (10, 10, 20, 10), (30, 10, 10, 20)]
)
def test_a_degenerate_rectangle_has_no_centre_worth_pointing_at(rectangle):
    """It would place the pointer on an edge or outside the control."""

    with pytest.raises(PointerPathError, match="positive area"):
        centre_of(rectangle)


@pytest.mark.parametrize(
    "rectangle",
    [(1, 2, 3), (1, 2, 3, 4, 5), "1,2,3,4", (1.0, 2, 3, 4), (True, 2, 3, 4)],
)
def test_a_malformed_rectangle_is_refused(rectangle):
    with pytest.raises(PointerPathError):
        centre_of(rectangle)


# --- the movement is followable -------------------------------------------


def test_the_easing_slows_towards_the_destination():
    """The slow end is the point: the eye needs most time exactly where the
    pointer is coming to rest.

    The margin is not decoration. `early > late` alone passes for a LINEAR
    easing, because 0.2-0.1 is 0.1000000000000000055 and 1.0-0.9 is
    0.09999999999999998 — float noise, asserted as if it were a property.
    An order of magnitude is a difference the eye can see.
    """

    early = ease_out(0.2) - ease_out(0.1)
    late = ease_out(1.0) - ease_out(0.9)

    assert early > late * 10


@pytest.mark.parametrize("fraction", [-0.1, 1.1])
def test_easing_outside_the_unit_interval_is_refused(fraction):
    with pytest.raises(PointerPathError):
        ease_out(fraction)


def test_frames_advance_monotonically_in_time_and_toward_the_target():
    frames = traversal((0, 0), TARGET, traversal_ms=400, frame_budget_ms=25)

    assert [f.at_ms for f in frames] == sorted(f.at_ms for f in frames)
    assert [f.x for f in frames] == sorted(f.x for f in frames)


def test_the_first_cue_of_a_run_does_not_fly_in_from_nowhere():
    """A pointer arriving from an arbitrary corner would suggest it had been
    somewhere it was not."""

    frames = traversal(None, TARGET, traversal_ms=400, frame_budget_ms=25)

    assert frames == (Frame(200, 230, 0.0, True),)


def test_a_pointer_already_on_the_target_does_not_animate():
    """Moving zero distance over 400 ms reads as a freeze, not as motion."""

    frames = traversal((200, 230), TARGET, traversal_ms=400, frame_budget_ms=25)

    assert len(frames) == 1


# --- the frame count is derived from a measurement ------------------------


def test_the_frame_count_comes_from_the_measured_paint_cost():
    assert frame_count(400, 25) == 12  # ceiling
    assert frame_count(400, 50) == 8
    assert frame_count(400, 100) == 4


def test_the_frame_count_is_capped_so_a_fast_machine_does_not_burn_the_loop():
    assert frame_count(400, 1) == 12


def test_a_paint_slower_than_the_traversal_still_yields_one_frame():
    """One frame at the destination is honest; zero frames would mean the
    pointer never appeared before the click."""

    assert frame_count(400, 5000) == 1


@pytest.mark.parametrize("budget", [0, -1, True, 2.5])
def test_a_frame_budget_that_is_not_a_positive_integer_is_refused(budget):
    """There is no default: a plausible constant here is the placeholder that
    measurement exists to replace."""

    with pytest.raises(PointerPathError, match="positive integer"):
        frame_count(400, budget)


def test_the_frame_budget_has_no_default():
    import inspect

    parameters = inspect.signature(frame_count).parameters

    assert parameters["frame_budget_ms"].default is inspect.Parameter.empty


# --- the schedule keeps the user able to interrupt ------------------------


def test_the_settle_follows_the_last_frame():
    schedule = schedule_for(
        (0, 0), TARGET, traversal_ms=400, settle_ms=250, frame_budget_ms=25
    )

    assert schedule.settled_until_ms == pytest.approx(650.0)
    assert schedule.total_ms == pytest.approx(650.0)


def test_no_gap_between_polls_exceeds_the_interval():
    """The settle is the longest stretch with nothing else happening, and it
    is time in which Stop must still be noticed."""

    schedule = schedule_for(
        (0, 0), TARGET, traversal_ms=400, settle_ms=250, frame_budget_ms=25
    )
    points = schedule.poll_points()

    gaps = [b - a for a, b in zip(points, points[1:])]
    assert max(gaps) <= schedule.poll_interval_ms
    assert points[-1] == pytest.approx(schedule.settled_until_ms)


def test_a_paint_slower_than_the_poll_interval_refuses_geometry_outright():
    """If one paint outlasts the interval in which Stop must be noticed, then
    geometry is not affordable on this machine and the caller falls back to
    rail text rather than quietly missing the poll floor."""

    with pytest.raises(PointerPathError, match="cannot hold a 50ms poll"):
        schedule_for(
            (0, 0), TARGET, traversal_ms=400, settle_ms=250, frame_budget_ms=60
        )


def test_a_paint_exactly_at_the_poll_interval_is_allowed():
    schedule = schedule_for(
        (0, 0), TARGET, traversal_ms=400, settle_ms=250, frame_budget_ms=50
    )

    assert len(schedule.frames) == 8


@pytest.mark.parametrize("settle", [0, -1, True])
def test_a_non_positive_settle_is_refused(settle):
    """A cue with no settle is a flash: the label would not be readable
    before the click."""

    with pytest.raises(PointerPathError, match="settle_ms"):
        schedule_for(
            (0, 0), TARGET, traversal_ms=400, settle_ms=settle, frame_budget_ms=25
        )


def test_a_first_cue_still_settles_even_though_it_does_not_travel():
    schedule = schedule_for(
        None, TARGET, traversal_ms=400, settle_ms=250, frame_budget_ms=25
    )

    assert len(schedule.frames) == 1
    assert schedule.settled_until_ms == pytest.approx(250.0)
