"""End-to-end: recipe -> ground -> hint on screen -> user acts -> verify."""

from pathlib import Path

import mss
import numpy as np

from ghostcursor.overlay import dpi
from ghostcursor.overlay import window as ov
from ghostcursor.perception.uia import iter_elements
from ghostcursor.reasoning import grounding
from ghostcursor.reasoning.loop import GuidedTour, State
from ghostcursor.reasoning.renderer import OverlayRenderer
from ghostcursor.reasoning.schema import Recipe
from ghostcursor.reasoning.staleness import Freshness
from ghostcursor.reasoning.verification import take_snapshot, verify
from tests.uia_app import BTN_EXPORT, SyntheticApp

RECIPE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ghostcursor"
    / "reasoning"
    / "recipes"
    / "synthetic_export.json"
)

#: Half-width of the crop searched for ring pixels, in screen pixels. The
#: whole desktop can contain unrelated cyan pixels (terminal text, syntax
#: highlighting) that corrupt a whole-screen centroid, so the search is
#: restricted to a box around the grounded target's expected centre.
_CROP_MARGIN = 60


def _ring_pixels_near(cx: int, cy: int, margin: int = _CROP_MARGIN):
    """Find hint-ring pixels within a crop around (cx, cy), in screen coords.

    Returns an (N, 2) array of (screen_y, screen_x) pairs.
    """
    with mss.MSS() as sct:
        frame = np.array(sct.grab(dpi.capture_region()))[:, :, :3]
    origin_left, origin_top, _, _ = dpi.virtual_screen_rect()

    # Crop coordinates are relative to the captured frame, which starts at
    # (origin_left, origin_top) in screen space.
    left = max(0, (cx - origin_left) - margin)
    top = max(0, (cy - origin_top) - margin)
    right = min(frame.shape[1], (cx - origin_left) + margin)
    bottom = min(frame.shape[0], (cy - origin_top) + margin)

    crop = frame[top:bottom, left:right]
    b, g, r = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    local = np.argwhere((r < 80) & (g > 150) & (b > 190))
    if len(local) == 0:
        return local
    # Convert back to screen coordinates: local (row, col) -> screen (y, x).
    screen = local + np.array([top + origin_top, left + origin_left])
    return screen


def test_recipe_file_is_valid():
    recipe = Recipe.load(RECIPE_PATH)
    from ghostcursor.reasoning.schema import validate_step

    assert recipe.steps, "recipe has no steps"
    for i, step in enumerate(recipe.steps):
        assert validate_step(step) == [], f"step {i} invalid"


def test_tour_grounds_renders_and_verifies_against_a_real_window():
    recipe = Recipe.load(RECIPE_PATH)

    with SyntheticApp() as app:
        title_re = f".*{app.title}.*"
        hwnd = ov.create_overlay_window()
        try:
            # The target is a UIA-confirmed control, so the confirmed-control
            # display state is the factually correct one to declare here.
            # OverlayRenderer requires it to be declared (D027).
            renderer = OverlayRenderer(hwnd, freshness_source=lambda: Freshness.FRESH)
            tour = GuidedTour(
                recipe=recipe,
                grounder=lambda step, i, elements=None: grounding.ground(
                    step, title_re
                ),
                snapshotter=lambda: take_snapshot(title_re),
                verifier=verify,
                renderer=renderer,
            )

            for _ in range(4):
                tour.tick()
                app.pump()
            assert tour.state is State.AWAITING_USER_ACTION

            # the hint must be on screen, over the Export button. Search only
            # a crop around the button's own bbox centre to avoid unrelated
            # cyan pixels elsewhere on the desktop (see task-9 brief).
            elements = {e.automation_id: e for e in iter_elements(title_re)}
            btn = elements[str(BTN_EXPORT)]
            expected_cx = (btn.bbox[0] + btn.bbox[2]) // 2
            expected_cy = (btn.bbox[1] + btn.bbox[3]) // 2

            ring = _ring_pixels_near(expected_cx, expected_cy)
            assert len(ring) > 50, "no hint ring rendered"

            cy, cx = ring[:, 0].mean(), ring[:, 1].mean()
            assert btn.bbox[0] <= cx <= btn.bbox[2]
            assert btn.bbox[1] <= cy <= btn.bbox[3]

            # ring diameter should be roughly 49px across for radius 24.
            span_x = ring[:, 1].max() - ring[:, 1].min()
            span_y = ring[:, 0].max() - ring[:, 0].min()
            assert 30 <= span_x <= 70, f"ring x-span {span_x} out of range"
            assert 30 <= span_y <= 70, f"ring y-span {span_y} out of range"

            # the user acts: the app's status label changes
            # Match the recipe's real synthetic-demo postcondition. The
            # generic UIA fixture's click helper intentionally emits only a
            # control-id diagnostic, not application-specific export state.
            app.set_status("Export finished: table.csv")
            app.pump()

            for _ in range(3):
                tour.tick()
                app.pump()
            assert tour.step_index == 1
        finally:
            ov.destroy_overlay_window(hwnd)


def test_promotion_persists_after_a_successful_grounding():
    recipe = Recipe.load(RECIPE_PATH)
    step = recipe.steps[0]
    assert step.target_descriptor.confirmed == []

    with SyntheticApp() as app:
        title_re = f".*{app.title}.*"
        grounded = grounding.ground(step, title_re)
        assert grounded is not None
        grounding.promote(step, grounded, app_version="1.0.0", locale="en-US")

    assert step.target_descriptor.confirmed[0].automation_id == str(BTN_EXPORT)
