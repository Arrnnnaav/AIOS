"""A cue must point at the control and not hide it.

Every case here is a way the drawn cue could say something untrue: a tip
somewhere other than where the click lands, a label over the button it names,
a label off the edge of the screen, or a colour that renders as a hole.
"""

from __future__ import annotations

import pytest

from ghostcursor.act_protocol import Backend, LifecycleState, TrustClass, trust_for
from ghostcursor.overlay.cue import (
    COLORKEY_RGB,
    TRUST_COLOURS,
    CueLayoutError,
    CueScene,
    LabelMetrics,
    cue_colour,
    label_box,
    pointer_polygon,
)

SCREEN = (0, 0, 1920, 1080)
METRICS = LabelMetrics(char_width=8, line_height=16, padding=6, gap=14)


# --- the tip is the contract (D109) ---------------------------------------


def test_the_glyph_tip_sits_exactly_on_the_point_it_is_given():
    """Not the glyph's centre, and not its bounding box. The tip is where the
    click is dispatched, so it is the only part of the shape that is a
    promise."""

    points = pointer_polygon(640, 480)

    assert points[0] == (640, 480)


def test_the_rest_of_the_glyph_hangs_below_and_right_of_the_tip():
    """A cursor drawn up-and-left of its own tip would cover the control it is
    pointing at."""

    points = pointer_polygon(640, 480)

    assert all(x >= 640 and y >= 480 for x, y in points)


def test_scaling_moves_the_body_and_never_the_tip():
    small = pointer_polygon(100, 100, scale=1)
    large = pointer_polygon(100, 100, scale=3)

    assert small[0] == large[0] == (100, 100)
    assert large[1] != small[1]


@pytest.mark.parametrize("scale", [0, -1, True, 1.5])
def test_a_glyph_scale_that_is_not_a_positive_integer_is_refused(scale):
    with pytest.raises(CueLayoutError, match="scale"):
        pointer_polygon(100, 100, scale=scale)


@pytest.mark.parametrize("point", [(1.0, 2), (True, 2)])
def test_a_non_integer_tip_is_refused(point):
    with pytest.raises(CueLayoutError):
        pointer_polygon(*point)


# --- colour is earned, and has to render ----------------------------------


def test_no_trust_colour_is_the_overlay_colorkey():
    """The colorkey is punched out of the window. A cue painted in it is not a
    dim cue -- it is a hole, and the user sees nothing at all.

    This is a near miss, not a hypothetical: the natural colour for the legacy
    backend is magenta, and the colorkey IS magenta.
    """

    assert COLORKEY_RGB not in TRUST_COLOURS.values()


def test_every_trust_class_has_a_colour():
    """A class with no colour is a node that cannot be drawn at all."""

    assert set(TRUST_COLOURS) == set(TrustClass)


def test_each_trust_class_is_visually_distinct():
    """Two classes sharing a colour is worse than one having none: the user
    believes they can tell them apart."""

    assert len(set(TRUST_COLOURS.values())) == len(TRUST_COLOURS)


def test_an_unproven_node_is_never_drawn_in_a_verified_colour():
    """The colour comes from `trust_for`, which collapses every unproven state
    to NEUTRAL -- including VERIFYING, where the effect has happened and its
    result is not yet known."""

    executing = cue_colour(trust_for(Backend.UIA_PATTERN, LifecycleState.EXECUTING))
    verifying = cue_colour(trust_for(Backend.UIA_PATTERN, LifecycleState.VERIFYING))
    verified = cue_colour(trust_for(Backend.UIA_PATTERN, LifecycleState.VERIFIED))

    assert executing == verifying == TRUST_COLOURS[TrustClass.NEUTRAL]
    assert verified == TRUST_COLOURS[TrustClass.LIVE_STATE]
    assert verified != executing


def test_a_uia_action_is_not_drawn_in_the_object_model_colour():
    """Reading the saved file and reading live UI state are different
    evidence, and D109 says they never share a colour."""

    artifact = cue_colour(trust_for(Backend.OBJECT_MODEL, LifecycleState.VERIFIED))
    live = cue_colour(trust_for(Backend.UIA_PATTERN, LifecycleState.VERIFIED))
    legacy = cue_colour(trust_for(Backend.LEGACY_IACCESSIBLE, LifecycleState.VERIFIED))

    assert len({artifact, live, legacy}) == 3


def test_a_colour_cannot_be_asked_for_by_anything_but_a_trust_class():
    with pytest.raises(CueLayoutError, match="TrustClass"):
        cue_colour("live_state")


# --- the label does not hide what it names --------------------------------


def test_the_label_sits_below_and_right_of_the_tip_by_default():
    """Where a real tooltip goes, so where the eye already is."""

    box = label_box((400, 300), "New Slide", METRICS, bounds=SCREEN)

    assert box[0] > 400 and box[1] > 300


def test_the_label_width_follows_the_measured_character_width():
    """Guessing it is how a label that "fits" clips its last word on the
    machine that matters."""

    short = label_box((400, 300), "New", METRICS, bounds=SCREEN)
    long = label_box((400, 300), "New Slide Layout", METRICS, bounds=SCREEN)

    assert long[2] - long[0] > short[2] - short[0]
    assert short[2] - short[0] == len("New") * 8 + 12


def test_the_label_flips_left_rather_than_running_off_the_right_edge():
    box = label_box((1900, 300), "New Slide", METRICS, bounds=SCREEN)

    assert box[2] <= SCREEN[2]
    assert box[0] < 1900


def test_the_label_flips_above_rather_than_running_off_the_bottom_edge():
    box = label_box((400, 1070), "New Slide", METRICS, bounds=SCREEN)

    assert box[3] <= SCREEN[3]
    assert box[1] < 1070


def test_a_corner_flips_both_ways_at_once():
    box = label_box((1900, 1070), "New Slide", METRICS, bounds=SCREEN)

    assert box[0] >= 0 and box[1] >= 0
    assert box[2] <= 1920 and box[3] <= 1080


def test_the_label_moves_off_the_control_it_is_naming():
    """A label over its own target is worse than no label: it names something
    it has just hidden."""

    target = (400, 300, 700, 400)
    box = label_box((410, 310), "New Slide", METRICS, bounds=SCREEN, avoid=target)

    assert not (
        box[0] < target[2]
        and target[0] < box[2]
        and box[1] < target[3]
        and target[1] < box[3]
    )


def test_a_label_touching_the_target_edge_is_not_an_overlap():
    """Sharing an edge covers no pixel. Treating it as a collision would push
    the label away from the control for nothing.

    The geometry is fussy on purpose. A simpler case cannot tell the two
    behaviours apart: if every candidate is judged to collide, the function
    falls back to the first in-bounds one, which is often the same box a
    correct run would have returned. Here the first in-bounds candidate
    (below-left) genuinely overlaps and the third (above-left) only touches
    the target's top edge, so a strict test returns the touching box and an
    inclusive one returns the overlapping fallback.
    """

    metrics = LabelMetrics(char_width=8, line_height=16, padding=6, gap=0)
    bounds = (0, 0, 220, 200)
    target = (150, 100, 210, 160)

    box = label_box((200, 100), "Hi", metrics, bounds=bounds, avoid=target)

    assert box == (172, 72, 200, 100)  # sitting ON the target's top edge


def test_a_label_that_can_only_overlap_still_appears():
    """When the target fills the screen there is nowhere clear to put it.
    Dropping the text would leave a pointer with no explanation; a partly
    covered button beside readable words is the better failure."""

    box = label_box((900, 500), "New Slide", METRICS, bounds=SCREEN, avoid=SCREEN)

    assert box[2] - box[0] > 0
    assert box[0] >= 0 and box[2] <= 1920


def test_a_label_wider_than_the_screen_starts_at_the_edge_not_off_it():
    """A tiny screen has no in-bounds candidate at all, and the label is wider
    than the whole thing. Anchoring left means the START of the text is
    readable; clamping the other way put it at x=-20, where the first three
    characters are simply gone."""

    tiny = (0, 0, 120, 60)
    box = label_box((100, 50), "New Slide Layout", METRICS, bounds=tiny)

    assert box[0] == 0
    # The height still fits, so that axis is clamped normally rather than
    # anchored: 28px of label inside 60px of screen, pulled up off the edge.
    assert box[3] == 60


def test_a_label_that_fits_but_lands_late_is_pulled_back_inside():
    """Distinct from the case above: here the box FITS, it is only the
    position that is wrong, so clamping must move it fully inside rather than
    anchoring at the edge."""

    small = (0, 0, 400, 300)
    box = label_box((390, 290), "Hi", METRICS, bounds=small)

    assert box[2] <= 400 and box[3] <= 300
    assert box[0] > 0 and box[1] > 0


@pytest.mark.parametrize("text", ["", "   ", None, 7])
def test_a_label_with_no_text_is_refused(text):
    with pytest.raises(CueLayoutError, match="text"):
        label_box((400, 300), text, METRICS, bounds=SCREEN)


def test_label_metrics_must_be_measured_not_improvised():
    with pytest.raises(CueLayoutError, match="LabelMetrics"):
        label_box((400, 300), "New Slide", (8, 16), bounds=SCREEN)


@pytest.mark.parametrize("field", ["char_width", "line_height"])
def test_a_zero_text_dimension_is_refused(field):
    """A zero character width makes every label the same size as the padding,
    so nothing ever overflows and nothing ever flips."""

    values = {"char_width": 8, "line_height": 16}
    values[field] = 0

    with pytest.raises(CueLayoutError, match=field):
        LabelMetrics(**values)


@pytest.mark.parametrize("bounds", [(0, 0, 0, 100), (0, 0, 100), "screen"])
def test_degenerate_bounds_are_refused(bounds):
    with pytest.raises(CueLayoutError, match="bounds"):
        label_box((400, 300), "New Slide", METRICS, bounds=bounds)


# --- the scene that crosses to the UI thread ------------------------------


def test_a_scene_carries_its_colour_from_its_trust_class():
    scene = CueScene((10, 20), (0, 0, 40, 40), "New Slide", TrustClass.NEUTRAL, False)

    assert scene.colour == TRUST_COLOURS[TrustClass.NEUTRAL]


def test_a_scene_is_frozen():
    """It crosses from the worker that decided the cue to the UI thread that
    paints it. A mutable scene could be edited in between."""

    scene = CueScene((10, 20), None, "New Slide", TrustClass.NEUTRAL, False)

    with pytest.raises(Exception):
        scene.pointer = (0, 0)


def test_a_scene_showing_nothing_is_refused():
    """No pointer and no target is a paint that draws only the colorkey, which
    the user experiences as the cue never appearing."""

    with pytest.raises(CueLayoutError, match="shows nothing"):
        CueScene(None, None, "New Slide", TrustClass.NEUTRAL, False)


def test_a_target_only_scene_is_allowed():
    """Rail-adjacent: a ring with no ghost pointer is still an honest cue."""

    scene = CueScene(None, (0, 0, 40, 40), "New Slide", TrustClass.NEUTRAL, False)

    assert scene.pointer is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"label": ""},
        {"trust": "live_state"},
        {"final": "yes"},
        {"pointer": (1.0, 2)},
        {"target": (0, 0, 0, 40)},
    ],
)
def test_a_malformed_scene_is_refused(kwargs):
    fields = {
        "pointer": (10, 20),
        "target": (0, 0, 40, 40),
        "label": "New Slide",
        "trust": TrustClass.NEUTRAL,
        "final": False,
    }
    fields.update(kwargs)

    with pytest.raises(CueLayoutError):
        CueScene(**fields)


def test_pulse_delta_breathes_within_bounds():
    """The hint ring's radius delta is 0 at the cycle start, peaks at the half
    cycle, and never leaves [0, amplitude] -- so the halo pulses without ever
    shrinking below its base or blooming onto a neighbour."""
    from ghostcursor.overlay.cue import PULSE_AMPLITUDE_PX, PULSE_PERIOD_S, pulse_delta

    assert pulse_delta(0.0) == 0
    assert pulse_delta(PULSE_PERIOD_S) == 0  # full cycle returns to base
    assert pulse_delta(PULSE_PERIOD_S / 2) == PULSE_AMPLITUDE_PX  # peak
    for i in range(240):  # two cycles, fine-grained: always in range
        d = pulse_delta(i * PULSE_PERIOD_S / 100)
        assert 0 <= d <= PULSE_AMPLITUDE_PX
    assert pulse_delta(5.0, period=0) == 0  # degenerate period never divides
