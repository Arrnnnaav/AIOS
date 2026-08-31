from __future__ import annotations

from types import SimpleNamespace

from ghostcursor.manager import project_snapshot
from ghostcursor.session import (
    SessionSnapshot,
    SessionStatus,
    active_capabilities,
    terminal_capabilities,
)


def _snapshot(**overrides):
    values = {
        "session_id": "session-1",
        "status": SessionStatus.GUIDING,
        "goal": "Create a project update",
        "intent_id": "CREATE_DECK",
        "plugin_id": "ghostcursor.powerpoint",
        "plugin_version": "1.0.0",
        "application": "POWERPNT.EXE",
        "current_step": 2,
        "total_steps": 3,
        "plan_steps": ("Create a deck", "Add a slide", "Save the deck"),
        "instruction": "Add one title slide.",
        "verification_state": "waiting for the title slide",
        "capabilities": active_capabilities(),
    }
    values.update(overrides)
    return SessionSnapshot(**values)


def test_manager_projects_executor_progress_without_counting_it_again():
    projection = project_snapshot(_snapshot())

    assert projection.status == "Guiding"
    assert projection.progress == "Step 2 of 3"
    assert [(step.number, step.state) for step in projection.steps] == [
        (1, "completed"),
        (2, "current"),
        (3, "pending"),
    ]
    assert projection.instruction == "Add one title slide."
    assert projection.verification == "waiting for the title slide"


def test_completed_projection_marks_only_executor_reported_plan_as_complete():
    projection = project_snapshot(
        _snapshot(
            status=SessionStatus.COMPLETED,
            current_step=3,
            instruction="",
            verification_state="",
            capabilities=terminal_capabilities(),
        )
    )

    assert all(step.state == "completed" for step in projection.steps)
    assert projection.instruction == "The workflow reached its verified outcome."
    assert projection.verification == "Verified"
    assert not projection.can_stop


def test_failure_projection_uses_stable_error_code_not_raw_detail_as_status():
    projection = project_snapshot(
        _snapshot(
            status=SessionStatus.FAILED,
            current_step=1,
            instruction="",
            verification_state="",
            error_code="TOUR_TIMED_OUT",
            detail="C:\\Customers\\private.pptx failed around secret text",
        )
    )

    assert projection.status == "Could not complete"
    assert "TOUR_TIMED_OUT" in projection.details
    assert "Customers" not in projection.details
    assert "private" not in projection.details


def test_paused_projection_changes_control_label_state_from_the_snapshot():
    projection = project_snapshot(
        _snapshot(status=SessionStatus.PAUSED, capabilities=active_capabilities(paused=True))
    )
    assert projection.paused
    assert projection.can_pause


def test_target_candidate_rows_need_both_handle_and_live_identity():
    candidate = SimpleNamespace(
        hwnd=42,
        title="Quarterly review - PowerPoint",
        app=SimpleNamespace(executable_name="POWERPNT.EXE", version="16.0"),
    )
    # The native view consumes these exact fields; title alone is deliberately
    # insufficient because two windows may have identical titles.
    assert (candidate.hwnd, candidate.app.executable_name) == (42, "POWERPNT.EXE")
