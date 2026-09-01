from __future__ import annotations

import hashlib
from types import MappingProxyType

import pytest

from ghostcursor.action import (
    ActionEdge,
    ActionGraph,
    ActionNode,
    ActionParameterSpec,
    ActionRisk,
    ActionValidationCode,
    ActionValidationError,
    ActionValueKind,
    OperationRegistry,
    OperationSpec,
    validate_action_graph,
)


PLUGIN = "ghostcursor.powerpoint"
VERSION = "1.0.0"
ADAPTER = "a" * 64


def _registry() -> OperationRegistry:
    return OperationRegistry(
        PLUGIN,
        VERSION,
        ADAPTER,
        "b" * 64,
        MappingProxyType(
            {
                "powerpoint.create_slide": OperationSpec(
                    "powerpoint.create_slide",
                    ActionRisk.NORMAL,
                    MappingProxyType(
                        {
                            "slide_id": ActionParameterSpec(ActionValueKind.STRING),
                            "content": ActionParameterSpec(ActionValueKind.OBJECT),
                        }
                    ),
                    preconditions=("presentation.created",),
                    postconditions=("slide.created",),
                    effect_key_fields=("slide_id",),
                ),
                "powerpoint.create_presentation": OperationSpec(
                    "powerpoint.create_presentation",
                    ActionRisk.NORMAL,
                    MappingProxyType({}),
                    postconditions=("presentation.created",),
                ),
            }
        ),
    )


def _node(node_id: str, slide_id: str) -> ActionNode:
    return ActionNode(
        node_id,
        "powerpoint.create_slide",
        MappingProxyType(
            {"slide_id": slide_id, "content": {"title": f"Slide {slide_id}"}}
        ),
    )


def test_action_graph_is_validated_whole_and_sorted_before_execution():
    graph = ActionGraph(
        PLUGIN,
        VERSION,
        ADAPTER,
        (
            _node("slide-two", "s2"),
            ActionNode("create", "powerpoint.create_presentation"),
            _node("slide-one", "s1"),
        ),
        (
            ActionEdge("create", "slide-one"),
            ActionEdge("slide-one", "slide-two"),
        ),
    )

    validated = validate_action_graph(graph, _registry())

    assert [node.node_id for node in validated.ordered_nodes] == [
        "create",
        "slide-one",
        "slide-two",
    ]
    assert len(validated.graph_sha256) == 64
    with pytest.raises(TypeError):
        validated.ordered_nodes[1].parameters["content"]["title"] = "changed"


def test_cycle_refuses_the_complete_graph():
    graph = ActionGraph(
        PLUGIN,
        VERSION,
        ADAPTER,
        (_node("slide-one", "s1"), _node("slide-two", "s2")),
        (ActionEdge("slide-one", "slide-two"), ActionEdge("slide-two", "slide-one")),
    )

    with pytest.raises(ActionValidationError) as raised:
        validate_action_graph(
            graph, _registry(), initial_facts=("presentation.created",)
        )

    assert raised.value.code is ActionValidationCode.CYCLE


def test_duplicate_non_idempotent_effect_is_rejected_but_distinct_resources_are_valid():
    duplicate = ActionGraph(
        PLUGIN,
        VERSION,
        ADAPTER,
        (_node("slide-one", "s1"), _node("slide-copy", "s1")),
        (ActionEdge("slide-one", "slide-copy"),),
    )
    with pytest.raises(ActionValidationError) as raised:
        validate_action_graph(
            duplicate, _registry(), initial_facts=("presentation.created",)
        )
    assert raised.value.code is ActionValidationCode.DUPLICATE_EFFECT

    distinct = ActionGraph(
        PLUGIN,
        VERSION,
        ADAPTER,
        (_node("slide-one", "s1"), _node("slide-two", "s2")),
        (ActionEdge("slide-one", "slide-two"),),
    )
    assert (
        len(
            validate_action_graph(
                distinct, _registry(), initial_facts=("presentation.created",)
            ).ordered_nodes
        )
        == 2
    )


def test_unknown_operation_and_nested_non_json_values_fail_closed():
    unknown = ActionGraph(
        PLUGIN,
        VERSION,
        ADAPTER,
        (ActionNode("bad", "powerpoint.run_macro"),),
        (),
    )
    with pytest.raises(ActionValidationError) as raised:
        validate_action_graph(unknown, _registry())
    assert raised.value.code is ActionValidationCode.UNKNOWN_OPERATION

    invalid = ActionGraph(
        PLUGIN,
        VERSION,
        ADAPTER,
        (
            ActionNode(
                "bad",
                "powerpoint.create_slide",
                MappingProxyType({"slide_id": "s1", "content": {"bad": object()}}),
            ),
        ),
        (),
    )
    with pytest.raises(ActionValidationError) as raised:
        validate_action_graph(
            invalid, _registry(), initial_facts=("presentation.created",)
        )
    assert raised.value.code is ActionValidationCode.INVALID_PARAMETER


def test_registry_digest_inputs_are_load_bearing():
    graph = ActionGraph(
        PLUGIN,
        VERSION,
        ADAPTER,
        (ActionNode("create", "powerpoint.create_presentation"),),
        (),
    )
    first = validate_action_graph(graph, _registry())
    changed = _registry()
    changed = OperationRegistry(
        changed.plugin_id,
        changed.plugin_version,
        changed.adapter_sha256,
        hashlib.sha256(b"changed").hexdigest(),
        changed.operations,
    )
    second = validate_action_graph(graph, changed)
    assert first.validation_sha256 != second.validation_sha256
