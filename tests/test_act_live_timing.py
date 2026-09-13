from __future__ import annotations

import pytest

from ghostcursor.devtools.act_live_node import (
    _ConfirmationTiming,
    _cue_budget,
    _default_visual_durations,
    _measured_write,
    _parse_arguments,
)


class _Clock:
    def __init__(self, *values: int) -> None:
        self._values = iter(values)

    def __call__(self) -> int:
        return next(self._values)


def test_confirmation_timing_measures_the_read_and_actual_uia_write_boundary():
    timing = _ConfirmationTiming(_Clock(1_000_000, 6_000_000, 8_500_000))

    timing.confirmation_started()
    timing.confirmation_completed()
    timing.request_written({"type": "execute", "pattern": "Invoke"})

    assert timing.record() == {
        "confirmation_round_trip_ms": 5.0,
        "confirmation_to_request_write_ms": 2.5,
    }


def test_non_uia_frames_cannot_satisfy_the_request_write_measurement():
    timing = _ConfirmationTiming(_Clock(1, 2))
    timing.confirmation_started()
    timing.confirmation_completed()
    timing.request_written({"type": "observe"})

    with pytest.raises(RuntimeError, match="incomplete"):
        timing.record()


def test_an_execute_frame_without_a_pattern_is_not_a_uia_dispatch():
    timing = _ConfirmationTiming(_Clock(1, 2))
    timing.confirmation_started()
    timing.confirmation_completed()
    timing.request_written({"type": "execute", "operation_id": "object.action"})

    with pytest.raises(RuntimeError, match="incomplete"):
        timing.record()


def test_a_request_before_confirmation_is_refused():
    timing = _ConfirmationTiming(_Clock(1))

    with pytest.raises(RuntimeError, match="before confirmation"):
        timing.request_written({"type": "execute", "pattern": "Invoke"})


def test_a_failed_pipe_write_is_not_recorded_as_a_written_request():
    timing = _ConfirmationTiming(_Clock(1, 2))
    timing.confirmation_started()
    timing.confirmation_completed()

    def failed(_frame):
        raise OSError("closed")

    with pytest.raises(OSError, match="closed"):
        _measured_write(timing, failed, {"type": "execute", "pattern": "Invoke"})
    with pytest.raises(RuntimeError, match="incomplete"):
        timing.record()


def test_a_second_execute_frame_cannot_replace_the_measured_boundary():
    timing = _ConfirmationTiming(_Clock(1, 2, 3, 4))
    timing.confirmation_started()
    timing.confirmation_completed()
    timing.request_written({"type": "execute", "pattern": "Invoke"})

    with pytest.raises(RuntimeError, match="more than one"):
        timing.request_written({"type": "execute", "pattern": "Invoke"})


def test_confirmation_cannot_complete_twice():
    timing = _ConfirmationTiming(_Clock(1, 2, 3))
    timing.confirmation_started()
    timing.confirmation_completed()

    with pytest.raises(RuntimeError, match="completed twice"):
        timing.confirmation_completed()


def test_confirmation_cannot_start_twice():
    timing = _ConfirmationTiming(_Clock(1, 2))
    timing.confirmation_started()

    with pytest.raises(RuntimeError, match="started twice"):
        timing.confirmation_started()


def test_confirmation_cannot_complete_before_it_starts():
    timing = _ConfirmationTiming(_Clock(1))

    with pytest.raises(RuntimeError, match="before it started"):
        timing.confirmation_completed()


def test_the_live_diagnostic_uses_the_measured_receipt_policy():
    import inspect
    from ghostcursor.devtools import act_live_node

    source = inspect.getsource(act_live_node.main)
    assert "receipt_policy = measured_receipt_policy()" in source
    assert "first_paint_deadline_ms=2000" not in source
    assert "completion_deadline_ms=8000" not in source


def test_the_live_diagnostic_defaults_to_the_budget_that_policy_measured():
    from ghostcursor.act_cli import default_cue_budget

    budget = default_cue_budget()

    assert _default_visual_durations() == (budget.traversal_ms, budget.settle_ms)

    arguments = _parse_arguments(["--frame-budget-ms", "2"])
    parsed = _cue_budget(arguments)
    assert (parsed.traversal_ms, parsed.settle_ms) == (
        budget.traversal_ms,
        budget.settle_ms,
    )


def test_explicit_visual_duration_overrides_reach_the_presenter_budget():
    arguments = _parse_arguments(
        [
            "--frame-budget-ms",
            "3",
            "--traversal-ms",
            "701",
            "--settle-ms",
            "902",
        ]
    )

    budget = _cue_budget(arguments)

    assert budget.traversal_ms == 701
    assert budget.settle_ms == 902
    assert budget.frame_budget_ms == 3


def test_main_passes_explicit_visual_overrides_to_the_actual_presenter_boundary(
    monkeypatch,
):
    """Protect the call site, not merely the helper that computes its value."""

    from argparse import Namespace

    from ghostcursor.devtools import act_live_node

    arguments = Namespace(
        operation="powerpoint.new_slide_uia",
        window_class="PPTFrameClass",
        frame_budget_ms=3,
        stop_after_ms=None,
        stop_before=None,
        traversal_ms=701,
        settle_ms=902,
        json=None,
    )
    captured = {}

    class PresenterReached(RuntimeError):
        pass

    def presenter(_hwnd, **kwargs):
        captured.update(kwargs)
        raise PresenterReached

    monkeypatch.setattr(act_live_node, "_parse_arguments", lambda: arguments)
    monkeypatch.setattr(act_live_node, "find_window", lambda _class: (101, 202))
    monkeypatch.setattr(
        act_live_node,
        "executable_of",
        lambda _pid: ("POWERPNT.EXE", "16.0"),
    )
    monkeypatch.setattr(
        act_live_node.overlay_window, "create_overlay_window", lambda: 303
    )
    monkeypatch.setattr(act_live_node, "overlay_presenter", presenter)

    with pytest.raises(PresenterReached):
        act_live_node.main()

    budget = captured["budget"]
    assert budget.traversal_ms == 701
    assert budget.settle_ms == 902
    assert budget.frame_budget_ms == 3
