"""Company playbooks: a Right/Wrong on a TEAM skill's guided step is an
audit event (skill, step, verdict -- no names, no screen text); the owner's
report ranks steps by how often people said Wrong, across shared logs."""

from __future__ import annotations

import json

from ghostcursor import audit
from ghostcursor.workspace import team


def test_a_team_rating_is_an_audit_event_with_counts_only():
    assert audit._clean("teach_rating", {"skill": "team-expense-report", "step": 2, "verdict": "wrong", "app": r"C:\Apps\excel.exe", "control_type": "Button"}) == {
        "skill": "team-expense-report", "step": 2, "verdict": "wrong", "app": "excel.exe", "control_type": "Button"}
    try:
        audit._clean("teach_rating", {"skill": "x", "name": "Pay $40"})
    except ValueError:
        pass
    else:
        raise AssertionError("a control name was accepted")


def test_the_owner_sees_where_people_get_stuck_most_wrong_first(tmp_path):
    def log(pc, rows):
        (tmp_path / f"{pc}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")

    rate = lambda skill, step, verdict: {"event": "teach_rating", "skill": skill, "step": step, "verdict": verdict}  # noqa: E731
    log("pc1", [rate("team-expense", 2, "wrong"), rate("team-expense", 2, "wrong"), rate("team-expense", 1, "right"), {"event": "egress"}])
    log("pc2", [rate("team-expense", 2, "wrong"), rate("team-onboard", 3, "right"), rate("team-expense", 1, "maybe")])
    rows = team.playbook_report(tmp_path)
    assert rows[0] == {"skill": "team-expense", "step": 2, "right": 0, "wrong": 3, "pcs": 2}
    assert [(r["skill"], r["step"]) for r in rows] == [("team-expense", 2), ("team-expense", 1), ("team-onboard", 3)]


def test_only_the_owner_gets_the_report_from_the_page(tmp_path, monkeypatch):
    import pytest

    from ghostcursor.providers import Gateway
    from ghostcursor.workspace.app import App
    from ghostcursor.workspace.brain import Brain
    from ghostcursor.workspace.session import Workspace

    app = App("pb", make_workspace=lambda: Workspace("pb", Gateway(), Brain(tmp_path / "b.sqlite"), root=tmp_path / "r"))
    try:
        monkeypatch.setattr(team, "role", lambda: "staff")
        with pytest.raises(ValueError, match="owner"):
            app.handle("playbook_report", {})
        monkeypatch.setattr(team, "role", lambda: "owner")
        monkeypatch.setattr(team, "playbook_report", lambda: [{"skill": "team-x", "step": 1, "right": 1, "wrong": 2, "pcs": 1}])
        assert app.handle("playbook_report", {})["rows"][0]["wrong"] == 2
    finally:
        app.close()


def test_a_personal_skill_cannot_take_a_team_name_and_only_synced_ones_count(tmp_path):
    import pytest

    from ghostcursor.providers import ExpectedChange as E
    from ghostcursor.providers import PlanStep, TeachPlan
    from ghostcursor.workspace import task_skills

    plan = TeachPlan((PlanStep("Click Save", E.CHOSEN_STATE_CHANGES),))
    with pytest.raises(ValueError, match="team"):
        task_skills.save_skill("Team budget for Acme layoffs", plan, dest_dir=tmp_path)
    task_skills.save_skill("team-expenses", plan, dest_dir=tmp_path, team=True)
    assert task_skills.team_skill_names(dest_dir=tmp_path) == set()  # not in the verified manifest
    task_skills.set_team_skills(["team-expenses", "not-team"], dest_dir=tmp_path)
    assert task_skills.team_skill_names(dest_dir=tmp_path) == {"team-expenses"}


def test_a_rating_reaches_the_owner_only_for_a_synced_team_skill(tmp_path):
    from ghostcursor.providers import Gateway
    from ghostcursor.workspace import task_skills
    from ghostcursor.workspace.app import App
    from ghostcursor.workspace.brain import Brain
    from ghostcursor.workspace.session import Workspace

    app = App("pb", make_workspace=lambda: Workspace("pb", Gateway(), Brain(tmp_path / "b.sqlite"), root=tmp_path / "r"))
    app.skills_dir = tmp_path / "skills"
    try:
        app.ws.active_skill = "team-expenses"
        assert app._team_skill() == ""  # a hand-placed file is not the team's
        task_skills.set_team_skills(["team-expenses"], dest_dir=app.skills_dir)
        assert app._team_skill() == "team-expenses"
        app.ws.active_skill = "my-own"
        assert app._team_skill() == ""
    finally:
        app.close()
