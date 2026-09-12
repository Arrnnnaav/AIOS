from __future__ import annotations

import pytest

from ghostcursor.devtools.act_live_node import _ConfirmationTiming, _measured_write


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
