"""Watch me, then repeat: clicks on observed controls become a plan; text
fields become 'type here' steps with no text; nothing outside the bound
windows, no repeated double clicks, and Stop saves nothing."""

from __future__ import annotations

from ghostcursor.harness.watch import step_for, watch
from ghostcursor.providers import ExpectedChange as E
from tests.test_harness_teach import _c, _frame


class Observer:
    def __init__(self, frame):
        self.frame = frame

    def latest(self):
        return self.frame


def _run(presses, frame, *, stop_at=None):
    """PRESSES: (x, y) per poll, None for button up."""

    script = list(presses)
    polls = {"n": 0}

    def button():
        i = polls["n"]
        return i < len(script) and script[i] is not None

    def cursor():
        return script[polls["n"]]

    def sleep(_):
        polls["n"] += 1

    said = []
    plan = watch(
        Observer(frame), 1e9,
        done=lambda: polls["n"] >= len(script),
        stop=lambda: stop_at is not None and polls["n"] >= stop_at,
        say=said.append, button=button, cursor=cursor, clock=lambda: 0.0, sleep=sleep,
    )
    return plan, said


def test_clicks_on_observed_controls_become_steps_in_order():
    insert = _c(1, "Insert", "TabItem", rect=(10, 10, 60, 30))
    title = _c(2, "Title", "Edit", rect=(10, 100, 200, 130))
    frame = _frame([insert, title])
    plan, said = _run([None, (20, 20), (20, 20), None, (20, 20), None, (50, 110), None, (900, 900), None], frame)
    steps = plan.steps
    assert [s.instruction for s in steps] == ['Click "Insert" (TabItem)', 'Click into "Title" (Edit) and type']
    assert steps[1].action == "click" and steps[1].text == ""  # nothing typed is recorded
    assert steps[1].expected_change is E.FOCUS_MOVES_TO_CHOSEN
    assert "Step 2" in said[-1]


def test_stop_saves_nothing_and_no_clicks_is_no_plan():
    frame = _frame([_c(1, "Insert", "TabItem", rect=(10, 10, 60, 30))])
    plan, said = _run([(20, 20), None, None, None], frame, stop_at=2)
    assert plan is None and "nothing was saved" in said[-1]
    plan, said = _run([None, (900, 900), None], frame)
    assert plan is None and "No click" in said[-1]


def test_a_button_already_held_when_watching_starts_is_not_a_click():
    frame = _frame([_c(1, "Insert", "TabItem", rect=(10, 10, 60, 30))])
    plan, _ = _run([(20, 20), (20, 20), None], frame)
    assert plan is None


def test_an_unnamed_control_still_gets_a_readable_step():
    assert step_for(_c(1, "", "Button")).instruction == 'Click "the Button" (Button)'


def test_the_page_records_saves_uses_and_deletes_a_skill(tmp_path, monkeypatch):
    from ghostcursor.providers import Gateway, PlanStep, TeachPlan
    from ghostcursor.workspace.app import App
    from ghostcursor.workspace.brain import Brain
    from ghostcursor.workspace.session import Workspace

    app = App("watch", make_workspace=lambda: Workspace("watch", Gateway(), Brain(tmp_path / "b.sqlite"), root=tmp_path / "r"))
    app.skills_dir = tmp_path / "skills"
    try:
        recorded = TeachPlan((PlanStep('Click "Export" (Button)', E.CHOSEN_STATE_CHANGES),))
        app.windows = [type("W", (), {"hwnd": 5})()]
        monkeypatch.setattr(app, "_watch", lambda hwnds, seconds: (app.ws._propose(recorded), 1)[1])
        assert app.handle("watch", {"windows": [0], "seconds": 60}) == {"steps": 1}
        assert app.handle("skill_save", {"name": "Weekly export"}) == {"name": "weekly-export"}
        assert app.state()["skills"] == ["weekly-export"]
        app.ws._propose(TeachPlan((PlanStep("Something else", E.CHOSEN_STATE_CHANGES),)))
        assert app.handle("skill_use", {"name": "weekly-export"}) == {"steps": 1}
        assert app.ws.plan.steps[0].instruction == 'Click "Export" (Button)'
        app.handle("skill_delete", {"name": "weekly-export"})
        assert app.state()["skills"] == []
    finally:
        app.close()



def test_a_content_name_is_kept_short_with_private_details_hidden():
    step = step_for(_c(1, "Invoice from ana@acme.com about the March payroll run for everyone", "ListItem"))
    assert "ana@acme.com" not in step.instruction and len(step.instruction) < 80


def test_watching_ends_at_the_deadline():
    frame = _frame([_c(1, "Insert", "TabItem", rect=(10, 10, 60, 30))])
    now = [0.0]

    def sleep(_):
        now[0] += 1.0

    plan = watch(Observer(frame), 3.0, done=lambda: False, stop=lambda: False, say=lambda m: None,
                 button=lambda: False, cursor=lambda: (0, 0), clock=lambda: now[0], sleep=sleep)
    assert plan is None and now[0] >= 3.0
