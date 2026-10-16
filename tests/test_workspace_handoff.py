"""Handoff (owner build order 4, Multiplayer seed): only goal, steps and
sources leave, scrubbed; what arrives is a proposal and an assistant turn,
never the receiver's goal; anything outside the closed shape is refused."""

from __future__ import annotations

import json

import pytest

from ghostcursor.workspace import handoff
from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.session import Workspace
from tests.test_workspace_session import PLAN, FakeGateway


def _ws(tmp_path, name):
    return Workspace(
        name, FakeGateway(), Brain(tmp_path / f"{name}.sqlite"), root=tmp_path / "b"
    )


def _sent(tmp_path):
    ws = _ws(tmp_path, "sender")
    ws.discuss("Build the Q3 deck; mail bob@acme.com when done")
    ws.make_plan()
    return ws, handoff.export(ws, "Asha")


def test_only_goal_steps_and_sources_leave_and_they_are_scrubbed(tmp_path):
    ws, text = _sent(tmp_path)
    value = json.loads(text)
    assert set(value) == {"kind", "version", "from", "goal", "plan", "sources"}
    assert value["goal"] == "Build the Q3 deck; mail [email] when done"
    assert [s["instruction"] for s in value["plan"]] == [
        s.instruction for s in PLAN.steps
    ]
    assert "ok" not in text  # the assistant's reply (the conversation) stays home


def test_what_arrives_is_a_proposal_not_the_receivers_goal(tmp_path):
    _, text = _sent(tmp_path)
    other = _ws(tmp_path, "receiver")
    assert handoff.receive(other, text) == "Asha"
    assert other.goal == ""  # someone else's words never become the goal
    assert other.turns[-2].speaker == "assistant"
    assert other.turns[-2].text.startswith("[handoff from Asha] Their goal: Build")
    assert other.plan == PLAN and other.proposal.revision == 1
    with pytest.raises(ValueError):
        handoff.receive(other, text)  # already has a plan


def _bad(text, **change):
    value = json.loads(text)
    value.update(change)
    return json.dumps(value)


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "other"},
        {"version": 2},
        {"plan": []},
        {"plan": [{"instruction": "x", "expected_change": "explode"}]},
        {
            "plan": [
                {
                    "instruction": "x",
                    "expected_change": "chosen_disappears",
                    "at": [1, 2],
                }
            ]
        },
        {"sources": [{"url": "javascript:alert(1)", "title": "t"}]},
        {"extra": 1},
    ],
)
def test_anything_outside_the_closed_shape_is_refused(tmp_path, change):
    _, text = _sent(tmp_path)
    with pytest.raises(ValueError):
        handoff.parse(_bad(text, **change))


def test_no_plan_no_handoff_and_oversize_is_refused(tmp_path):
    with pytest.raises(ValueError):
        handoff.export(_ws(tmp_path, "empty"), "Asha")
    _, text = _sent(tmp_path)
    handoff.parse(text)
    with pytest.raises(ValueError, match="too large"):
        handoff.parse(text + " " * handoff.MAX_BYTES)  # valid JSON, too big


def test_app_saves_and_opens_a_handoff(tmp_path):
    from ghostcursor.workspace.app import App

    app = App("sender", make_workspace=lambda: _sent(tmp_path)[0])
    app.downloads = tmp_path / "dl"
    path = app.handle("handoff_export", {"name": "Asha"})["path"]
    app.close()
    other = App("receiver", make_workspace=lambda: _ws(tmp_path, "receiver"))
    data = (tmp_path / "dl" / "sender.orbyn-handoff.json").read_text(encoding="utf-8")
    assert path.endswith("sender.orbyn-handoff.json")
    assert other.handle("handoff_import", {"data": data}) == {"from": "Asha"}
    assert other.state()["plan"]["revision"] == 1
    other.close()


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"goal": ["not", "text"]},
        {"from": {"x": 1}},
        {"plan": [{"instruction": ["a"], "expected_change": "chosen_disappears"}]},
        {"sources": [{"url": ["https://x"], "title": "t"}]},
    ],
)
def test_fields_must_be_their_exact_types(tmp_path, change):
    _, text = _sent(tmp_path)
    with pytest.raises(ValueError):
        handoff.parse(_bad(text, **change))


def test_local_only_policy_refuses_a_handoff(tmp_path, monkeypatch):
    from ghostcursor import policy

    ws, _ = _sent(tmp_path)
    monkeypatch.setattr(policy, "_value", lambda name: 0 if name == "MaxEgress" else None)
    with pytest.raises(ValueError, match="organisation"):
        handoff.export(ws, "Asha")
