"""MVP workspace gaps closed by D175: evidence inspection, Spatial
confirmation, editable plan proposals bound to the brief, Teach outcomes in
the brief, and replay of recorded model answers (MVP.md "Required quality")."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostcursor.brief import brief_path, load_brief
from ghostcursor.providers.errors import FailureKind, ProviderError
from ghostcursor.providers.schemas import parse_teach_plan
from ghostcursor.workspace.__main__ import confirm_reference
from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.contracts import SpatialContextReference
from ghostcursor.workspace.session import Workspace

REPLAY = json.loads(
    (Path(__file__).parent / "fixtures" / "workspace_replay.json").read_text(
        encoding="utf-8"
    )
)


class ReplayGateway:
    """Answers each call with the next recorded answer."""

    def __init__(self):
        self.answer, self.fail, self.envelopes = None, None, []

    def _give(self, parse):
        if self.fail:
            raise ProviderError(FailureKind(self.fail))
        return parse(json.dumps(self.answer))

    def complete(self, envelope, system, schema, parse, **kw):
        self.envelopes.append(envelope)
        return self._give(parse)

    def plan(self, envelope, **kw):
        self.envelopes.append(envelope)
        return self._give(parse_teach_plan)


def _check(ws, gateway, step, result):
    expect = step.get("expect", {})
    op = step["op"]
    if "scopes" in expect:
        assert {m.text: m.scope for m in ws.brain.list()} == expect["scopes"]
    for text in expect.get("tainted_contains", ()):
        assert text in gateway.envelopes[-1].tainted_json()
    for text in expect.get("trusted_lacks", ()):
        assert text not in json.dumps(gateway.envelopes[-1].trusted)
    if "reply_starts" in expect:
        assert result.startswith(expect["reply_starts"])
    if op == "research":
        graph, trace = result
        assert [c.status.value for c in graph.claims] == expect["statuses"]
        assert list(trace.failures) == expect["failures"]
        graph.validate()
        if "categories" in expect:
            assert [s.category.value for s in graph.sources] == expect["categories"]
        for text in expect.get("evidence_contains", ()):
            assert text in ws.evidence()
        shown = ws.turns[-1].text
        if "shown_starts" in expect:
            assert shown.startswith(expect["shown_starts"])
    if "revision" in expect:
        got = ws.proposal.revision if ws.proposal else None
        assert got == expect["revision"]
    if "steps" in expect:
        assert [s.instruction for s in ws.plan.steps] == expect["steps"]


@pytest.mark.parametrize(
    "scenario", REPLAY["scenarios"], ids=[s["name"] for s in REPLAY["scenarios"]]
)
def test_replay(scenario, tmp_path):
    brain = Brain(tmp_path / "brain.sqlite")
    gateway = ReplayGateway()
    ws = None
    try:
        for step in scenario["steps"]:
            gateway.answer, gateway.fail = step.get("model"), step.get("fail")
            if step.get("topic"):
                ws = Workspace(step["topic"], gateway, brain, root=tmp_path / "briefs")
            elif ws is None:
                ws = Workspace("replay", gateway, brain, root=tmp_path / "briefs")
            op, result = step["op"], None
            if op == "discuss":
                result = ws.discuss(step["message"])
            elif op == "research":
                shown = ws.research(
                    step["question"],
                    search=lambda q, hits=step["hits"]: hits,
                    key_lookup=lambda n: None,
                    trace_path=tmp_path / "trace.jsonl",
                )
                result = (ws.research_graphs[-1], _last_trace(tmp_path))
                for text in step["expect"].get("shown_contains", ()):
                    assert text in shown
            elif op == "plan":
                ws.make_plan()
            elif op == "plan_edit":
                if "error" in step["expect"]:
                    with pytest.raises(ValueError, match=step["expect"]["error"]):
                        ws.edit_plan(step["verb"], step["args"])
                else:
                    ws.edit_plan(step["verb"], step["args"])
            _check(ws, gateway, step, result)
    finally:
        brain.close()


def _last_trace(tmp_path):
    from ghostcursor.workspace.contracts import ResearchTrace

    line = (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    return ResearchTrace(**json.loads(line))


# --- plan proposals --------------------------------------------------------------


@pytest.fixture
def planned(tmp_path):
    brain = Brain(tmp_path / "brain.sqlite")
    gateway = ReplayGateway()
    ws = Workspace("p", gateway, brain, root=tmp_path / "briefs")
    gateway.answer = {"reply": "ok", "memories": []}
    ws.discuss("Add a title slide")
    gateway.answer = {
        "steps": [
            {"instruction": "Open Home", "expected_change": "chosen_state_changes"},
            {"instruction": "Click New Slide", "expected_change": "chosen_disappears"},
        ]
    }
    ws.make_plan()
    yield ws
    brain.close()


def test_a_proposal_binds_the_brief_bytes_it_was_made_from(planned):
    first = planned.proposal
    # The proposal's turn is appended after binding, so the bound digest is
    # the brief as it was before -- and differs from the brief now.
    now = load_brief(brief_path(planned.root, planned.topic)).sha256
    assert first.brief_sha256 and first.brief_sha256 != now
    second = planned.edit_plan("add", ["Type", "a", "title"])
    assert second.brief_sha256 == now and second.revision == first.revision + 1
    assert second.digest() != first.digest()
    assert planned.turns[-1].text.startswith(
        f"[plan r2, a proposal {second.digest()[:12]}]"
    )


@pytest.mark.parametrize(
    "verb, args",
    [
        ("edit", ["3", "x"]),
        ("edit", ["0", "x"]),
        ("drop", ["9"]),
        ("drop", ["x"]),
        ("edit", ["1"]),
        ("add", []),
        ("add", ["x" * 201]),
        ("move", ["1"]),
    ],
)
def test_bad_edits_are_refused_and_keep_the_proposal(planned, verb, args):
    before = planned.proposal
    with pytest.raises(ValueError):
        planned.edit_plan(verb, args)
    assert planned.proposal is before


def test_a_plan_never_grows_past_the_step_cap(planned):
    for _ in range(18):
        planned.edit_plan("add", ["step"])
    with pytest.raises(ValueError, match="1 to 20"):
        planned.edit_plan("add", ["one", "too", "many"])


def test_edits_need_a_plan(tmp_path):
    brain = Brain(tmp_path / "b.sqlite")
    ws = Workspace("np", ReplayGateway(), brain, root=tmp_path)
    with pytest.raises(ValueError, match="no plan"):
        ws.edit_plan("add", ["x"])
    brain.close()


def test_teach_starts_from_the_latest_revision_and_its_outcome_is_recorded(planned):
    planned.edit_plan("edit", ["2", "Click", "Blank", "Slide"])
    assert [s.instruction for s in planned.teach_plan(2).steps] == ["Click Blank Slide"]
    line = planned.record_teach(2, [(1, "you confirmed")], 0)
    assert line == "[teach r2] step 2 done (you confirmed); ended"
    assert planned.turns[-1].text == line
    assert planned.record_teach(1, [], 3).endswith(
        "no step done; stopped: a window changed"
    )
    assert planned.record_teach(1, [], 2).endswith("; blocked")


# --- evidence and Spatial confirmation ------------------------------------------


def test_evidence_shows_cited_passages_and_bounds_its_index(planned):
    assert planned.evidence() == "no such research answer"
    planned.gateway.answer = {
        "claims": [
            {"text": "A", "status": "supported", "evidence": ["p1"]},
            {"text": "B", "status": "unresolved", "evidence": []},
        ]
    }
    planned.research(
        "q",
        search=lambda q: [
            {"url": "https://a.org/x", "title": "A", "passages": ["alpha"]}
        ],
        key_lookup=lambda n: None,
        trace_path=planned.root / "t.jsonl",
    )
    shown = planned.evidence(1)
    assert '"alpha"' in shown and "https://a.org/x" in shown
    assert "(no passage cited)" in shown
    assert planned.evidence(2) == "no such research answer"


REF = SpatialContextReference(
    "point", "Insert", "TabItem", "powerpnt.exe", 0.6, ("Ribbon", "Tabs")
)


def test_the_user_keeps_picks_or_discards_the_resolution():
    assert confirm_reference(REF, "") is REF
    chosen = confirm_reference(REF, "2")
    assert (chosen.name, chosen.confidence, chosen.alternatives) == ("Tabs", 1.0, ())
    assert "user chose" in chosen.as_text()
    for answer in ("x", "0", "3", "no"):
        assert confirm_reference(REF, answer) is None


@pytest.mark.parametrize(
    "goal, topic",
    [
        ("Make my Investor Deck!", "make-my-investor-deck"),
        ("", "workspace"),
        ("../../etc/passwd", "etc-passwd"),
        ("Café ünïcode — only", "caf-n-code-only"),
        ("a " * 50, "a-a-a-a-a-a"),
    ],
)
def test_the_manager_opens_a_valid_workspace_topic(goal, topic, tmp_path):
    from ghostcursor.manager import workspace_topic

    assert workspace_topic(goal) == topic
    brief_path(tmp_path, topic)  # a valid topic name


def test_measures_count_without_text(planned):
    from ghostcursor.workspace.session import measures

    planned.edit_plan("drop", ["2"])
    planned.record_teach(1, [(1, "you confirmed")], 0)
    planned.gateway.fail = "timeout"
    traces = planned.root / "t.jsonl"
    planned.research(
        "secret question",
        search=lambda q: [{"url": "https://a.org/x", "title": "A", "passages": ["p"]}],
        key_lookup=lambda n: None,
        trace_path=traces,
    )
    traces.write_text(traces.read_text() + "not json\n")
    got = measures(planned.brain, planned.root, traces)
    assert got["research_answers"] == 1 and got["provider_failures"] == {"model": 1}
    assert (got["plan_proposals"], got["plan_revisions"]) == (2, 1)
    assert (got["teach_runs"], got["teach_steps_done"]) == (1, 1)
    sent = json.dumps(got)
    assert "secret" not in sent and "title slide" not in sent.lower()
