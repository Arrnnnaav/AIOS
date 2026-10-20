"""Agent crew orchestration (D186): the manager pattern, governed.

Two things matter and are pinned here:
  1. the crew plan is strictly parsed (closed schema, bounded, ordered), and
  2. the orchestrator runs each step through the SAME dispatch the one-step
     router uses, in order, and a 'plan' step only proposes -- it never acts.

No model and no real effects: a fake gateway returns a fixed crew plan, and a
fake workspace records which intents were dispatched.
"""

from __future__ import annotations

import pytest

from ghostcursor.providers.errors import FailureKind, ProviderError
from ghostcursor.providers.schemas import MAX_CREW_STEPS, parse_crew_plan
from ghostcursor.workspace import crew


def test_parse_crew_plan_is_strict_and_ordered():
    text = '{"steps": [{"intent": "research", "argument": "X"}, {"intent": "deck", "argument": "Y"}]}'
    assert parse_crew_plan(text) == (("research", "X"), ("deck", "Y"))


def test_parse_crew_plan_rejects_bad_shapes():
    for bad in (
        '{"steps": []}',  # empty
        '{"steps": [{"intent": "research"}]}',  # missing argument
        '{"steps": [{"intent": "mine_bitcoin", "argument": "x"}]}',  # not a capability
        '{"steps": [{"intent": "research", "argument": "x", "extra": 1}]}',  # extra key
        '{"plan": []}',  # wrong top key
    ):
        with pytest.raises(ProviderError) as exc:
            parse_crew_plan(bad)
        assert exc.value.kind is FailureKind.INVALID_OUTPUT


def test_parse_crew_plan_caps_steps():
    many = ", ".join(
        '{"intent": "chat", "argument": "x"}' for _ in range(MAX_CREW_STEPS + 1)
    )
    with pytest.raises(ProviderError):
        parse_crew_plan('{"steps": [' + many + "]}")


class _FakeGateway:
    def __init__(self, steps):
        self._steps = steps

    def complete(self, envelope, system, schema, parser, *, purpose):
        import json

        return parser(
            json.dumps(
                {"steps": [{"intent": i, "argument": a} for i, a in self._steps]}
            )
        )


class _FakeWorkspace:
    """Records dispatched intents; a 'plan' step only proposes (sets a flag)."""

    def __init__(self, gateway):
        self.gateway = gateway
        self.dispatched = []
        self.proposed = False

    def _run_intent(self, intent, arg, *, fallback=""):
        self.dispatched.append((intent, arg))
        if intent == "plan":
            self.proposed = True
            return "✨ [plan] proposed (needs approval)"
        return f"[{intent}] ran on {arg}"


def test_run_crew_runs_steps_in_order_and_only_proposes_plans():
    plan = [("research", "market"), ("deck", "pitch"), ("plan", "open PowerPoint")]
    ws = _FakeWorkspace(_FakeGateway(plan))
    result = crew.run_crew(ws, "build a pitch")
    assert ws.dispatched == plan  # same order, same dispatch path
    assert ws.proposed is True and len(result.results) == 3
    assert "build a pitch" in result.as_text()


def test_run_crew_degrades_to_one_research_step_without_a_model():
    class _NoModel:
        def complete(self, *a, **k):
            raise ProviderError(FailureKind.UNAVAILABLE, "no model")

    ws = _FakeWorkspace(_NoModel())
    result = crew.run_crew(ws, "some goal")
    assert ws.dispatched == [("research", "some goal")]
    assert len(result.results) == 1


def test_saved_crew_round_trips_and_replays_without_a_model(tmp_path):
    steps = (("research", "market"), ("deck", "pitch"))
    path = crew.save_crew(tmp_path, "Pitch Builder", steps)
    assert path.stem == "pitch-builder"
    assert crew.list_crews(tmp_path) == ["pitch-builder"]
    assert crew.load_crew(tmp_path, "pitch-builder") == steps

    # replaying a saved crew must NOT call the model (steps supplied verbatim)
    class _NoModel:
        def complete(self, *a, **k):
            raise AssertionError("a saved crew must not re-plan")

    ws = _FakeWorkspace(_NoModel())
    result = crew.run_crew(
        ws, "pitch-builder", steps=crew.load_crew(tmp_path, "pitch-builder")
    )
    assert ws.dispatched == list(steps)
    assert len(result.results) == 2


def test_crew_name_and_missing_and_corrupt_are_handled(tmp_path):
    # traversal chars are stripped to a clean slug under the crews dir, not escaped
    path = crew.save_crew(tmp_path, "../escape", (("chat", "x"),))
    assert path.stem == "escape" and path.parent == crew._dir(tmp_path)
    with pytest.raises(ValueError):
        crew.save_crew(tmp_path, "!!!", (("chat", "x"),))  # slugs to empty
    with pytest.raises(ValueError):
        crew.save_crew(tmp_path, "ok", ())  # empty crew
    with pytest.raises(ValueError):
        crew.load_crew(tmp_path, "nope")  # missing
    bad = crew._dir(tmp_path)
    bad.mkdir(parents=True, exist_ok=True)
    (bad / "rot.json").write_text('{"steps": [{"intent": "bad"}]}', encoding="utf-8")
    with pytest.raises(ValueError):
        crew.load_crew(tmp_path, "rot")  # re-validated, refused
