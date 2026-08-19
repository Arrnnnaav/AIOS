"""The third ring state must be distinguishable from the other two."""

from ghostcursor.overlay import window as ov
from ghostcursor.reasoning.staleness import Freshness


def _rgb(colorref):
    return (colorref & 0xFF, (colorref >> 8) & 0xFF, (colorref >> 16) & 0xFF)


def test_three_distinct_ring_colours_exist():
    colours = {ov.RING_COLOR, ov.DIMMED_RING_COLOR, ov.INFERRED_RING_COLOR}
    assert len(colours) == 3


def test_inferred_is_not_merely_a_shade_of_the_others():
    """It signals a different KIND of doubt, so it must not read as 'dim'."""
    inferred, fresh, dimmed = (
        _rgb(ov.INFERRED_RING_COLOR),
        _rgb(ov.RING_COLOR),
        _rgb(ov.DIMMED_RING_COLOR),
    )
    assert sum(abs(a - b) for a, b in zip(inferred, fresh)) > 90
    assert sum(abs(a - b) for a, b in zip(inferred, dimmed)) > 90


def test_the_painter_picks_a_colour_for_every_drawable_state():
    for state in (Freshness.FRESH, Freshness.DIMMED, Freshness.INFERRED):
        assert ov.ring_colour_for(state) in (
            ov.RING_COLOR,
            ov.DIMMED_RING_COLOR,
            ov.INFERRED_RING_COLOR,
        )
    assert ov.ring_colour_for(Freshness.FRESH) == ov.RING_COLOR
    assert ov.ring_colour_for(Freshness.INFERRED) == ov.INFERRED_RING_COLOR
    assert ov.ring_colour_for(Freshness.DIMMED) == ov.DIMMED_RING_COLOR
