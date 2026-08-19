"""Capture and diffing. The diff is what stops OCR running every tick."""

import numpy as np

from ghostcursor.overlay import dpi  # noqa: F401  DPI awareness at import (D010)
from ghostcursor.perception.capture import (
    FRAME_DIFF_THRESHOLD,
    capture_window,
    frames_differ,
)


def _frame(value=0):
    return np.full((100, 200, 3), value, dtype=np.uint8)


def test_no_previous_frame_counts_as_changed():
    """The first observation must never be skipped."""
    assert frames_differ(None, _frame()) is True


def test_identical_frames_do_not_differ():
    assert frames_differ(_frame(10), _frame(10)) is False


def test_a_fully_repainted_frame_differs():
    assert frames_differ(_frame(0), _frame(255)) is True


def test_a_tiny_change_is_below_the_threshold():
    """A blinking cursor must not trigger a re-read."""
    current = _frame(0)
    current[0:2, 0:2] = 255  # 4 of 20000 pixels = 0.02%
    assert frames_differ(_frame(0), current) is False


def test_a_change_just_over_the_threshold_is_detected():
    current = _frame(0)
    rows = int(100 * (FRAME_DIFF_THRESHOLD * 2))
    current[0:rows, :] = 255
    assert frames_differ(_frame(0), current) is True


def test_mismatched_shapes_count_as_changed():
    """A resized window is a change, not a crash."""
    assert frames_differ(_frame(), np.zeros((50, 50, 3), dtype=np.uint8)) is True


def test_capturing_an_absent_window_returns_none():
    assert capture_window("NoSuchWindowTitleAnywhere12345") is None
