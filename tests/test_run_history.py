"""Run history (Work) and Undo: each Guide me / Do it for me run is one
line with no control names; Undo drafts a plan to approve, never acts."""

from __future__ import annotations

import pytest

from ghostcursor.providers import ExpectedChange as E
from ghostcursor.providers import PlanStep, TeachPlan
from ghostcursor.workspace.app import App
from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.session import Workspace
from tests.test_how_to_guide import PLAN, Planner


def _app(tmp_path):
    return App("runs", make_workspace=lambda: Workspace("runs", Planner(), Brain(tmp_path / "b.sqlite"), root=tmp_path / "r"))


def test_a_run_is_remembered_without_names_newest_first(tmp_path, monkeypatch):
    from ghostcursor.harness import binding

    app = _app(tmp_path)
    try:
        monkeypatch.setattr(binding, "identify", lambda hwnd: type("I", (), {"executable": "EXCEL.EXE"})())
        plan = TeachPlan((PlanStep('Click "Pay $40" (Button)', E.CHOSEN_STATE_CHANGES),) * 3)
        app._remember_run(1, plan, [5], [(1, "done"), (2, "done")], 2, act=True)
        app._remember_run(1, plan, [5], [], 0, act=False)
        runs = app.state()["runs"]
        assert [r["mode"] for r in runs] == ["guide", "act"]
        assert runs[1] | {"at": 0} == {"at": 0, "mode": "act", "from_step": 1, "done": 2, "total": 3, "ended": "blocked", "apps": ["EXCEL.EXE"]}
        assert "Pay" not in str(runs)  # no control names
    finally:
        app.close()


def test_undo_drafts_a_plan_and_needs_an_act_run(tmp_path, monkeypatch):
    from ghostcursor.harness import binding

    app = _app(tmp_path)
    try:
        with pytest.raises(ValueError, match="no Do it for me run"):
            app.handle("undo_plan", {})
        monkeypatch.setattr(binding, "identify", lambda hwnd: type("I", (), {"executable": "notepad.exe"})())
        app._remember_run(1, PLAN, [5], [(1, "done")], 0, act=True)
        assert app.handle("undo_plan", {}) == {"steps": 1}
        envelope = app.ws.gateway.envelopes[-1]
        assert "Undo the last 1 change(s) Orbyn just made in notepad.exe" in envelope.trusted["goal"]
        assert app.ws.plan is PLAN  # proposed, to be approved; nothing was done
    finally:
        app.close()
