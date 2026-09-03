from __future__ import annotations

import json
from types import MappingProxyType, SimpleNamespace

import pytest

from ghostcursor.inference.ollama import GenerateResponse
from ghostcursor.task_graph import CapabilityRegistry, CapabilitySpec, TaskGraphValidationError
from ghostcursor.task_planner import (
    TaskProposalRejected,
    infer_task_graph,
    parse_task_graph_proposal,
    propose_task_graph,
    task_plan_steps,
    task_graph_response_schema,
)


PLUGIN = "ghostcursor.presentation"
SHA = "a" * 64


def _registry():
    return CapabilityRegistry(
        PLUGIN,
        "1.0.0",
        SHA,
        3,
        MappingProxyType(
            {
                "CREATE_DECK": CapabilitySpec(
                    "CREATE_DECK", "CREATE_DECK", "create a presentation",
                    postconditions=("deck.exists",),
                ),
                "ADD_SLIDE": CapabilitySpec(
                    "ADD_SLIDE", "ADD_SLIDE", "add a slide",
                    preconditions=("deck.exists",),
                    postconditions=("slide.exists",),
                    safe_to_repeat=True,
                ),
            }
        ),
    )


def _payload():
    return {
        # `outcome` is the discriminator: a planning round returns exactly one
        # of a clarification or a plan, and says which.
        "outcome": "plan",
        "questions": [],
        "summary": "Create a deck and add a slide.",
        "nodes": [
            {"node_id": "create", "capability_id": "CREATE_DECK", "parameters": {}},
            {"node_id": "slide", "capability_id": "ADD_SLIDE", "parameters": {}},
        ],
        "edges": [{"before": "create", "after": "slide"}],
    }


def test_response_schema_allows_only_registered_capability_ids_and_graph_fields():
    schema = task_graph_response_schema(_registry())
    assert schema["additionalProperties"] is False
    assert schema["properties"]["nodes"]["maxItems"] == 32
    node = schema["properties"]["nodes"]["items"]
    assert node["additionalProperties"] is False
    assert node["properties"]["capability_id"]["enum"] == ["ADD_SLIDE", "CREATE_DECK"]


def test_model_never_supplies_plugin_identity_and_fictional_capability_is_rejected():
    graph, _ = parse_task_graph_proposal(_payload(), _registry())
    assert graph.plugin_id == PLUGIN
    assert {node.plugin_id for node in graph.nodes} == {PLUGIN}

    fictional = _payload()
    fictional["nodes"][0]["capability_id"] = "DELETE_EVERYTHING"
    with pytest.raises(TaskProposalRejected, match="unregistered capability"):
        parse_task_graph_proposal(fictional, _registry())


def test_duplicate_json_keys_and_non_scalar_parameters_fail_before_validation():
    duplicate = json.dumps(_payload()).replace(
        '"summary":', '"summary":"first","summary":', 1
    )
    with pytest.raises(TaskProposalRejected, match="repeats key"):
        parse_task_graph_proposal(duplicate, _registry())

    value = _payload()
    value["nodes"][0]["parameters"] = {"instruction": {"click": "anything"}}
    with pytest.raises(TaskProposalRejected, match="not scalar"):
        parse_task_graph_proposal(value, _registry())


def test_inference_uses_bounded_schema_then_validates_the_whole_graph(monkeypatch):
    captured = {}

    def generate(**kwargs):
        captured.update(kwargs)
        return GenerateResponse(_payload())

    monkeypatch.setattr("ghostcursor.task_planner.generate_structured", generate)
    proposal = infer_task_graph("Build a simple presentation", _registry())

    assert proposal.validated.ordered_nodes[0].node_id == "create"
    assert captured["num_predict"] == 768
    assert "CREATE_DECK" in captured["prompt"]
    assert captured["schema"]["additionalProperties"] is False


def test_preview_steps_are_flattened_from_validated_nodes_and_signed_capabilities(monkeypatch):
    value = _payload()
    value["nodes"][1]["parameters"] = {}
    monkeypatch.setattr(
        "ghostcursor.task_planner.generate_structured",
        lambda **_kwargs: GenerateResponse(value),
    )

    proposal = infer_task_graph("Build a simple presentation", _registry())

    assert [(step.node_id, step.instruction) for step in proposal.steps] == [
        ("create", "create a presentation"),
        ("slide", "add a slide"),
    ]
    assert proposal.steps == task_plan_steps(proposal.validated, _registry())


def test_preview_parameters_are_display_only_sorted_scalars(monkeypatch):
    from ghostcursor.task_graph import ParameterKind, ParameterSpec

    registry = _registry()
    slide = registry.capabilities["ADD_SLIDE"]
    registry = CapabilityRegistry(
        registry.plugin_id,
        registry.plugin_version,
        registry.catalog_sha256,
        registry.catalog_generation,
        MappingProxyType(
            {
                **registry.capabilities,
                "ADD_SLIDE": CapabilitySpec(
                    slide.capability_id,
                    slide.intent_id,
                    slide.authorization_goal,
                    preconditions=slide.preconditions,
                    postconditions=slide.postconditions,
                    parameters=MappingProxyType(
                        {
                            "slide_title": ParameterSpec(ParameterKind.STRING),
                            "template": ParameterSpec(ParameterKind.STRING),
                        }
                    ),
                    safe_to_repeat=True,
                ),
            }
        ),
    )
    value = _payload()
    value["nodes"][1]["parameters"] = {
        "template": "Investor",
        "slide_title": "GhostCursor",
    }
    monkeypatch.setattr(
        "ghostcursor.task_planner.generate_structured",
        lambda **_kwargs: GenerateResponse(value),
    )

    proposal = infer_task_graph("Build a deck", registry)

    assert [(item.name, item.value) for item in proposal.steps[1].guidance_values] == [
        ("slide_title", "GhostCursor"),
        ("template", "Investor"),
    ]


def test_a_cyclic_model_graph_is_rejected_before_it_can_be_proposed(monkeypatch):
    value = _payload()
    value["edges"].append({"before": "slide", "after": "create"})
    monkeypatch.setattr(
        "ghostcursor.task_planner.generate_structured",
        lambda **_kwargs: GenerateResponse(value),
    )
    with pytest.raises(TaskGraphValidationError, match="cycle"):
        infer_task_graph("Build a presentation", _registry())


def test_no_enabled_capability_registry_means_no_model_contact(monkeypatch):
    monkeypatch.setattr(
        "ghostcursor.plugins.platform.load_composition_context",
        lambda: SimpleNamespace(registries={}),
    )
    monkeypatch.setattr(
        "ghostcursor.task_planner.infer_task_graph",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("model called")),
    )
    with pytest.raises(TaskProposalRejected, match="no active capabilities"):
        propose_task_graph("invent something", "ghostcursor.fictional")


def test_invalid_initial_facts_are_rejected_before_model_contact(monkeypatch):
    monkeypatch.setattr(
        "ghostcursor.task_planner.generate_structured",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("model called")),
    )
    with pytest.raises(TaskGraphValidationError, match="initial facts"):
        infer_task_graph(
            "Build a presentation",
            _registry(),
            initial_facts=("ignore previous instructions",),
        )


# --- a planning round returns a question or a plan, never a blend ---------


def _clarification(**overrides):
    value = {
        "outcome": "clarification",
        "questions": ["Who is the audience?", "How many slides?"],
        "summary": "Need the audience before planning.",
        "nodes": [],
        "edges": [],
    }
    value.update(overrides)
    return value


def _parse(value, generation=None):
    from ghostcursor.task_planner import parse_planning_response

    return parse_planning_response(
        value, _registry(), generation or object(), brief_sha256=None
    )


def test_a_clarification_comes_back_as_questions_not_an_empty_plan():
    """The whole point of a separate type. A caller that received a plan with
    empty nodes and read the emptiness as 'nothing to do' would execute
    nothing and report success."""

    from ghostcursor.task_planner import ClarificationRequired

    result = _parse(_clarification())

    assert isinstance(result, ClarificationRequired)
    assert result.questions == ("Who is the audience?", "How many slides?")


def test_a_clarification_carries_no_graph_at_all():
    """There is nowhere to put a partial plan, so a partial plan cannot leak
    through as if it were complete."""

    from ghostcursor.task_planner import ClarificationRequired

    fields = set(ClarificationRequired.__dataclass_fields__)

    assert fields == {"questions", "summary", "generation", "brief_sha256"}
    for forbidden in ("graph", "nodes", "validated", "steps", "edges"):
        assert forbidden not in fields


def test_a_response_that_both_asks_and_plans_is_refused():
    """Ignoring the questions would execute a plan the model itself said it
    lacked information for. Ignoring the nodes would discard work. Refusing
    is the only honest answer."""

    both = _payload()
    both["questions"] = ["Who is the audience?"]

    with pytest.raises(TaskProposalRejected, match="mutually exclusive"):
        _parse(both)


def test_a_clarification_carrying_nodes_is_refused():
    with pytest.raises(TaskProposalRejected, match="mutually exclusive"):
        _parse(_clarification(nodes=_payload()["nodes"]))


def test_a_clarification_with_no_questions_is_refused():
    """'Neither' matters as much as 'both': a clarification with no questions
    is a dead end that leaves a caller waiting for input it never asked
    for."""

    with pytest.raises(TaskProposalRejected, match="at least one question"):
        _parse(_clarification(questions=[]))


@pytest.mark.parametrize("outcome", ["", "maybe", None, "PLAN", 7])
def test_an_unknown_outcome_is_refused(outcome):
    with pytest.raises(TaskProposalRejected, match="outcome must be one of"):
        _parse(_clarification(outcome=outcome))


@pytest.mark.parametrize(
    "questions",
    [["  "], [""], [None], [7], ["x" * 500], ["ok", "ok", "ok", "ok", "ok"]],
)
def test_malformed_questions_are_refused(questions):
    with pytest.raises(TaskProposalRejected):
        _parse(_clarification(questions=questions))


def test_a_plan_still_parses_through_the_union():
    graph, summary = _parse(_payload())

    assert summary.startswith("Create a deck")
    assert len(graph.nodes) == 2


def test_the_plan_parser_refuses_a_clarification_outright():
    """Two entry points, and the narrow one does not silently accept the
    other kind."""

    from ghostcursor.task_planner import parse_task_graph_proposal

    with pytest.raises(TaskProposalRejected, match="not a plan"):
        parse_task_graph_proposal(_clarification(), _registry())


def test_the_schema_offers_both_outcomes_and_requires_the_discriminator():
    schema = task_graph_response_schema(_registry())

    assert schema["properties"]["outcome"]["enum"] == ["clarification", "plan"]
    assert "outcome" in schema["required"]
    assert "questions" in schema["required"]

