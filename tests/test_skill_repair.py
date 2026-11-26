"""Skills that repair themselves: a replayed Watch-me skill whose control
was renamed is offered as an update; nothing is saved without the OK, and
content-bearing names are never written in."""

from __future__ import annotations

from ghostcursor.providers import ExpectedChange as E
from ghostcursor.providers import Gateway, PlanStep, TeachPlan
from ghostcursor.workspace import task_skills
from ghostcursor.workspace.app import App
from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.session import Workspace

RECORDED = TeachPlan((
    PlanStep('Click "File" (MenuItem)', E.CHOSEN_STATE_CHANGES),
    PlanStep('Click "Export" (Button)', E.CHOSEN_STATE_CHANGES),
    PlanStep('Click "Q3 report.xlsx" (ListItem)', E.CHOSEN_STATE_CHANGES),
))


def _app(tmp_path):
    app = App("repair", make_workspace=lambda: Workspace("repair", Gateway(), Brain(tmp_path / "b.sqlite"), root=tmp_path / "r"))
    app.skills_dir = tmp_path / "skills"
    task_skills.save_skill("export report", RECORDED, dest_dir=app.skills_dir)
    app.handle("skill_use", {"name": "export report"})
    return app


def test_a_renamed_control_is_offered_and_saved_only_on_ok(tmp_path):
    app = _app(tmp_path)
    try:
        used = [(1, "File", "MenuItem"), (2, "Export as...", "Button"), (3, "Q4 report.xlsx", "ListItem")]
        app._offer_skill_repair(1, app.ws.plan, used)
        offer = app.state()["skill_repair"]
        assert offer == {"skill": "export-report", "changes": [{"step": 2, "old": "Export", "new": "Export as..."}]}
        assert task_skills.load_skill("export report", dest_dir=app.skills_dir).steps[1].instruction == 'Click "Export" (Button)'
        assert app.handle("skill_repair", {"apply": True}) == {"updated": 1}
        saved = task_skills.load_skill("export report", dest_dir=app.skills_dir)
        assert saved.steps[1].instruction == 'Click "Export as..." (Button)'
        assert saved.steps[2].instruction == 'Click "Q3 report.xlsx" (ListItem)'  # content never rewritten
        assert app.state()["skill_repair"] is None
    finally:
        app.close()


def test_no_is_kept_and_a_plan_not_from_a_skill_is_never_offered(tmp_path):
    app = _app(tmp_path)
    try:
        app._offer_skill_repair(1, app.ws.plan, [(2, "Export as...", "Button")])
        assert app.handle("skill_repair", {"apply": False}) == {"updated": 0}
        assert task_skills.load_skill("export report", dest_dir=app.skills_dir).steps[1].instruction == 'Click "Export" (Button)'
        app.ws._propose(RECORDED)  # the same steps, but not loaded as a skill
        app._offer_skill_repair(1, app.ws.plan, [(2, "Export as...", "Button")])
        assert app.state()["skill_repair"] is None
    finally:
        app.close()


def test_teach_records_which_control_did_each_step():
    from ghostcursor.harness.teach import ModelTeachSession
    from tests.test_harness_teach import FakeGateway, SyncSlot, _c, _choice, _frame

    plan = TeachPlan((PlanStep("Click Insert", E.CHOSEN_STATE_CHANGES),))
    session = ModelTeachSession("x", FakeGateway(plan, [_choice("c1")]), SyncSlot(), clock=lambda: 0.0, plan=plan)
    session.tick(_frame([_c(1, "Insert ribbon tab", "TabItem")]))
    session.tick(_frame([_c(1, "Insert ribbon tab", "TabItem")], frame_id=2), confirm=True)
    assert session.used == [(1, "Insert ribbon tab", "TabItem")]
