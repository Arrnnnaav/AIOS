"""Bounded, declarative composition of already-authorized workflow intents.

The graph is deliberately weaker than a workflow recipe.  It may name a
capability and provide bounded scalar parameters, but it cannot carry actions,
selectors, instructions, or verification rules.  Those remain signed plugin
artifacts compiled through the existing trust boundary.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping, TypeAlias


MAX_GRAPH_NODES = 32
MAX_GRAPH_EDGES = 128
MAX_NODE_PARAMETERS = 16
MAX_PARAMETER_STRING_LENGTH = 512
MAX_REGISTRY_CAPABILITIES = 256
MAX_CAPABILITY_FACTS = 32
MAX_ALLOWED_VALUES = 64
MAX_CAPABILITY_ARTIFACT_BYTES = 256 * 1024
MAX_AUTHORIZATION_GOAL_LENGTH = 1024
CAPABILITY_ARTIFACT_PATH = "ghostcursor/capabilities.json"

_PLUGIN_ID_RE = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+")
_VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?")
_CAPABILITY_ID_RE = re.compile(r"[A-Z][A-Z0-9_]*")
_NODE_ID_RE = re.compile(r"[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*")
_FACT_RE = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
_PARAMETER_RE = re.compile(r"[a-z][a-z0-9_]*")

Scalar: TypeAlias = str | int | float | bool


class ParameterKind(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"


class GraphValidationCode(str, Enum):
    INVALID_REGISTRY = "invalid_registry"
    INVALID_GRAPH = "invalid_graph"
    LIMIT_EXCEEDED = "limit_exceeded"
    DUPLICATE_NODE = "duplicate_node"
    DUPLICATE_EDGE = "duplicate_edge"
    UNKNOWN_NODE = "unknown_node"
    WRONG_PLUGIN = "wrong_plugin"
    UNKNOWN_CAPABILITY = "unknown_capability"
    INVALID_PARAMETER = "invalid_parameter"
    DUPLICATE_NON_REPEATABLE = "duplicate_non_repeatable"
    CYCLE = "cycle"
    UNSATISFIED_PRECONDITION = "unsatisfied_precondition"


class TaskGraphValidationError(ValueError):
    """A graph rejected before any workflow is allowed to start."""

    phase = "validation"

    def __init__(
        self,
        code: GraphValidationCode,
        message: str,
        *,
        node_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.node_id = node_id


@dataclass(frozen=True)
class ParameterSpec:
    kind: ParameterKind
    required: bool = True
    allowed_values: tuple[Scalar, ...] = ()


@dataclass(frozen=True)
class CapabilitySpec:
    """Trusted composition metadata for one existing plugin intent."""

    capability_id: str
    intent_id: str
    authorization_goal: str
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    parameters: Mapping[str, ParameterSpec] = field(
        default_factory=lambda: MappingProxyType({})
    )
    safe_to_repeat: bool = False


@dataclass(frozen=True)
class CapabilityRegistry:
    """One plugin/version's complete capability vocabulary."""

    plugin_id: str
    plugin_version: str
    catalog_sha256: str
    catalog_generation: int
    capabilities: Mapping[str, CapabilitySpec]


@dataclass(frozen=True)
class TaskNode:
    node_id: str
    plugin_id: str
    capability_id: str
    parameters: Mapping[str, Scalar] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True, order=True)
class TaskEdge:
    before: str
    after: str


@dataclass(frozen=True)
class TaskGraph:
    plugin_id: str
    plugin_version: str
    nodes: tuple[TaskNode, ...]
    edges: tuple[TaskEdge, ...]


@dataclass(frozen=True)
class ValidatedTaskGraph:
    """A whole-graph validation result; it grants no workflow authority.

    Runtime execution must still call the canonical intent authorization gate
    for every node immediately before binding it.  The catalog fields here
    make a stale validation detectable; they do not replace that recheck.
    """

    plugin_id: str
    plugin_version: str
    catalog_sha256: str
    catalog_generation: int
    registry_sha256: str
    graph_sha256: str
    validation_sha256: str
    initial_facts: tuple[str, ...]
    ordered_nodes: tuple[TaskNode, ...]


def _reject(
    code: GraphValidationCode,
    message: str,
    *,
    node_id: str | None = None,
) -> None:
    raise TaskGraphValidationError(code, message, node_id=node_id)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _scalar_matches(kind: ParameterKind, value: object) -> bool:
    if kind is ParameterKind.STRING:
        return isinstance(value, str) and len(value) <= MAX_PARAMETER_STRING_LENGTH
    if kind is ParameterKind.INTEGER:
        return type(value) is int
    if kind is ParameterKind.NUMBER:
        return type(value) in {int, float} and math.isfinite(float(value))
    if kind is ParameterKind.BOOLEAN:
        return type(value) is bool
    return False


def _validate_registry(registry: CapabilityRegistry) -> None:
    if _PLUGIN_ID_RE.fullmatch(registry.plugin_id) is None:
        _reject(GraphValidationCode.INVALID_REGISTRY, "registry plugin_id is invalid")
    if _VERSION_RE.fullmatch(registry.plugin_version) is None:
        _reject(GraphValidationCode.INVALID_REGISTRY, "registry version is invalid")
    if not _is_sha256(registry.catalog_sha256):
        _reject(GraphValidationCode.INVALID_REGISTRY, "registry catalog digest is invalid")
    if type(registry.catalog_generation) is not int or registry.catalog_generation < 0:
        _reject(
            GraphValidationCode.INVALID_REGISTRY,
            "registry catalog generation must be a non-negative integer",
        )
    if not isinstance(registry.capabilities, Mapping) or not registry.capabilities:
        _reject(GraphValidationCode.INVALID_REGISTRY, "registry has no capabilities")
    if len(registry.capabilities) > MAX_REGISTRY_CAPABILITIES:
        _reject(
            GraphValidationCode.INVALID_REGISTRY,
            "registry declares too many capabilities",
        )

    claimed_intents: set[str] = set()
    for key, capability in registry.capabilities.items():
        if key != capability.capability_id:
            _reject(
                GraphValidationCode.INVALID_REGISTRY,
                f"capability key {key!r} disagrees with its id",
            )
        if _CAPABILITY_ID_RE.fullmatch(capability.capability_id) is None:
            _reject(
                GraphValidationCode.INVALID_REGISTRY,
                f"capability id {capability.capability_id!r} is invalid",
            )
        if _CAPABILITY_ID_RE.fullmatch(capability.intent_id) is None:
            _reject(
                GraphValidationCode.INVALID_REGISTRY,
                f"intent id {capability.intent_id!r} is invalid",
            )
        if capability.intent_id in claimed_intents:
            _reject(
                GraphValidationCode.INVALID_REGISTRY,
                f"more than one capability maps to intent {capability.intent_id!r}",
            )
        claimed_intents.add(capability.intent_id)
        if (
            not isinstance(capability.authorization_goal, str)
            or not capability.authorization_goal.strip()
            or len(capability.authorization_goal) > MAX_AUTHORIZATION_GOAL_LENGTH
        ):
            _reject(
                GraphValidationCode.INVALID_REGISTRY,
                f"capability {key} authorization_goal is invalid",
            )
        if type(capability.safe_to_repeat) is not bool:
            _reject(
                GraphValidationCode.INVALID_REGISTRY,
                f"capability {key} safe_to_repeat must be boolean",
            )
        if (
            len(capability.preconditions) > MAX_CAPABILITY_FACTS
            or len(capability.postconditions) > MAX_CAPABILITY_FACTS
        ):
            _reject(
                GraphValidationCode.INVALID_REGISTRY,
                f"capability {key} declares too many facts",
            )
        for fact in (*capability.preconditions, *capability.postconditions):
            if _FACT_RE.fullmatch(fact) is None:
                _reject(
                    GraphValidationCode.INVALID_REGISTRY,
                    f"capability {key} has invalid fact {fact!r}",
                )
        if len(set(capability.preconditions)) != len(capability.preconditions):
            _reject(
                GraphValidationCode.INVALID_REGISTRY,
                f"capability {key} repeats a precondition",
            )
        if len(set(capability.postconditions)) != len(capability.postconditions):
            _reject(
                GraphValidationCode.INVALID_REGISTRY,
                f"capability {key} repeats a postcondition",
            )
        if not isinstance(capability.parameters, Mapping):
            _reject(
                GraphValidationCode.INVALID_REGISTRY,
                f"capability {key} parameters must be a mapping",
            )
        if len(capability.parameters) > MAX_NODE_PARAMETERS:
            _reject(
                GraphValidationCode.INVALID_REGISTRY,
                f"capability {key} declares too many parameters",
            )
        for name, parameter in capability.parameters.items():
            if _PARAMETER_RE.fullmatch(name) is None:
                _reject(
                    GraphValidationCode.INVALID_REGISTRY,
                    f"capability {key} has invalid parameter name {name!r}",
                )
            if not isinstance(parameter, ParameterSpec):
                _reject(
                    GraphValidationCode.INVALID_REGISTRY,
                    f"capability {key} parameter {name!r} is invalid",
                )
            if not isinstance(parameter.kind, ParameterKind):
                _reject(
                    GraphValidationCode.INVALID_REGISTRY,
                    f"capability {key} parameter {name!r} has invalid kind",
                )
            if type(parameter.required) is not bool:
                _reject(
                    GraphValidationCode.INVALID_REGISTRY,
                    f"capability {key} parameter {name!r} required must be boolean",
                )
            if len(parameter.allowed_values) > MAX_ALLOWED_VALUES:
                _reject(
                    GraphValidationCode.INVALID_REGISTRY,
                    f"capability {key} parameter {name!r} has too many allowed values",
                )
            for allowed in parameter.allowed_values:
                if not _scalar_matches(parameter.kind, allowed):
                    _reject(
                        GraphValidationCode.INVALID_REGISTRY,
                        f"capability {key} parameter {name!r} has invalid allowed value",
                    )


def _validate_parameter_values(node: TaskNode, capability: CapabilitySpec) -> None:
    if not isinstance(node.parameters, Mapping):
        _reject(
            GraphValidationCode.INVALID_PARAMETER,
            f"node {node.node_id!r} parameters must be a mapping",
            node_id=node.node_id,
        )
    if len(node.parameters) > MAX_NODE_PARAMETERS:
        _reject(
            GraphValidationCode.LIMIT_EXCEEDED,
            f"node {node.node_id!r} has too many parameters",
            node_id=node.node_id,
        )
    unknown = set(node.parameters) - set(capability.parameters)
    if unknown:
        _reject(
            GraphValidationCode.INVALID_PARAMETER,
            f"node {node.node_id!r} has unknown parameters: {sorted(unknown)}",
            node_id=node.node_id,
        )
    missing = {
        name
        for name, parameter in capability.parameters.items()
        if parameter.required and name not in node.parameters
    }
    if missing:
        _reject(
            GraphValidationCode.INVALID_PARAMETER,
            f"node {node.node_id!r} is missing parameters: {sorted(missing)}",
            node_id=node.node_id,
        )
    for name, value in node.parameters.items():
        parameter = capability.parameters[name]
        if not _scalar_matches(parameter.kind, value):
            _reject(
                GraphValidationCode.INVALID_PARAMETER,
                f"node {node.node_id!r} parameter {name!r} has the wrong type",
                node_id=node.node_id,
            )
        if parameter.allowed_values and value not in parameter.allowed_values:
            _reject(
                GraphValidationCode.INVALID_PARAMETER,
                f"node {node.node_id!r} parameter {name!r} is not allowed",
                node_id=node.node_id,
            )


def _canonical_scalar(value: Scalar) -> Scalar:
    # JSON emits 1.0 and 1 differently.  Both are valid NUMBER values and their
    # distinct spelling remains part of the model-proposed graph digest.
    return value


def _registry_bytes(registry: CapabilityRegistry) -> bytes:
    value = {
        "catalog_generation": registry.catalog_generation,
        "catalog_sha256": registry.catalog_sha256,
        "capabilities": [
            {
                "capability_id": capability.capability_id,
                "intent_id": capability.intent_id,
                "authorization_goal": capability.authorization_goal,
                "parameters": [
                    {
                        "allowed_values": [
                            _canonical_scalar(value) for value in parameter.allowed_values
                        ],
                        "kind": parameter.kind.value,
                        "name": name,
                        "required": parameter.required,
                    }
                    for name, parameter in sorted(capability.parameters.items())
                ],
                "postconditions": list(capability.postconditions),
                "preconditions": list(capability.preconditions),
                "safe_to_repeat": capability.safe_to_repeat,
            }
            for _, capability in sorted(registry.capabilities.items())
        ],
        "plugin_id": registry.plugin_id,
        "plugin_version": registry.plugin_version,
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def capability_registry_sha256(registry: CapabilityRegistry) -> str:
    """Return the canonical digest of one validated capability vocabulary."""

    _validate_registry(registry)
    return hashlib.sha256(_registry_bytes(registry)).hexdigest()


def _strict_capability_json(raw: bytes) -> dict[str, object]:
    if len(raw) > MAX_CAPABILITY_ARTIFACT_BYTES:
        _reject(GraphValidationCode.INVALID_REGISTRY, "capability artifact is too large")
    if raw.startswith(b"\xef\xbb\xbf"):
        _reject(GraphValidationCode.INVALID_REGISTRY, "capability artifact has a BOM")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _reject(GraphValidationCode.INVALID_REGISTRY, "capability artifact is not UTF-8")

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                _reject(
                    GraphValidationCode.INVALID_REGISTRY,
                    f"capability artifact repeats key {key!r}",
                )
            value[key] = item
        return value

    def constant(value: str) -> None:
        _reject(
            GraphValidationCode.INVALID_REGISTRY,
            f"capability artifact has non-finite number {value}",
        )

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except json.JSONDecodeError:
        _reject(GraphValidationCode.INVALID_REGISTRY, "capability artifact is not JSON")
    if not isinstance(value, dict):
        _reject(GraphValidationCode.INVALID_REGISTRY, "capability artifact must be an object")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if canonical != raw:
        _reject(
            GraphValidationCode.INVALID_REGISTRY,
            "capability artifact is not canonical JSON",
        )
    return value


def load_capability_registry(
    raw: bytes,
    *,
    plugin_id: str,
    plugin_version: str,
    catalog_sha256: str,
    catalog_generation: int,
) -> CapabilityRegistry:
    """Parse one signed plugin capability artifact and bind its catalog epoch."""

    value = _strict_capability_json(raw)
    required = {"schema_version", "plugin_id", "plugin_version", "capabilities"}
    if set(value) != required or value["schema_version"] != 1:
        _reject(GraphValidationCode.INVALID_REGISTRY, "capability artifact fields are invalid")
    if value["plugin_id"] != plugin_id or value["plugin_version"] != plugin_version:
        _reject(
            GraphValidationCode.INVALID_REGISTRY,
            "capability artifact plugin identity disagrees with its signed bundle",
        )
    declared = value["capabilities"]
    if not isinstance(declared, dict):
        _reject(GraphValidationCode.INVALID_REGISTRY, "capabilities must be an object")

    capabilities: dict[str, CapabilitySpec] = {}
    for capability_id, item in declared.items():
        if not isinstance(capability_id, str) or not isinstance(item, dict):
            _reject(GraphValidationCode.INVALID_REGISTRY, "capability declaration is invalid")
        fields = {
            "authorization_goal",
            "intent_id",
            "parameters",
            "postconditions",
            "preconditions",
            "safe_to_repeat",
        }
        if set(item) != fields:
            _reject(
                GraphValidationCode.INVALID_REGISTRY,
                f"capability {capability_id!r} fields are invalid",
            )
        parameters_value = item["parameters"]
        if not isinstance(parameters_value, dict):
            _reject(
                GraphValidationCode.INVALID_REGISTRY,
                f"capability {capability_id!r} parameters must be an object",
            )
        parameters: dict[str, ParameterSpec] = {}
        for name, parameter in parameters_value.items():
            if not isinstance(name, str) or not isinstance(parameter, dict):
                _reject(
                    GraphValidationCode.INVALID_REGISTRY,
                    f"capability {capability_id!r} parameter is invalid",
                )
            if set(parameter) != {"allowed_values", "kind", "required"}:
                _reject(
                    GraphValidationCode.INVALID_REGISTRY,
                    f"capability {capability_id!r} parameter {name!r} fields are invalid",
                )
            try:
                kind = ParameterKind(parameter["kind"])
            except (TypeError, ValueError):
                _reject(
                    GraphValidationCode.INVALID_REGISTRY,
                    f"capability {capability_id!r} parameter {name!r} kind is invalid",
                )
            allowed = parameter["allowed_values"]
            if not isinstance(allowed, list):
                _reject(
                    GraphValidationCode.INVALID_REGISTRY,
                    f"capability {capability_id!r} parameter {name!r} allowed_values is invalid",
                )
            parameters[name] = ParameterSpec(
                kind=kind,
                required=parameter["required"],
                allowed_values=tuple(allowed),
            )
        preconditions = item["preconditions"]
        postconditions = item["postconditions"]
        if not isinstance(preconditions, list) or not all(
            isinstance(fact, str) for fact in preconditions
        ):
            _reject(
                GraphValidationCode.INVALID_REGISTRY,
                f"capability {capability_id!r} preconditions are invalid",
            )
        if not isinstance(postconditions, list) or not all(
            isinstance(fact, str) for fact in postconditions
        ):
            _reject(
                GraphValidationCode.INVALID_REGISTRY,
                f"capability {capability_id!r} postconditions are invalid",
            )
        capabilities[capability_id] = CapabilitySpec(
            capability_id=capability_id,
            intent_id=item["intent_id"],
            authorization_goal=item["authorization_goal"],
            preconditions=tuple(preconditions),
            postconditions=tuple(postconditions),
            parameters=MappingProxyType(parameters),
            safe_to_repeat=item["safe_to_repeat"],
        )
    registry = CapabilityRegistry(
        plugin_id=plugin_id,
        plugin_version=plugin_version,
        catalog_sha256=catalog_sha256,
        catalog_generation=catalog_generation,
        capabilities=MappingProxyType(capabilities),
    )
    _validate_registry(registry)
    return registry


def _graph_bytes(graph: TaskGraph) -> bytes:
    value = {
        "edges": [
            {"after": edge.after, "before": edge.before}
            for edge in sorted(graph.edges)
        ],
        "nodes": [
            {
                "capability_id": node.capability_id,
                "node_id": node.node_id,
                "parameters": {
                    name: _canonical_scalar(parameter)
                    for name, parameter in sorted(node.parameters.items())
                },
                "plugin_id": node.plugin_id,
            }
            for node in sorted(graph.nodes, key=lambda item: item.node_id)
        ],
        "plugin_id": graph.plugin_id,
        "plugin_version": graph.plugin_version,
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def validate_task_graph(
    graph: TaskGraph,
    registry: CapabilityRegistry,
    *,
    initial_facts: tuple[str, ...] = (),
) -> ValidatedTaskGraph:
    """Validate the entire graph and return one deterministic linearization.

    No node is executable merely because this returns.  The result proves only
    that the proposal is a bounded, acyclic, single-plugin arrangement of the
    registry's known capabilities with statically satisfiable ordering.
    """

    _validate_registry(registry)
    if graph.plugin_id != registry.plugin_id or graph.plugin_version != registry.plugin_version:
        _reject(
            GraphValidationCode.WRONG_PLUGIN,
            "graph plugin identity disagrees with the capability registry",
        )
    if not graph.nodes:
        _reject(GraphValidationCode.INVALID_GRAPH, "task graph has no nodes")
    if len(graph.nodes) > MAX_GRAPH_NODES or len(graph.edges) > MAX_GRAPH_EDGES:
        _reject(GraphValidationCode.LIMIT_EXCEEDED, "task graph exceeds its size limit")
    if len(set(initial_facts)) != len(initial_facts) or any(
        _FACT_RE.fullmatch(fact) is None for fact in initial_facts
    ):
        _reject(GraphValidationCode.INVALID_GRAPH, "initial facts are invalid")

    nodes: dict[str, TaskNode] = {}
    used_non_repeatable: set[str] = set()
    for node in graph.nodes:
        if not isinstance(node, TaskNode):
            _reject(GraphValidationCode.INVALID_GRAPH, "task graph has an invalid node")
        if _NODE_ID_RE.fullmatch(node.node_id) is None:
            _reject(
                GraphValidationCode.INVALID_GRAPH,
                f"node id {node.node_id!r} is invalid",
                node_id=node.node_id,
            )
        if node.node_id in nodes:
            _reject(
                GraphValidationCode.DUPLICATE_NODE,
                f"node id {node.node_id!r} is duplicated",
                node_id=node.node_id,
            )
        if node.plugin_id != graph.plugin_id:
            _reject(
                GraphValidationCode.WRONG_PLUGIN,
                f"node {node.node_id!r} belongs to another plugin",
                node_id=node.node_id,
            )
        capability = registry.capabilities.get(node.capability_id)
        if capability is None:
            _reject(
                GraphValidationCode.UNKNOWN_CAPABILITY,
                f"node {node.node_id!r} names an unknown capability",
                node_id=node.node_id,
            )
        _validate_parameter_values(node, capability)
        if not capability.safe_to_repeat:
            if capability.capability_id in used_non_repeatable:
                _reject(
                    GraphValidationCode.DUPLICATE_NON_REPEATABLE,
                    f"capability {capability.capability_id!r} is not safe to repeat",
                    node_id=node.node_id,
                )
            used_non_repeatable.add(capability.capability_id)
        nodes[node.node_id] = node

    children = {node_id: set() for node_id in nodes}
    parents = {node_id: set() for node_id in nodes}
    seen_edges: set[TaskEdge] = set()
    for edge in graph.edges:
        if not isinstance(edge, TaskEdge):
            _reject(GraphValidationCode.INVALID_GRAPH, "task graph has an invalid edge")
        if edge in seen_edges:
            _reject(
                GraphValidationCode.DUPLICATE_EDGE,
                f"edge {edge.before!r} -> {edge.after!r} is duplicated",
            )
        seen_edges.add(edge)
        if edge.before not in nodes or edge.after not in nodes:
            _reject(
                GraphValidationCode.UNKNOWN_NODE,
                f"edge {edge.before!r} -> {edge.after!r} names an unknown node",
            )
        children[edge.before].add(edge.after)
        parents[edge.after].add(edge.before)

    ready = [node_id for node_id, incoming in parents.items() if not incoming]
    heapq.heapify(ready)
    remaining_parents = {node_id: set(incoming) for node_id, incoming in parents.items()}
    order: list[str] = []
    while ready:
        node_id = heapq.heappop(ready)
        order.append(node_id)
        for child in sorted(children[node_id]):
            remaining_parents[child].remove(node_id)
            if not remaining_parents[child]:
                heapq.heappush(ready, child)
    if len(order) != len(nodes):
        _reject(GraphValidationCode.CYCLE, "task graph contains a cycle")

    guaranteed_after: dict[str, set[str]] = {}
    initial = set(initial_facts)
    for node_id in order:
        available = set(initial)
        for parent in parents[node_id]:
            available.update(guaranteed_after[parent])
        capability = registry.capabilities[nodes[node_id].capability_id]
        missing = set(capability.preconditions) - available
        if missing:
            _reject(
                GraphValidationCode.UNSATISFIED_PRECONDITION,
                f"node {node_id!r} has unsatisfied preconditions: {sorted(missing)}",
                node_id=node_id,
            )
        guaranteed_after[node_id] = available | set(capability.postconditions)

    frozen_nodes = tuple(
        TaskNode(
            node_id=nodes[node_id].node_id,
            plugin_id=nodes[node_id].plugin_id,
            capability_id=nodes[node_id].capability_id,
            parameters=MappingProxyType(dict(nodes[node_id].parameters)),
        )
        for node_id in order
    )
    registry_sha256 = capability_registry_sha256(registry)
    graph_sha256 = hashlib.sha256(_graph_bytes(graph)).hexdigest()
    sorted_initial_facts = tuple(sorted(initial_facts))
    validation_sha256 = hashlib.sha256(
        json.dumps(
            {
                "graph_sha256": graph_sha256,
                "initial_facts": sorted_initial_facts,
                "registry_sha256": registry_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ValidatedTaskGraph(
        plugin_id=graph.plugin_id,
        plugin_version=graph.plugin_version,
        catalog_sha256=registry.catalog_sha256,
        catalog_generation=registry.catalog_generation,
        registry_sha256=registry_sha256,
        graph_sha256=graph_sha256,
        validation_sha256=validation_sha256,
        initial_facts=sorted_initial_facts,
        ordered_nodes=frozen_nodes,
    )
