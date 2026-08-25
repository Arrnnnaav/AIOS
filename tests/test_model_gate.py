import sys
from argparse import Namespace

import pytest

from ghostcursor.evaluation.dataset import load_dataset
from ghostcursor.evaluation.model_gate import RuntimeNoActionGuard, build_report, run_hermetic


def test_hermetic_gate_proves_d058_abstention_and_hint_bound():
    result = run_hermetic(load_dataset())

    assert result["passed"] is True
    assert result["checks"] == {
        "d058_rejected_ungrounded_export": True,
        "abstention_used_trusted_fallback": True,
        "hint_candidates_only_recipe_approved_export": True,
    }


def test_runtime_guard_rejects_loaded_tour_dispatcher(monkeypatch):
    monkeypatch.setitem(sys.modules, "ghostcursor.run", object())

    with pytest.raises(AssertionError, match="loaded before"):
        with RuntimeNoActionGuard():
            pass


def test_draft_gate_reports_interactive_skip_explicitly(monkeypatch):
    monkeypatch.setattr(
        "ghostcursor.evaluation.model_gate.run_local_model",
        lambda *args, **kwargs: {"passed": True},
    )
    args = Namespace(
        draft=True,
        endpoint="http://127.0.0.1:11434",
        unavailable_endpoint="http://127.0.0.1:1",
        model="qwen3:4b-instruct",
        timeout=1.0,
        interactive=False,
    )

    report = build_report(args)

    assert report["passed"] is True
    assert report["final_milestone_eligible"] is False
    assert report["lanes"]["interactive"] == {
        "passed": None,
        "skipped": True,
        "reason": "requires --interactive and a normal Windows desktop",
    }


def test_non_draft_gate_refuses_pending_owner_review():
    args = Namespace(
        draft=False,
        endpoint="http://127.0.0.1:11434",
        unavailable_endpoint="http://127.0.0.1:1",
        model="qwen3:4b-instruct",
        timeout=1.0,
        interactive=False,
    )

    with pytest.raises(ValueError, match="not owner-reviewed"):
        build_report(args)
