"""The overlay must be able to say "this hint is unconfirmed".

Colour, not disappearance: the user keeps their guidance while being told it
may no longer be current.
"""

from ghostcursor.overlay import window as ov
from ghostcursor.reasoning.staleness import Freshness


def test_a_dimmed_hint_uses_a_different_colour_from_a_fresh_one():
    assert ov.DIMMED_RING_COLOR != ov.RING_COLOR


def test_set_hint_records_the_requested_freshness():
    ov._hint = None
    hwnd = ov.create_overlay_window()
    try:
        ov.set_hint(hwnd, 300, 300, freshness=Freshness.DIMMED)
        assert ov._hint is not None
        assert ov._hint[3] is Freshness.DIMMED
        ov.set_hint(hwnd, 300, 300)
        assert ov._hint[3] is Freshness.FRESH, "freshness must default to FRESH"
    finally:
        ov.destroy_overlay_window(hwnd)


def test_hiding_clears_the_hint_entirely():
    hwnd = ov.create_overlay_window()
    try:
        ov.set_hint(hwnd, 300, 300)
        ov.clear_hint(hwnd)
        assert ov._hint is None
    finally:
        ov.destroy_overlay_window(hwnd)
