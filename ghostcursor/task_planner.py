"""Advisory decomposition of a complex goal into capability-only graph data."""

from __future__ import annotations

import json
from dataclasses import dataclass

from ghostcursor.inference.ollama import DEFAULT_MODEL, GenerateResponse, generate_structured
from ghostcursor.session import GuidanceValue
from ghostcursor.task_graph import (
    MAX_GRAPH_EDGES,
    MAX_GRAPH_NODES,
    MAX_NODE_ID_LENGTH,
    MAX_NODE_PARAMETERS,
    MAX_PARAMETER_STRING_LENGTH,
    CapabilityRegistry,
    TaskEdge,
    TaskGraph,
    TaskNode,
    ValidatedTaskGraph,
    capability_registry_sha256,
    validate_task_graph,
    validate_initial_facts,
)


MAX_TASK_GOAL_CHARS = 1024
MAX_TASK_SUMMARY_CHARS = 512
TASK_GRAPH_NUM_PREDICT = 768


class TaskProposalRejected(ValueError):
    """Model output was not closed capability-graph data."""


@dataclass(frozen=True)
class TaskPlanStep:
    """Inert, signed-authority-derived presentation for one validated node."""

    node_id: str
    capability_id: str
    instruction: str
    guidance_values: tuple[GuidanceValue, ...] = ()


@dataclass(frozen=True)
class TaskGraphProposal:
    graph: TaskGraph
    validated: ValidatedTaskGraph
    summary: str
    generation: GenerateResponse
    steps: tuple[TaskPlanStep, ...]


def task_plan_steps(
    validated: ValidatedTaskGraph,
    registry: CapabilityRegistry,
) -> tuple[TaskPlanStep, ...]:
    """Project the trusted flattened graph without creating new authority."""

    if (
        validated.plugin_id != registry.plugin_id
        or validated.plugin_version != registry.plugin_version
        or validated.registry_sha256 != capability_registry_sha256(registry)
    ):
        raise TaskProposalRejected("validated graph no longer matches its capability registry")
    return tuple(
        TaskPlanStep(
            node_id=node.node_id,
            capability_id=node.capability_id,
            instruction=registry.capabilities[node.capability_id].authorization_goal,
            guidance_values=tuple(
                GuidanceValue(name, value)
                for name, value in sorted(node.parameters.items())
            ),
        )
        for node in validated.ordered_nodes
    )


def task_graph_response_schema(registry: CapabilityRegistry) -> dict:
    capability_ids = sorted(registry.capabilities)
    if not capability_ids:
        raise ValueError("capability registry must not be empty")
    scalar = {
        "type": ["string", "integer", "number", "boolean"],
    }
    return {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_TASK_SUMMARY_CHARS,
            },
            "nodes": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_GRAPH_NODES,
                "items": {
                    "type": "object",
                    "properties": {
                        "node_id": {
                            "type": "string",
                            "maxLength": MAX_NODE_ID_LENGTH,
                            "pattern": "^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$",
                        },
                        "capability_id": {
                            "type": "string",
                            "enum": capability_ids,
                        },
                        "parameters": {
                            "type": "object",
                            "maxProperties": MAX_NODE_PARAMETERS,
                            "additionalProperties": scalar,
                        },
                    },
                    "required": ["node_id", "capability_id", "parameters"],
                    "additionalProperties": False,
                },
            },
            "edges": {
                "type": "array",
                "maxItems": MAX_GRAPH_EDGES,
                "items": {
                    "type": "object",
                    "properties": {
                        "before": {"type": "string"},
                        "after": {"type": "string"},
                    },
                    "required": ["before", "after"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "nodes", "edges"],
        "additionalProperties": False,
    }


def _strict_model_object(raw: object) -> dict:
    if isinstance(raw, str):
        def pairs(items):
            value = {}
            for key, item in items:
                if key in value:
                    raise TaskProposalRejected(f"model response repeats key {key!r}")
                value[key] = item
            return value

        try:
            raw = json.loads(raw, object_pairs_hook=pairs)
        except json.JSONDecodeError as exc:
            raise TaskProposalRejected("model response is not JSON") from exc
    if not isinstance(raw, dict):
        raise TaskProposalRejected("model response must be an object")
    return raw


def parse_task_graph_proposal(
    raw: object,
    registry: CapabilityRegistry,
) -> tuple[TaskGraph, str]:
    """Parse exact model fields; plugin identity never comes from the model."""

    value = _strict_model_object(raw)
    if set(value) != {"summary", "nodes", "edges"}:
        raise TaskProposalRejected("model response has invalid task graph fields")
    summary = value["summary"]
    if (
        not isinstance(summary, str)
        or not summary.strip()
        or len(summary) > MAX_TASK_SUMMARY_CHARS
    ):
        raise TaskProposalRejected("model task summary is invalid")
    nodes_value = value["nodes"]
    edges_value = value["edges"]
    if (
        not isinstance(nodes_value, list)
        or not 1 <= len(nodes_value) <= MAX_GRAPH_NODES
        or not isinstance(edges_value, list)
        or len(edges_value) > MAX_GRAPH_EDGES
    ):
        raise TaskProposalRejected("model task graph exceeds its bounds")

    nodes = []
    for item in nodes_value:
        if not isinstance(item, dict) or set(item) != {
            "node_id", "capability_id", "parameters"
        }:
            raise TaskProposalRejected("model task node fields are invalid")
        capability_id = item["capability_id"]
        if not isinstance(capability_id, str) or capability_id not in registry.capabilities:
            raise TaskProposalRejected("model named an unregistered capability")
        parameters = item["parameters"]
        if not isinstance(parameters, dict) or len(parameters) > MAX_NODE_PARAMETERS:
            raise TaskProposalRejected("model task parameters are invalid")
        for name, parameter in parameters.items():
            if not isinstance(name, str) or type(parameter) not in {str, int, float, bool}:
                raise TaskProposalRejected("model task parameter is not scalar")
            if isinstance(parameter, str) and len(parameter) > MAX_PARAMETER_STRING_LENGTH:
                raise TaskProposalRejected("model task parameter is too long")
        nodes.append(
            TaskNode(
                node_id=item["node_id"],
                plugin_id=registry.plugin_id,
                capability_id=capability_id,
                parameters=parameters,
            )
        )

    edges = []
    for item in edges_value:
        if not isinstance(item, dict) or set(item) != {"before", "after"}:
            raise TaskProposalRejected("model task edge fields are invalid")
        if not isinstance(item["before"], str) or not isinstance(item["after"], str):
            raise TaskProposalRejected("model task edge is invalid")
        edges.append(TaskEdge(item["before"], item["after"]))
    return (
        TaskGraph(
            plugin_id=registry.plugin_id,
            plugin_version=registry.plugin_version,
            nodes=tuple(nodes),
            edges=tuple(edges),
        ),
        summary.strip(),
    )


def _capability_prompt(registry: CapabilityRegistry) -> str:
    rows = []
    for capability_id, capability in sorted(registry.capabilities.items()):
        rows.append(
            {
                "capability_id": capability_id,
                "purpose": capability.authorization_goal,
                "parameters": {
                    name: {
                        "kind": parameter.kind.value,
                        "required": parameter.required,
                        "allowed_values": list(parameter.allowed_values),
                    }
                    for name, parameter in sorted(capability.parameters.items())
                },
                "preconditions": list(capability.preconditions),
                "postconditions": list(capability.postconditions),
                "safe_to_repeat": capability.safe_to_repeat,
            }
        )
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


def infer_task_graph(
    goal: str,
    registry: CapabilityRegistry,
    *,
    initial_facts: tuple[str, ...] = (),
    endpoint: str = "http://127.0.0.1:11434",
    model: str = DEFAULT_MODEL,
    timeout: float = 20.0,
) -> TaskGraphProposal:
    """Ask the model for graph data, then apply the complete trusted validator."""

    if not isinstance(goal, str) or not goal.strip() or len(goal) > MAX_TASK_GOAL_CHARS:
        raise TaskProposalRejected("task goal is invalid")
    # Reject malformed caller state and registry data before either can enter
    # the advisory prompt. The model is not a validator or a recovery path.
    initial_facts = validate_initial_facts(initial_facts)
    capability_registry_sha256(registry)
    prompt = (
        "Decompose the user's goal into a bounded dependency graph using only the "
        "registered capability IDs below. Do not invent capabilities, UI actions, "
        "selectors, instructions, or verification. Return a short summary, nodes, "
        "and dependency edges only. Every required precondition must be provided by "
        "an initial fact or a predecessor node.\n"
        f"Initial facts: {json.dumps(list(initial_facts))}\n"
        f"Capabilities: {_capability_prompt(registry)}\n"
        f"Goal: {goal.strip()}"
    )
    generation = generate_structured(
        endpoint=endpoint,
        model=model,
        prompt=prompt,
        schema=task_graph_response_schema(registry),
        timeout=timeout,
        num_predict=TASK_GRAPH_NUM_PREDICT,
    )
    graph, summary = parse_task_graph_proposal(generation.payload, registry)
    validated = validate_task_graph(graph, registry, initial_facts=initial_facts)
    return TaskGraphProposal(
        graph,
        validated,
        summary,
        generation,
        task_plan_steps(validated, registry),
    )


def propose_task_graph(
    goal: str,
    plugin_id: str,
    *,
    initial_facts: tuple[str, ...] = (),
    endpoint: str = "http://127.0.0.1:11434",
    model: str = DEFAULT_MODEL,
    timeout: float = 20.0,
) -> TaskGraphProposal:
    """Production proposal entry point; an absent plugin never contacts a model."""

    from ghostcursor.plugins.platform import load_composition_context

    context = load_composition_context()
    registry = context.registries.get(plugin_id)
    if registry is None:
        raise TaskProposalRejected(f"plugin {plugin_id!r} has no active capabilities")
    return infer_task_graph(
        goal,
        registry,
        initial_facts=initial_facts,
        endpoint=endpoint,
        model=model,
        timeout=timeout,
    )
