"""App skills (D186, rec #4): author-controlled per-app guidance the model-
driven planner pulls in by trigger word. Guidance only -- never execution
authority, never screen text or model output. Broadening Teach/plan coverage to
more apps (Word, Excel, browser) alongside PowerPoint."""

from __future__ import annotations

from ghostcursor.workspace import skills


def test_app_goals_pull_the_matching_skill():
    def names(goal):
        return {name for name, _body in skills.relevant(goal)}

    assert "word" in names("write a cover letter in Word")
    assert "excel" in names("build a spreadsheet with a SUM formula")
    assert "browser" in names("open the website in a new tab")
    assert "powerpoint" in names("make a slide deck")


def test_an_unrelated_goal_pulls_no_skill():
    assert skills.relevant("summarize my week") == []


def test_every_skill_has_triggers_and_a_body():
    for name, body in [(n, b) for n, _t, b in skills._loaded()]:
        assert body.strip(), f"{name} skill has an empty body"
