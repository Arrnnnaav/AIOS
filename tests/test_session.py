from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import zipfile

import pytest

from ghostcursor.session import (
    SessionCapabilities,
    SessionSnapshot,
    SessionStatus,
    active_capabilities,
)
from ghostcursor.session_store import DiagnosticExportOptions, SessionStore


def _snapshot(**overrides):
    values = {
        "session_id": "session-1",
        "status": SessionStatus.GUIDING,
        "goal": "secret workbook goal",
        "intent_id": "MAKE_DECK",
        "plugin_id": "ghostcursor.powerpoint",
        "plugin_version": "1.0.0",
        "application": "POWERPNT.EXE",
        "target_hwnd": 123,
        "current_step": 1,
        "total_steps": 2,
        "plan_steps": ("Add a slide", "Add a title"),
        "instruction": "private instruction",
        "detail": "C:\\Customers\\private.pptx",
        "capabilities": active_capabilities(),
    }
    values.update(overrides)
    return SessionSnapshot(**values)


def test_a_snapshot_refuses_progress_the_executor_could_not_have_made():
    with pytest.raises(ValueError, match="exceed"):
        _snapshot(current_step=3)
    with pytest.raises(ValueError, match="plan length"):
        _snapshot(plan_steps=("only one",))


def test_active_capabilities_are_explicit_not_inferred_by_the_surface():
    assert active_capabilities() == SessionCapabilities(
        can_pause=True,
        can_stop=True,
        can_repeat=True,
        can_report_problem=True,
        can_choose_target=False,
    )
    assert not active_capabilities(paused=True).can_repeat


def test_session_history_never_persists_goal_instruction_hwnd_or_detail(tmp_path):
    with SessionStore(tmp_path / "sessions.sqlite") as store:
        store.record(_snapshot())
        event = store.events()[0]

    serialized = json.dumps(event)
    assert "secret workbook goal" not in serialized
    assert "private instruction" not in serialized
    assert "Customers" not in serialized
    assert "target_hwnd" not in event
    assert event["detail_code"] == "present"


def test_diagnostics_require_separate_explicit_consent_for_goal_and_note(tmp_path):
    archive_path = tmp_path / "diagnostics.zip"
    with SessionStore(tmp_path / "sessions.sqlite") as store:
        store.record(_snapshot())
        store.export(
            archive_path,
            goal="private goal",
            note="private note",
        )
    with zipfile.ZipFile(archive_path) as archive:
        payload = json.loads(archive.read("diagnostics.json"))
    assert "goal" not in payload
    assert "note" not in payload

    with SessionStore(tmp_path / "sessions.sqlite") as store:
        store.export(
            archive_path,
            options=DiagnosticExportOptions(include_goal=True, include_note=True),
            goal="private goal",
            note="private note",
        )
    with zipfile.ZipFile(archive_path) as archive:
        payload = json.loads(archive.read("diagnostics.json"))
    assert payload["goal"] == "private goal"
    assert payload["note"] == "private note"


def test_thirty_day_retention_is_an_exact_boundary(tmp_path):
    now = datetime(2026, 8, 31, tzinfo=UTC)
    with SessionStore(tmp_path / "sessions.sqlite") as store:
        store.record(_snapshot(session_id="old"), occurred_at=now - timedelta(days=31))
        store.record(_snapshot(session_id="boundary"), occurred_at=now - timedelta(days=30))
        store.record(_snapshot(session_id="new"), occurred_at=now - timedelta(days=1))
        assert store.purge_expired(now=now) == 1
        assert [event["session_id"] for event in store.events()] == ["boundary", "new"]
