"""The Teach ring flies from the user's cursor to the control (HeyClicky's
spring flight) and always lands exactly on the observed control (rule 3)."""

from ghostcursor.overlay.cue import FLY_S, fly_position


def test_flight_starts_at_the_cursor_and_lands_exactly_on_the_control():
    start, end = (0, 0), (1000, 400)
    assert fly_position(start, end, 0.0) == start
    assert fly_position(start, end, FLY_S) == end
    assert fly_position(start, end, FLY_S * 5) == end
    assert fly_position(start, end, -1.0) == start


def test_flight_moves_forward_and_overshoots_only_a_little():
    start, end = (0, 0), (1000, 0)
    xs = [fly_position(start, end, FLY_S * i / 20)[0] for i in range(21)]
    assert xs[5] > 300  # ease-out: most of the way early
    assert max(xs) <= 1000 * 1.1  # a spring's small overshoot, never wild
    assert xs[-1] == 1000
