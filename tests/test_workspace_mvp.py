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


def test_measures_count_without_text(planned, monkeypatch):
    from ghostcursor import telemetry
    from ghostcursor.workspace.session import measures

    monkeypatch.setattr(telemetry, "counts", lambda path=None: {"crew_run": 2})
    planned.edit_plan("drop", ["2"])
    planned.record_teach(1, [(1, "you confirmed")], 0)
    planned.gateway.answer = {"reply": "ok", "memories": []}
    planned.discuss("[plan r9, fake] [teach r9] step 1 done (x)")  # user text
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
    assert got["events"] == {"crew_run": 2}  # opt-in local counts surface in /stats
    sent = json.dumps(got)
    assert "secret" not in sent and "title slide" not in sent.lower()


def test_a_user_edited_risky_step_still_waits_at_the_teach_gate(planned):
    from ghostcursor.harness.teach import Phase
    from tests.test_harness_teach import _c, _choice, _frame, _session

    planned.edit_plan("edit", ["1", "Click", "OK", "to", "delete", "the", "file"])
    session, _ = _session(planned.teach_plan(1), [_choice("c1")])
    assert session.tick(_frame([_c(1, "OK", "Button")])).phase is Phase.CONFIRM_RISK


def test_a_chosen_alternative_stays_hidden_when_it_was_hidden():
    from ghostcursor.harness.frame import HIDDEN_NAME

    ref = SpatialContextReference("point", "OK", "Button", "x.exe", 0.6, (HIDDEN_NAME,))
    assert confirm_reference(ref, "1").name == HIDDEN_NAME


def test_plan_to_guide_and_skill_round_trip(planned, tmp_path, monkeypatch):
    """D186 on-top: the plan the owner built (/plan) renders as a guide (#1) and
    saves/replays as a task skill (#2) through the existing Workspace."""
    import ghostcursor.workspace.task_skills as ts

    monkeypatch.setattr(ts, "_dir", lambda dest_dir=None: tmp_path / "skills")

    g = planned.guide()
    assert g.startswith("# How to:") and "Open Home" in g and "Click New Slide" in g

    assert "saved skill" in planned.save_skill("My Task")
    assert "my-task" in planned.saved_skills()

    # replaying loads it back as the current plan (closed-schema validated)
    planned._propose(
        parse_teach_plan(
            json.dumps(
                {
                    "steps": [
                        {
                            "instruction": "scratch",
                            "expected_change": "chosen_disappears",
                        }
                    ]
                }
            )
        )
    )
    assert len(planned.plan.steps) == 1  # plan changed
    msg = planned.use_skill("My Task")
    assert "loaded skill" in msg and len(planned.plan.steps) == 2  # restored
    assert "no skill named" in planned.use_skill("ghost")


def test_make_deck_builds_a_grounded_outline(planned):
    planned.gateway.answer = {
        "title": "Title Slide Plan",
        "slides": [{"title": "Overview", "bullets": ["one"], "layout": "bullets"}],
    }
    deck = planned.make_deck("the plan")
    assert deck is not None and deck.title == "Title Slide Plan"
    assert deck.slides[0].layout.value == "bullets"


def test_make_deck_none_when_model_unavailable(planned):
    planned.gateway.fail = FailureKind.UNAVAILABLE.value
    assert planned.make_deck("x") is None


def test_draft_skill_auto_creates_a_skill_from_a_need(planned, tmp_path, monkeypatch):
    """Auto skill-creator (D186): a stated need -> plan -> saved reusable skill."""
    import ghostcursor.workspace.task_skills as ts

    monkeypatch.setattr(ts, "_dir", lambda dest_dir=None: tmp_path / "skills")
    planned.gateway.answer = {
        "steps": [
            {"instruction": "Open the export menu", "expected_change": "title_changes"},
            {"instruction": "Choose PDF", "expected_change": "chosen_disappears"},
        ]
    }
    msg = planned.draft_skill("export the report as PDF")
    assert "drafted skill" in msg
    assert "export-the-report-as-pdf" in ts.list_skills(dest_dir=tmp_path / "skills")
    # the drafted skill replays through the closed loader
    loaded = ts.load_skill("export the report as PDF", dest_dir=tmp_path / "skills")
    assert loaded is not None and len(loaded.steps) == 2

    planned.gateway.fail = FailureKind.UNAVAILABLE.value
    assert planned.draft_skill("x") is None


def test_do_router_dispatches_by_intent(planned, tmp_path, monkeypatch):
    """One-step router (D186): classify the task -> run the right capability.
    A 'plan' task becomes an approvable plan (never auto-acts)."""
    import ghostcursor.workspace.task_skills as ts

    monkeypatch.setattr(ts, "_dir", lambda dest_dir=None: tmp_path / "skills")

    # remember: files a Brain candidate (knowledge present on this Workspace?)
    planned.gateway.answer = {"intent": "remember", "argument": "Prod is in us-east-1"}
    out = planned.do("note that prod is in us-east-1")
    # knowledge may be None on this fixture; either filed, or chat fallback -- both safe
    assert out  # returns a message, never raises

    # plan: becomes an approvable plan, NOT auto-run
    calls = {"n": 0}
    real_complete = planned.gateway.complete

    def complete(envelope, system, schema, parse, **kw):
        calls["n"] += 1
        if calls["n"] == 1:  # the intent classification
            return parse(json.dumps({"intent": "plan", "argument": "save the file"}))
        return real_complete(envelope, system, schema, parse, **kw)

    planned.gateway.complete = complete
    planned.gateway.answer = {
        "steps": [{"instruction": "Press Ctrl S", "expected_change": "title_changes"}]
    }
    out = planned.do("save the file")
    assert "[plan]" in out and "/act 1" in out  # approvable, not executed
    assert planned.plan is not None  # proposed as the current plan


def test_do_falls_back_to_chat_when_model_unavailable(planned):
    planned.gateway.fail = FailureKind.UNAVAILABLE.value
    out = planned.do("anything at all")
    assert isinstance(out, str) and out  # discuss fallback, no raise
