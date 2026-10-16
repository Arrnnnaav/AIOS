"""IDEATE (owner build order 2): approaches with assumptions and unknowns,
recorded in the brief; a plan for the chosen approach carries its text only as
data, never as the goal; the plan shows which memories it was made with."""

from __future__ import annotations

import json

import pytest

from ghostcursor.providers.errors import FailureKind, ProviderError
from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.session import Workspace, parse_ideas
from tests.test_workspace_session import PLAN, FakeGateway

IDEAS = {
    "ideas": [
        {
            "title": "Reuse last deck",
            "summary": "Start from the March deck.",
            "assumptions": ["the March deck is current"],
            "unknowns": ["which numbers changed"],
        },
        {
            "title": "Fresh template",
            "summary": "Start from a blank template.",
            "assumptions": [],
            "unknowns": [],
        },
    ]
}
MEMORY = {"kind": "preference", "text": "prefers dark slides", "confidence": 0.9}


class IdeaGateway(FakeGateway):
    def complete(self, envelope, system, schema, parse, **kw):
        if kw.get("purpose") == "ideation":
            self.envelopes.append(envelope)
            return parse(json.dumps(IDEAS))
        return super().complete(envelope, system, schema, parse, **kw)


@pytest.fixture
def ws(tmp_path):
    brain = Brain(tmp_path / "brain.sqlite")
    yield Workspace("deck", IdeaGateway(memories=[MEMORY]), brain, root=tmp_path / "briefs")
    brain.close()


def test_ideas_are_recorded_and_a_chosen_one_travels_only_as_data(ws):
    ws.discuss("Make my investor deck. I prefer dark slides.")
    ideas = ws.ideate()
    assert [i.title for i in ideas] == ["Reuse last deck", "Fresh template"]
    assert ws.turns[-1].text.startswith("[ideas]\n1. Reuse last deck: Start from")
    assert "Unknown: which numbers changed." in ws.turns[-1].text
    assert ws.make_plan(idea=1) == PLAN
    sent = ws.gateway.envelopes[-1]
    assert sent.trusted["goal"] == "Make my investor deck. I prefer dark slides."
    assert "Reuse last deck" not in json.dumps(sent.trusted)
    assert sent.tainted["chosen_approach"].text.startswith("Reuse last deck")
    assert [ws.brain.get(m).text for m in ws.plan_memories] == ["prefers dark slides"]


def test_an_unknown_idea_or_no_model_gives_no_plan(ws):
    with pytest.raises(ValueError):
        ws.make_plan(idea=1)
    ws.gateway.fail = ProviderError(FailureKind.UNAVAILABLE)
    ws.gateway.complete = FakeGateway.complete.__get__(ws.gateway)
    assert ws.ideate() == () and ws.ideas == ()


@pytest.mark.parametrize(
    "bad",
    [
        {"ideas": IDEAS["ideas"][:1]},
        {"ideas": IDEAS["ideas"], "extra": 1},
        {"ideas": [dict(IDEAS["ideas"][0], steps=[]), IDEAS["ideas"][1]]},
        {"ideas": [dict(IDEAS["ideas"][0], title=""), IDEAS["ideas"][1]]},
        {"ideas": [dict(IDEAS["ideas"][0], unknowns=["x"] * 5), IDEAS["ideas"][1]]},
    ],
)
def test_ideas_outside_the_schema_are_refused(bad):
    with pytest.raises(ProviderError) as exc:
        parse_ideas(json.dumps(bad))
    assert exc.value.kind is FailureKind.INVALID_OUTPUT


def test_the_page_reads_plan_memories_without_touching_sqlite(tmp_path):
    """state() runs on a request thread; the Brain's sqlite may not."""
    from concurrent.futures import ThreadPoolExecutor

    from ghostcursor.workspace.app import App

    app = App(
        "deck",
        make_workspace=lambda: Workspace(
            "deck",
            IdeaGateway(memories=[MEMORY]),
            Brain(tmp_path / "brain.sqlite"),
            root=tmp_path / "briefs",
        ),
    )
    app.handle("say", {"text": "Make my investor deck. I prefer dark slides."})
    app.handle("plan", {})
    with ThreadPoolExecutor(1) as other:
        state = other.submit(app.state).result()
    assert state["plan_memories"] == ["prefers dark slides"]
    app.close()
