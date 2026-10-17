"""Create, test, save and list reusable agents (D182). Creating or saving is
authoring only -- no actions, no permissions; a saved agent runs through the
harness like any plan. A drafted agent is strictly parsed; the auto-test gates
the save; the registry round-trips and re-validates on load."""

from __future__ import annotations

import json

import pytest

from ghostcursor.providers.errors import FailureKind, ProviderError
from ghostcursor.workspace import agents
from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.session import Workspace

GOOD = {
    "name": "Q3 Deck Builder",
    "description": "Builds the quarterly sales deck",
    "goal_template": "Build a {n}-slide sales deck in PowerPoint",
    "apps": ["PowerPoint"],
    "skills": ["powerpoint"],
    "deny": ["Delete"],
    "max_steps": 12,
}


class AgentGateway:
    def __init__(self, draft=GOOD, fail=None):
        self.draft, self.fail, self.envelopes = draft, fail, []

    def complete(self, envelope, system, schema, parse, **kw):
        self.envelopes.append(envelope)
        if self.fail:
            raise self.fail
        return parse(json.dumps(self.draft))


def _ws(tmp_path, draft=GOOD, fail=None):
    return Workspace(
        "agent-topic",
        AgentGateway(draft, fail),
        Brain(tmp_path / "b.sqlite"),
        root=tmp_path / "briefs",
    )


def test_parse_normalises_the_name_and_keeps_fields():
    s = agents.parse_agent(json.dumps(GOOD))
    assert s.name == "q3-deck-builder" and s.apps == ("PowerPoint",)
    assert s.skills == ("powerpoint",) and s.max_steps == 12


@pytest.mark.parametrize(
    "bad",
    [
        {**GOOD, "max_steps": 0},
        {**GOOD, "max_steps": True},
        {**GOOD, "name": "!!!"},
        {k: v for k, v in GOOD.items() if k != "deny"},
        {**GOOD, "extra": 1},
    ],
)
def test_a_malformed_draft_is_refused(bad):
    with pytest.raises(ProviderError):
        agents.parse_agent(json.dumps(bad))


def test_the_auto_test_catches_unknown_guides_and_risky_goals_without_deny():
    unknown = agents.parse_agent(json.dumps({**GOOD, "skills": ["nope"]}))
    assert any("unknown guide" in i for i in agents.test_agent(unknown))
    risky = agents.parse_agent(
        json.dumps({**GOOD, "goal_template": "send the report", "deny": []})
    )
    assert any("never touch" in i for i in agents.test_agent(risky))
    assert agents.test_agent(agents.parse_agent(json.dumps(GOOD))) == []


def test_save_is_gated_by_the_auto_test_and_round_trips(tmp_path):
    root = tmp_path / "r"
    good = agents.parse_agent(json.dumps(GOOD))
    agents.save(root, good)
    assert [s.name for s in agents.list_specs(root)] == ["q3-deck-builder"]
    assert agents.load(root, "q3-deck-builder").goal_template == GOOD["goal_template"]
    risky = agents.parse_agent(
        json.dumps({**GOOD, "name": "mailer", "goal_template": "send it", "deny": []})
    )
    with pytest.raises(ValueError, match="not ready"):
        agents.save(root, risky)
    assert [s.name for s in agents.list_specs(root)] == ["q3-deck-builder"]
    agents.delete(root, "q3-deck-builder")
    assert agents.list_specs(root) == []


def test_a_corrupt_registry_file_is_skipped_not_fatal(tmp_path):
    root = tmp_path / "r"
    agents.save(root, agents.parse_agent(json.dumps(GOOD)))
    (root / "agents" / "broken.json").write_text("{not json", encoding="utf-8")
    assert [s.name for s in agents.list_specs(root)] == ["q3-deck-builder"]


def test_the_session_drafts_tests_and_saves(tmp_path):
    ws = _ws(tmp_path)
    spec = ws.create_agent("I need a helper that builds my quarterly deck")
    assert spec.name == "q3-deck-builder" and ws.draft_agent is spec
    assert ws.turns[-1].text.startswith("[agent draft]")
    ws.save_agent()
    assert [s.name for s in ws.agents()] == ["q3-deck-builder"]


def test_the_session_will_not_save_a_failing_draft(tmp_path):
    ws = _ws(tmp_path, draft={**GOOD, "goal_template": "delete old files", "deny": []})
    ws.create_agent("clean up my files")
    with pytest.raises(ValueError, match="not ready"):
        ws.save_agent()


def test_no_model_means_no_draft(tmp_path):
    ws = _ws(tmp_path, fail=ProviderError(FailureKind.UNAVAILABLE))
    assert ws.create_agent("anything") is None and ws.draft_agent is None


def test_use_agent_fills_the_goal_and_applies_the_deny_list(tmp_path):
    ws = _ws(tmp_path)
    ws.create_agent("deck builder")
    ws.save_agent()
    spec = ws.use_agent("q3-deck-builder", {"n": "8"})
    assert spec.name == "q3-deck-builder"
    assert ws.goal == "Build a 8-slide sales deck in PowerPoint"  # slot filled
    assert ws.active_deny == ("Delete",)  # Act will prefer this


def test_use_agent_leaves_unknown_slots_as_text(tmp_path):
    ws = _ws(tmp_path, draft={**GOOD, "goal_template": "Email {who} the {what}", "deny": ["Send"]})
    ws.create_agent("mailer")
    ws.save_agent()
    ws.use_agent("q3-deck-builder", {"who": "Bob"})
    assert ws.goal == "Email Bob the {what}"  # missing slot preserved, not crashed


def test_use_a_missing_agent_is_refused(tmp_path):
    with pytest.raises(ValueError, match="no agent"):
        _ws(tmp_path).use_agent("ghost")
