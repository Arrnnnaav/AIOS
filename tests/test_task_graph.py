from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
import json

import pytest

from ghostcursor.task_graph import (
    MAX_GRAPH_NODES,
    CapabilityRegistry,
    CapabilitySpec,
    GraphValidationCode,
    ParameterKind,
    ParameterSpec,
    TaskEdge,
    TaskGraph,
    TaskGraphValidationError,
    TaskNode,
    load_capability_registry,
    validate_task_graph,
)


SHA = "a" * 64
PLUGIN = "ghostcursor.powerpoint"


def _registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        plugin_id=PLUGIN,
        plugin_version="1.0.0",
        catalog_sha256=SHA,
        catalog_generation=7,
        capabilities=MappingProxyType(
            {
                "CREATE_DECK": CapabilitySpec(
                    capability_id="CREATE_DECK",
                    intent_id="CREATE_DECK",
                    authorization_goal="Create a presentation",
                    postconditions=("deck.exists",),
                    parameters=MappingProxyType(
                        {
                            "title": ParameterSpec(
                                ParameterKind.STRING,
                                allowed_values=("Quarterly review", "Project update"),
                            )
                        }
                    ),
                ),
                "ADD_SLIDE": CapabilitySpec(
                    capability_id="ADD_SLIDE",
                    intent_id="ADD_SLIDE",
                    authorization_goal="Add a slide",
                    preconditions=("deck.exists",),
                    postconditions=("slide.exists",),
                    parameters=MappingProxyType(
                        {
                            "layout": ParameterSpec(
                                ParameterKind.STRING,
                                allowed_values=("title", "content"),
                            )
                        }
                    ),
                    safe_to_repeat=True,
                ),
                "SET_SLIDE_TITLE": CapabilitySpec(
                    capability_id="SET_SLIDE_TITLE",
                    intent_id="SET_SLIDE_TITLE",
                    authorization_goal="Set the slide title",
                    preconditions=("slide.exists",),
                    postconditions=("slide.title_set",),
                    parameters=MappingProxyType(
                        {"text": ParameterSpec(ParameterKind.STRING)}
                    ),
                    safe_to_repeat=True,
                ),
                "SAVE_DECK": CapabilitySpec(
                    capability_id="SAVE_DECK",
                    intent_id="SAVE_DECK",
                    authorization_goal="Save the presentation",
                    preconditions=("slide.title_set",),
                    postconditions=("deck.saved",),
                ),
            }
        ),
    )


def _node(node_id: str, capability_id: str, **parameters) -> TaskNode:
    return TaskNode(node_id, PLUGIN, capability_id, parameters)


def _valid_graph() -> TaskGraph:
    return TaskGraph(
        plugin_id=PLUGIN,
        plugin_version="1.0.0",
        nodes=(
            _node("create", "CREATE_DECK", title="Quarterly review"),
            _node("slide", "ADD_SLIDE", layout="title"),
            _node("title", "SET_SLIDE_TITLE", text="Results"),
            _node("save", "SAVE_DECK"),
        ),
        edges=(
            TaskEdge("create", "slide"),
            TaskEdge("slide", "title"),
            TaskEdge("title", "save"),
        ),
    )


def _rejected(graph, code, *, registry=None, initial_facts=()):
    with pytest.raises(TaskGraphValidationError) as caught:
        validate_task_graph(
            graph,
            registry or _registry(),
            initial_facts=initial_facts,
        )
    assert caught.value.code is code
    assert caught.value.phase == "validation"
    return caught.value


def test_a_valid_graph_is_wholly_checked_and_flattened_deterministically():
    validated = validate_task_graph(_valid_graph(), _registry())

    assert [node.node_id for node in validated.ordered_nodes] == [
        "create",
        "slide",
        "title",
        "save",
    ]
    assert validated.plugin_id == PLUGIN
    assert validated.catalog_sha256 == SHA
    assert len(validated.registry_sha256) == 64
    assert len(validated.graph_sha256) == 64


def test_graph_validation_is_order_independent_but_digest_preserves_the_proposal():
    graph = _valid_graph()
    reordered = replace(
        graph,
        nodes=tuple(reversed(graph.nodes)),
        edges=tuple(reversed(graph.edges)),
    )
    first = validate_task_graph(graph, _registry())
    second = validate_task_graph(reordered, _registry())

    assert first.ordered_nodes == second.ordered_nodes
    assert first.graph_sha256 == second.graph_sha256


def test_cycle_rejects_the_entire_graph_before_any_node_can_run():
    graph = replace(
        _valid_graph(),
        edges=(*_valid_graph().edges, TaskEdge("title", "create")),
    )
    _rejected(graph, GraphValidationCode.CYCLE)


def test_a_self_cycle_is_rejected_as_a_cycle():
    graph = replace(
        _valid_graph(),
        edges=(*_valid_graph().edges, TaskEdge("save", "save")),
    )
    _rejected(graph, GraphValidationCode.CYCLE)


def test_cross_plugin_nodes_are_forbidden_even_when_the_capability_name_is_known():
    graph = replace(
        _valid_graph(),
        nodes=(replace(_valid_graph().nodes[0], plugin_id="ghostcursor.excel"),),
        edges=(),
    )
    _rejected(graph, GraphValidationCode.WRONG_PLUGIN)


def test_graph_and_registry_plugin_versions_must_match_exactly():
    graph = replace(_valid_graph(), plugin_version="2.0.0")
    _rejected(graph, GraphValidationCode.WRONG_PLUGIN)


def test_a_fictional_capability_is_rejected_not_interpreted():
    graph = TaskGraph(
        PLUGIN,
        "1.0.0",
        (_node("invented", "MAKE_IT_BEAUTIFUL"),),
        (),
    )
    _rejected(graph, GraphValidationCode.UNKNOWN_CAPABILITY)


def test_unknown_missing_wrong_type_and_unapproved_parameters_are_rejected():
    base = _valid_graph()
    create = base.nodes[0]
    cases = (
        replace(create, parameters={"title": "Quarterly review", "theme": "blue"}),
        replace(create, parameters={}),
        replace(create, parameters={"title": 7}),
        replace(create, parameters={"title": "Unreviewed title"}),
    )
    for node in cases:
        graph = TaskGraph(PLUGIN, "1.0.0", (node,), ())
        _rejected(graph, GraphValidationCode.INVALID_PARAMETER)


def test_boolean_is_not_silently_accepted_as_an_integer():
    registry = _registry()
    capabilities = dict(registry.capabilities)
    capabilities["SET_COUNT"] = CapabilitySpec(
        capability_id="SET_COUNT",
        intent_id="SET_COUNT",
        authorization_goal="Set the count",
        parameters=MappingProxyType(
            {"count": ParameterSpec(ParameterKind.INTEGER)}
        ),
    )
    registry = replace(registry, capabilities=MappingProxyType(capabilities))
    graph = TaskGraph(
        PLUGIN,
        "1.0.0",
        (_node("count", "SET_COUNT", count=True),),
        (),
    )
    _rejected(graph, GraphValidationCode.INVALID_PARAMETER, registry=registry)


def test_non_finite_numbers_are_rejected():
    registry = _registry()
    capabilities = dict(registry.capabilities)
    capabilities["SET_SCALE"] = CapabilitySpec(
        capability_id="SET_SCALE",
        intent_id="SET_SCALE",
        authorization_goal="Set the scale",
        parameters=MappingProxyType(
            {"scale": ParameterSpec(ParameterKind.NUMBER)}
        ),
    )
    registry = replace(registry, capabilities=MappingProxyType(capabilities))
    graph = TaskGraph(
        PLUGIN,
        "1.0.0",
        (_node("scale", "SET_SCALE", scale=float("nan")),),
        (),
    )
    _rejected(graph, GraphValidationCode.INVALID_PARAMETER, registry=registry)


def test_duplicate_non_repeatable_capability_rejects_even_with_different_node_ids():
    graph = TaskGraph(
        PLUGIN,
        "1.0.0",
        (
            _node("first-save", "SAVE_DECK"),
            _node("second-save", "SAVE_DECK"),
        ),
        (),
    )
    _rejected(graph, GraphValidationCode.DUPLICATE_NON_REPEATABLE)


def test_a_capability_explicitly_safe_to_repeat_may_appear_twice():
    graph = TaskGraph(
        PLUGIN,
        "1.0.0",
        (
            _node("first-slide", "ADD_SLIDE", layout="title"),
            _node("second-slide", "ADD_SLIDE", layout="content"),
        ),
        (TaskEdge("first-slide", "second-slide"),),
    )
    validated = validate_task_graph(
        graph,
        _registry(),
        initial_facts=("deck.exists",),
    )
    assert [node.node_id for node in validated.ordered_nodes] == [
        "first-slide",
        "second-slide",
    ]


def test_a_producer_without_a_dependency_edge_does_not_satisfy_a_precondition():
    graph = TaskGraph(
        PLUGIN,
        "1.0.0",
        (
            _node("create", "CREATE_DECK", title="Project update"),
            _node("slide", "ADD_SLIDE", layout="content"),
        ),
        (),
    )
    rejected = _rejected(graph, GraphValidationCode.UNSATISFIED_PRECONDITION)
    assert rejected.node_id == "slide"


def test_trusted_initial_facts_can_satisfy_a_root_precondition():
    graph = TaskGraph(
        PLUGIN,
        "1.0.0",
        (_node("slide", "ADD_SLIDE", layout="content"),),
        (),
    )
    validated = validate_task_graph(
        graph,
        _registry(),
        initial_facts=("deck.exists",),
    )
    assert validated.ordered_nodes[0].node_id == "slide"
    assert validated.initial_facts == ("deck.exists",)


def test_the_validation_digest_binds_the_trusted_initial_facts():
    graph = TaskGraph(
        PLUGIN,
        "1.0.0",
        (_node("slide", "ADD_SLIDE", layout="content"),),
        (),
    )
    first = validate_task_graph(
        graph,
        _registry(),
        initial_facts=("deck.exists",),
    )
    second = validate_task_graph(
        graph,
        _registry(),
        initial_facts=("deck.exists", "user.confirmed"),
    )

    assert first.graph_sha256 == second.graph_sha256
    assert first.validation_sha256 != second.validation_sha256


def test_duplicate_nodes_edges_and_edges_to_unknown_nodes_are_distinct_rejections():
    node = _node("create", "CREATE_DECK", title="Project update")
    _rejected(
        TaskGraph(PLUGIN, "1.0.0", (node, node), ()),
        GraphValidationCode.DUPLICATE_NODE,
    )
    _rejected(
        TaskGraph(
            PLUGIN,
            "1.0.0",
            (node,),
            (TaskEdge("create", "create"), TaskEdge("create", "create")),
        ),
        GraphValidationCode.DUPLICATE_EDGE,
    )
    _rejected(
        TaskGraph(
            PLUGIN,
            "1.0.0",
            (node,),
            (TaskEdge("create", "missing"),),
        ),
        GraphValidationCode.UNKNOWN_NODE,
    )


def test_graph_size_is_bounded_before_topological_processing():
    nodes = tuple(
        _node(f"node-{index}", "ADD_SLIDE", layout="content")
        for index in range(MAX_GRAPH_NODES + 1)
    )
    graph = TaskGraph(PLUGIN, "1.0.0", nodes, ())
    _rejected(graph, GraphValidationCode.LIMIT_EXCEEDED)


def test_validated_parameters_are_immutable_copies():
    parameters = {"title": "Quarterly review"}
    graph = TaskGraph(
        PLUGIN,
        "1.0.0",
        (TaskNode("create", PLUGIN, "CREATE_DECK", parameters),),
        (),
    )
    validated = validate_task_graph(graph, _registry())
    parameters["title"] = "changed after validation"

    assert validated.ordered_nodes[0].parameters["title"] == "Quarterly review"
    with pytest.raises(TypeError):
        validated.ordered_nodes[0].parameters["title"] = "mutation"


def test_capability_registry_digest_changes_with_composition_contract():
    first = validate_task_graph(_valid_graph(), _registry())
    registry = _registry()
    capabilities = dict(registry.capabilities)
    capabilities["ADD_SLIDE"] = replace(
        capabilities["ADD_SLIDE"],
        postconditions=("slide.exists", "slide.selected"),
    )
    changed = validate_task_graph(
        _valid_graph(),
        replace(registry, capabilities=MappingProxyType(capabilities)),
    )

    assert first.registry_sha256 != changed.registry_sha256


def test_malformed_registry_booleans_fail_as_registry_errors():
    registry = _registry()
    capabilities = dict(registry.capabilities)
    capabilities["SAVE_DECK"] = replace(
        capabilities["SAVE_DECK"],
        safe_to_repeat=1,
    )
    _rejected(
        _valid_graph(),
        GraphValidationCode.INVALID_REGISTRY,
        registry=replace(registry, capabilities=MappingProxyType(capabilities)),
    )


def test_non_mapping_node_parameters_fail_closed_with_a_stable_code():
    graph = TaskGraph(
        PLUGIN,
        "1.0.0",
        (TaskNode("create", PLUGIN, "CREATE_DECK", []),),
        (),
    )
    _rejected(graph, GraphValidationCode.INVALID_PARAMETER)


def _artifact(**changes) -> bytes:
    value = {
        "schema_version": 1,
        "plugin_id": PLUGIN,
        "plugin_version": "1.0.0",
        "capabilities": {
            "ADD_SLIDE": {
                "authorization_goal": "Add a slide",
                "intent_id": "ADD_SLIDE",
                "preconditions": ["deck.exists"],
                "postconditions": ["slide.exists"],
                "safe_to_repeat": True,
                "parameters": {
                    "layout": {
                        "kind": "string",
                        "required": True,
                        "allowed_values": ["title", "content"],
                    }
                },
            }
        },
    }
    value.update(changes)
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def test_signed_capability_artifact_parses_into_the_same_bounded_registry():
    registry = load_capability_registry(
        _artifact(),
        plugin_id=PLUGIN,
        plugin_version="1.0.0",
        catalog_sha256=SHA,
        catalog_generation=7,
    )
    capability = registry.capabilities["ADD_SLIDE"]
    assert capability.intent_id == "ADD_SLIDE"
    assert capability.authorization_goal == "Add a slide"
    assert capability.parameters["layout"].allowed_values == ("title", "content")


def test_capability_artifact_identity_extra_fields_and_noncanonical_bytes_fail_closed():
    cases = (
        (_artifact(plugin_id="ghostcursor.other"), "identity"),
        (_artifact(extra=True), "fields"),
        (_artifact() + b"\n", "canonical"),
    )
    for raw, message in cases:
        with pytest.raises(TaskGraphValidationError, match=message):
            load_capability_registry(
                raw,
                plugin_id=PLUGIN,
                plugin_version="1.0.0",
                catalog_sha256=SHA,
                catalog_generation=7,
            )


def test_capability_artifact_duplicate_keys_are_rejected_before_interpretation():
    raw = _artifact().replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
    with pytest.raises(TaskGraphValidationError, match="repeats key"):
        load_capability_registry(
            raw,
            plugin_id=PLUGIN,
            plugin_version="1.0.0",
            catalog_sha256=SHA,
            catalog_generation=7,
        )


def test_the_core_graph_vocabulary_contains_no_application_specific_branches():
    import inspect
    import ghostcursor.task_graph as module

    source = inspect.getsource(module).casefold()
    for application_word in ("powerpoint", "excel", "vscode", "sap"):
        assert application_word not in source



def test_a_huge_integer_number_is_refused_not_an_overflow():
    from ghostcursor.task_graph import _scalar_matches

    assert _scalar_matches(ParameterKind.NUMBER, 10**400) is False


@pytest.mark.parametrize("field", ["capability_id", "intent_id"])
def test_a_non_string_capability_id_is_a_refusal_not_a_type_error(field):
    registry = _registry()
    key = next(iter(registry.capabilities))
    spec = replace(registry.capabilities[key], **{field: 7})
    caps = {**registry.capabilities, key: spec}
    if field == "capability_id":
        caps = {**registry.capabilities, key: spec}
    bad = replace(registry, capabilities=MappingProxyType(caps))
    with pytest.raises(TaskGraphValidationError):
        validate_task_graph(TaskGraph(PLUGIN, "1.0.0", (), ()), bad)
