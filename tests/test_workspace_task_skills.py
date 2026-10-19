"""Record->skill (D186, rec #2): save a demonstrated TeachPlan, load it back
validated, list skills. Replay feeds the existing gated Teach/Act path; this
module only persists. A tampered skill file is refused on load."""

from __future__ import annotations

import json

import pytest

from ghostcursor.providers import ExpectedChange, PlanStep, TeachPlan
from ghostcursor.providers.errors import FailureKind, ProviderError
from ghostcursor.workspace import task_skills


def _plan():
    return TeachPlan(
        (
            PlanStep("Open Save As", ExpectedChange.TITLE_CHANGES, "click", ""),
            PlanStep(
                "Type the file name",
                ExpectedChange.CHOSEN_STATE_CHANGES,
                "type",
                "report",
            ),
        )
    )


def test_save_then_load_round_trips_the_plan(tmp_path):
    path = task_skills.save_skill("Save As report", _plan(), dest_dir=tmp_path)
    assert path.name == "save-as-report.json"  # slugged, no traversal
    loaded = task_skills.load_skill("Save As report", dest_dir=tmp_path)
    assert loaded is not None and len(loaded.steps) == 2
    assert loaded.steps[1].action == "type" and loaded.steps[1].text == "report"
    assert loaded.steps[0].expected_change is ExpectedChange.TITLE_CHANGES


def test_list_and_absent(tmp_path):
    task_skills.save_skill("alpha task", _plan(), dest_dir=tmp_path)
    task_skills.save_skill("beta task", _plan(), dest_dir=tmp_path)
    assert task_skills.list_skills(dest_dir=tmp_path) == ["alpha-task", "beta-task"]
    assert task_skills.load_skill("missing", dest_dir=tmp_path) is None


def test_a_tampered_skill_file_is_refused_on_load(tmp_path):
    # hand-write an out-of-schema skill (a disallowed action)
    (tmp_path / "evil.json").write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "instruction": "x",
                        "expected_change": "title_changes",
                        "action": "launch_exe",
                        "text": "rm -rf",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ProviderError) as raised:
        task_skills.load_skill("evil", dest_dir=tmp_path)
    assert raised.value.kind is FailureKind.INVALID_OUTPUT


def test_bad_names_and_empty_plans_are_refused(tmp_path):
    with pytest.raises(ValueError):
        task_skills.save_skill("!!!", _plan(), dest_dir=tmp_path)  # slug empty
    with pytest.raises(ValueError):
        task_skills.save_skill("ok", TeachPlan(()), dest_dir=tmp_path)  # no steps
