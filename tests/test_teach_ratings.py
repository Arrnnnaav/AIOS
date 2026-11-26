"""Right/Wrong on the pointer Teach shows: a wrong control is not offered
again for that step, and every verdict is kept locally without names."""

from __future__ import annotations

import json

from ghostcursor.harness import ratings
from ghostcursor.harness.teach import ModelTeachSession, Phase
from ghostcursor.providers import ExpectedChange as E
from ghostcursor.providers import PlanStep, TeachPlan
from tests.test_harness_teach import FakeGateway, SyncSlot, _c, _choice, _frame


def test_a_wrong_control_is_not_offered_again_for_that_step():
    plan = TeachPlan((PlanStep("Click Insert", E.CHOSEN_STATE_CHANGES),))
    gateway = FakeGateway(plan, [_choice("c1"), _choice("c2")])
    offered = []
    real_choose = gateway.choose

    def choose(envelope, ids, **kw):
        offered.append(tuple(ids))
        return real_choose(envelope, ids, **kw)

    gateway.choose = choose
    session = ModelTeachSession("x", gateway, SyncSlot(), clock=lambda: 0.0, plan=plan)
    frame = _frame([_c(1, "Insert"), _c(2, "Insert Picture")])
    shown = session.tick(frame)
    assert shown.phase is Phase.SHOWING and shown.target.name == "Insert"
    assert session.reject() is True
    again = session.tick(frame)
    assert "c1" not in offered[-1] and again.target.name == "Insert Picture"


def test_reject_does_nothing_when_no_pointer_or_while_acting():
    plan = TeachPlan((PlanStep("Click Insert", E.CHOSEN_STATE_CHANGES),))
    session = ModelTeachSession("x", FakeGateway(plan, [_choice("c1")]), SyncSlot(), clock=lambda: 0.0, plan=plan)
    assert session.reject() is False  # nothing shown yet
    acting = ModelTeachSession(
        "x", FakeGateway(plan, [_choice("c1")]), SyncSlot(), clock=lambda: 0.0, plan=plan,
        act=lambda step, target: "ok",
    )
    assert acting.reject() is False


def test_ratings_are_kept_locally_without_names(tmp_path):
    path = tmp_path / "r.jsonl"
    ratings.record("right", app="Notepad.exe", control_type="MenuItem", step=1, path=path)
    ratings.record("wrong", app="notepad.exe", control_type="Button", step=2, path=path)
    ratings.record("right", app="POWERPNT.EXE", control_type="TabItem", step=1, path=path)
    path.write_text(path.read_text() + "{torn\n")
    assert ratings.summary(path) == {
        "notepad.exe": {"right": 1, "wrong": 1},
        "powerpnt.exe": {"right": 1, "wrong": 0},
    }
    rows = [json.loads(line) for line in path.read_text().splitlines()[:3]]
    assert all(set(r) == {"at", "app", "control_type", "step", "verdict"} for r in rows)
    try:
        ratings.record("maybe", app="x", control_type="y", step=1, path=path)
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown verdict was kept")


def test_the_page_rates_only_while_guiding(tmp_path):
    import pytest

    from ghostcursor.providers import Gateway
    from ghostcursor.workspace.app import App
    from ghostcursor.workspace.brain import Brain
    from ghostcursor.workspace.session import Workspace

    app = App("rate", make_workspace=lambda: Workspace("rate", Gateway(), Brain(tmp_path / "b.sqlite"), root=tmp_path / "r"))
    try:
        with pytest.raises(ValueError, match="nothing is being shown"):
            app.handle("rate_step", {"verdict": "wrong"})
        app.busy = "Guiding"
        with pytest.raises(ValueError, match="right or wrong"):
            app.handle("rate_step", {"verdict": "meh"})
        app.handle("rate_step", {"verdict": "wrong"})
        assert app._take_rating() == "wrong" and app._take_rating() is None
    finally:
        app.busy = ""
        app.close()
