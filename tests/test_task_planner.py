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
