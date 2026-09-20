"""Fail-closed contracts for autonomous, plugin-owned desktop actions.

The model-facing task graph remains a vocabulary of signed capabilities.  This
module owns the smaller action graph produced after one capability has crossed
the canonical intent boundary.  An action graph is still inert: validation and
operator approval grant no application authority, and every node must receive
a fresh one-use authorization immediately before an adapter is called.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from enum import Enum
from types import MappingProxyType

if TYPE_CHECKING:  # pragma: no cover
    from ghostcursor.uia_identity import IdentityPolicy
from typing import Any, Mapping, TypeAlias


MAX_ACTION_NODES = 512
MAX_ACTION_EDGES = 2048
MAX_ACTION_PARAMETERS = 32
MAX_ACTION_VALUE_BYTES = 64 * 1024
MAX_ACTION_DEPTH = 8
MAX_OPERATION_REGISTRY_BYTES = 512 * 1024
MAX_OPERATION_COUNT = 256
OPERATION_ARTIFACT_PATH = "ghostcursor/operations.json"

_PLUGIN_ID_RE = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+")
_VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?")
_OPERATION_ID_RE = re.compile(r"[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*)+")
_NODE_ID_RE = re.compile(r"[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*")
_PARAMETER_RE = re.compile(r"[a-z][a-z0-9_]*")
_FACT_RE = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]


class ActionValueKind(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"


class ActionRisk(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    SENSITIVE = "sensitive"


class ActionValidationCode(str, Enum):
    INVALID_REGISTRY = "invalid_registry"
    INVALID_GRAPH = "invalid_graph"
    LIMIT_EXCEEDED = "limit_exceeded"
    DUPLICATE_NODE = "duplicate_node"
    DUPLICATE_EDGE = "duplicate_edge"
    UNKNOWN_NODE = "unknown_node"
    UNKNOWN_OPERATION = "unknown_operation"
    INVALID_PARAMETER = "invalid_parameter"
    DUPLICATE_EFFECT = "duplicate_effect"
    CYCLE = "cycle"
    UNSATISFIED_PRECONDITION = "unsatisfied_precondition"


class ActionValidationError(ValueError):
    """An action plan refused before an adapter may be started."""

    phase = "validation"

    def __init__(
        self,
        code: ActionValidationCode,
        message: str,
        *,
        node_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.node_id = node_id


@dataclass(frozen=True)
class ActionParameterSpec:
    kind: ActionValueKind
    required: bool = True
    allowed_values: tuple[JsonScalar, ...] = ()


#: How an operation performs its effect. Absent means OBJECT_MODEL, which
#: is what every registry signed before UIA support declared implicitly --
#: adding a required key would have changed those bytes and invalidated
#: their digests, so the field is optional and defaults to the old
#: behaviour.
OPERATION_BACKENDS = frozenset(
    {"object_model", "uia_pattern", "legacy_iaccessible"}
)

#: UIA patterns a signed operation may name. Closed: a pattern the adapter
#: cannot dispatch would be an operation nothing can perform.
UIA_PATTERNS = frozenset({"Invoke", "SelectionItem", "Toggle", "Value"})


@dataclass(frozen=True)
class OperationSpec:
    operation_id: str
    risk: ActionRisk
    parameters: Mapping[str, ActionParameterSpec] = field(
        default_factory=lambda: MappingProxyType({})
    )
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    safe_to_repeat: bool = False
    effect_key_fields: tuple[str, ...] = ()
    timeout_s: float = 20.0
    backend: str = "object_model"
    #: The UIA pattern to dispatch, and the identity the resolved control
    #: must still have when it is dispatched. Both None for an
    #: object-model operation, which drives an application API and has no
    #: control to hold.
    uia_pattern: str | None = None
    identity: "IdentityPolicy | None" = None
    #: Signed timing policy for a UIA confirmation boundary.
    confirmation_round_trip_deadline_ms: int | None = None
    confirmation_to_request_deadline_ms: int | None = None

    @property
    def draws_a_pointer(self) -> bool:
        """Whether this operation may show a pointer at its target (D109).

        Only a backend that resolves and acts on a real control may. An
        object-model operation has no control it is clicking, so a pointer
        over one would show an action where it did not happen.
        """

        return self.backend != "object_model"


@dataclass(frozen=True)
class OperationRegistry:
    plugin_id: str
    plugin_version: str
    adapter_sha256: str
    operations_sha256: str
    operations: Mapping[str, OperationSpec]


@dataclass(frozen=True)
class ActionNode:
    node_id: str
    operation_id: str
    parameters: Mapping[str, JsonValue] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True, order=True)
class ActionEdge:
    before: str
    after: str


@dataclass(frozen=True)
class ActionGraph:
    plugin_id: str
    plugin_version: str
    adapter_sha256: str
    nodes: tuple[ActionNode, ...]
    edges: tuple[ActionEdge, ...]


@dataclass(frozen=True)
class ValidatedActionGraph:
    plugin_id: str
    plugin_version: str
    adapter_sha256: str
    operations_sha256: str
    graph_sha256: str
    validation_sha256: str
    initial_facts: tuple[str, ...]
    ordered_nodes: tuple[ActionNode, ...]


def _reject(
    code: ActionValidationCode,
    message: str,
    *,
    node_id: str | None = None,
) -> None:
    raise ActionValidationError(code, message, node_id=node_id)


def _strict_json(raw: bytes, *, label: str, limit: int) -> Any:
    if len(raw) > limit:
        _reject(ActionValidationCode.LIMIT_EXCEEDED, f"{label} is too large")
    if raw.startswith(b"\xef\xbb\xbf"):
        _reject(ActionValidationCode.INVALID_REGISTRY, f"{label} has a BOM")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _reject(ActionValidationCode.INVALID_REGISTRY, f"{label} is not UTF-8")

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                _reject(
                    ActionValidationCode.INVALID_REGISTRY,
                    f"{label} repeats key {key!r}",
                )
            value[key] = item
        return value

    def constant(value: str) -> None:
        _reject(
            ActionValidationCode.INVALID_REGISTRY,
            f"{label} has non-finite number {value}",
        )

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except json.JSONDecodeError:
        _reject(ActionValidationCode.INVALID_REGISTRY, f"{label} is not JSON")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    if canonical != raw.removesuffix(b"\n") or b"\r" in raw:
        _reject(ActionValidationCode.INVALID_REGISTRY, f"{label} is not canonical JSON")
    return value


def _freeze(value: Any, *, depth: int = 0) -> JsonValue:
    if depth > MAX_ACTION_DEPTH:
        _reject(
            ActionValidationCode.LIMIT_EXCEEDED, "action value is too deeply nested"
        )
    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            _reject(ActionValidationCode.INVALID_PARAMETER, "non-finite action number")
        return value
    if isinstance(value, list):
        return tuple(_freeze(item, depth=depth + 1) for item in value)
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            _reject(
                ActionValidationCode.INVALID_PARAMETER,
                "action object keys must be strings",
            )
        return MappingProxyType(
            {key: _freeze(item, depth=depth + 1) for key, item in sorted(value.items())}
        )
    _reject(ActionValidationCode.INVALID_PARAMETER, "action value has an invalid type")


def _plain(value: JsonValue) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _value_matches(kind: ActionValueKind, value: JsonValue) -> bool:
    if kind is ActionValueKind.STRING:
        return isinstance(value, str)
    if kind is ActionValueKind.INTEGER:
        return type(value) is int
    if kind is ActionValueKind.NUMBER:
        return type(value) in {int, float} and math.isfinite(float(value))
    if kind is ActionValueKind.BOOLEAN:
        return type(value) is bool
    if kind is ActionValueKind.OBJECT:
        return isinstance(value, Mapping)
    if kind is ActionValueKind.ARRAY:
        return isinstance(value, tuple)
    return False


def _validate_value_size(value: JsonValue, *, node_id: str, name: str) -> None:
    encoded = json.dumps(_plain(value), sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > MAX_ACTION_VALUE_BYTES:
        _reject(
            ActionValidationCode.LIMIT_EXCEEDED,
            f"node {node_id!r} parameter {name!r} is too large",
            node_id=node_id,
        )



def _parse_uia_block(operation_id: str, uia: object, backend: str):
    """Read the signed UIA block into a pattern and an IdentityPolicy.

    Refused rather than defaulted at every step. An operation that acts on
    a real control must say exactly which control and what has to still be
    true about it, because the gap between resolving it and acting on it is
    where a selector starts matching something else.
    """

    from ghostcursor.uia_identity import IdentityPolicy, IdentityPolicyError

    if (
        backend == "legacy_iaccessible"
        and isinstance(uia, dict)
        and "pattern" in uia
        and uia["pattern"] != "DoDefaultAction"
    ):
        _reject(
            ActionValidationCode.INVALID_REGISTRY,
            f"operation {operation_id!r} legacy backend must declare DoDefaultAction",
        )

    expected = {
        "control_type",
        "evidence_identity_fields",
        "identity_mode",
        "pattern",
        "required_identity_fields",
        "selector_id",
        "selector_sha256",
    }
    if backend == "uia_pattern":
        expected |= {
            "confirmation_round_trip_deadline_ms",
            "confirmation_to_request_deadline_ms",
        }
    if not isinstance(uia, dict) or set(uia) != expected:
        _reject(
            ActionValidationCode.INVALID_REGISTRY,
            f"operation {operation_id!r} uia block is invalid",
        )
    pattern = uia["pattern"]
    if backend == "legacy_iaccessible":
        # The legacy default action is not a UIA pattern and must say so,
        # rather than borrowing a pattern name it does not dispatch.
        if pattern != "DoDefaultAction":
            _reject(
                ActionValidationCode.INVALID_REGISTRY,
                f"operation {operation_id!r} legacy backend must declare "
                "DoDefaultAction",
            )
    elif pattern not in UIA_PATTERNS:
        _reject(
            ActionValidationCode.INVALID_REGISTRY,
            f"operation {operation_id!r} pattern {pattern!r} is not a "
            "dispatchable UIA pattern",
        )
    deadlines = (
        (uia["confirmation_round_trip_deadline_ms"],
         uia["confirmation_to_request_deadline_ms"])
        if backend == "uia_pattern" else (None, None)
    )
    if backend == "uia_pattern" and any(
        type(value) is not int or not 1 <= value <= 120_000 for value in deadlines
    ):
        _reject(
            ActionValidationCode.INVALID_REGISTRY,
            f"operation {operation_id!r} UIA timing policy is invalid",
        )
    for label in ("required_identity_fields", "evidence_identity_fields"):
        if not isinstance(uia[label], list) or any(
            not isinstance(name, str) for name in uia[label]
        ):
            _reject(
                ActionValidationCode.INVALID_REGISTRY,
                f"operation {operation_id!r} {label} is invalid",
            )
    try:
        identity = IdentityPolicy(
            operation_id=operation_id,
            selector_id=uia["selector_id"],
            selector_sha256=uia["selector_sha256"],
            control_type=uia["control_type"],
            identity_mode=uia["identity_mode"],
            required_fields=tuple(uia["required_identity_fields"]),
            evidence_fields=tuple(uia["evidence_identity_fields"]),
        )
    except IdentityPolicyError as exc:
        _reject(
            ActionValidationCode.INVALID_REGISTRY,
            f"operation {operation_id!r} identity policy is invalid: {exc}",
        )
    return pattern, identity, deadlines

def load_operation_registry(
    raw: bytes,
    *,
    plugin_id: str,
    plugin_version: str,
    adapter_sha256: str,
) -> OperationRegistry:
    """Parse the signed, closed vocabulary an executable adapter may receive."""

    value = _strict_json(
        raw, label="operation registry", limit=MAX_OPERATION_REGISTRY_BYTES
    )
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "plugin_id",
        "plugin_version",
        "operations",
    }:
        _reject(
            ActionValidationCode.INVALID_REGISTRY,
            "operation registry fields are invalid",
        )
    if value["schema_version"] != 1:
        _reject(
            ActionValidationCode.INVALID_REGISTRY,
            "operation registry version is unsupported",
        )
    if value["plugin_id"] != plugin_id or value["plugin_version"] != plugin_version:
        _reject(
            ActionValidationCode.INVALID_REGISTRY,
            "operation registry identity disagrees",
        )
    declared = value["operations"]
    if (
        not isinstance(declared, dict)
        or not declared
        or len(declared) > MAX_OPERATION_COUNT
    ):
        _reject(
            ActionValidationCode.INVALID_REGISTRY,
            "operation registry is empty or too large",
        )

    operations: dict[str, OperationSpec] = {}
    for operation_id, item in declared.items():
        if (
            not isinstance(operation_id, str)
            or _OPERATION_ID_RE.fullmatch(operation_id) is None
        ):
            _reject(ActionValidationCode.INVALID_REGISTRY, "operation id is invalid")
        required_fields = {
            "effect_key_fields",
            "parameters",
            "postconditions",
            "preconditions",
            "risk",
            "safe_to_repeat",
            "timeout_s",
        }
        # `backend` and `uia` are OPTIONAL so registries signed before UIA
        # support keep validating byte-for-byte. Anything else is refused.
        optional_fields = {"backend", "uia"}
        if (
            not isinstance(item, dict)
            or not required_fields <= set(item)
            or not set(item) <= required_fields | optional_fields
        ):
            _reject(
                ActionValidationCode.INVALID_REGISTRY,
                f"operation {operation_id!r} fields are invalid",
            )
        try:
            risk = ActionRisk(item["risk"])
        except (TypeError, ValueError):
            _reject(
                ActionValidationCode.INVALID_REGISTRY,
                f"operation {operation_id!r} risk is invalid",
            )
        parameters_value = item["parameters"]
        if (
            not isinstance(parameters_value, dict)
            or len(parameters_value) > MAX_ACTION_PARAMETERS
        ):
            _reject(
                ActionValidationCode.INVALID_REGISTRY,
                f"operation {operation_id!r} parameters are invalid",
            )
        parameters: dict[str, ActionParameterSpec] = {}
        for name, parameter in parameters_value.items():
            if (
                not isinstance(name, str)
                or _PARAMETER_RE.fullmatch(name) is None
                or not isinstance(parameter, dict)
            ):
                _reject(
                    ActionValidationCode.INVALID_REGISTRY,
                    f"operation {operation_id!r} parameter is invalid",
                )
            if set(parameter) != {"allowed_values", "kind", "required"}:
                _reject(
                    ActionValidationCode.INVALID_REGISTRY,
                    f"operation {operation_id!r} parameter fields are invalid",
                )
            try:
                kind = ActionValueKind(parameter["kind"])
            except (TypeError, ValueError):
                _reject(
                    ActionValidationCode.INVALID_REGISTRY,
                    f"operation {operation_id!r} parameter kind is invalid",
                )
            allowed = parameter["allowed_values"]
            if not isinstance(allowed, list) or any(
                type(item) not in {str, int, float, bool, type(None)}
                or (type(item) is float and not math.isfinite(item))
                for item in allowed
            ):
                _reject(
                    ActionValidationCode.INVALID_REGISTRY,
                    f"operation {operation_id!r} allowed values are invalid",
                )
            parameters[name] = ActionParameterSpec(
                kind=kind,
                required=parameter["required"],
                allowed_values=tuple(allowed),
            )
        preconditions = item["preconditions"]
        postconditions = item["postconditions"]
        effect_fields = item["effect_key_fields"]
        if not all(
            isinstance(part, list)
            for part in (preconditions, postconditions, effect_fields)
        ):
            _reject(
                ActionValidationCode.INVALID_REGISTRY,
                f"operation {operation_id!r} list fields are invalid",
            )
        if any(
            not isinstance(fact, str) or _FACT_RE.fullmatch(fact) is None
            for facts in (preconditions, postconditions)
            for fact in facts
        ) or any(
            len(facts) != len(set(facts)) for facts in (preconditions, postconditions)
        ):
            _reject(
                ActionValidationCode.INVALID_REGISTRY,
                f"operation {operation_id!r} facts are invalid",
            )
        if any(not isinstance(field, str) for field in effect_fields):
            _reject(
                ActionValidationCode.INVALID_REGISTRY,
                f"operation {operation_id!r} effect key is invalid",
            )
        if any(field not in parameters for field in effect_fields) or len(
            set(effect_fields)
        ) != len(effect_fields):
            _reject(
                ActionValidationCode.INVALID_REGISTRY,
                f"operation {operation_id!r} effect key is invalid",
            )
        backend = item.get("backend", "object_model")
        if backend not in OPERATION_BACKENDS:
            _reject(
                ActionValidationCode.INVALID_REGISTRY,
                f"operation {operation_id!r} backend {backend!r} is unknown",
            )
        uia = item.get("uia")
        if backend == "object_model":
            if uia is not None:
                _reject(
                    ActionValidationCode.INVALID_REGISTRY,
                    f"operation {operation_id!r} is object_model but "
                    "declares a uia block",
                )
            uia_pattern, identity = None, None
            confirmation_round_trip_deadline_ms = None
            confirmation_to_request_deadline_ms = None
        else:
            (
                uia_pattern,
                identity,
                (
                    confirmation_round_trip_deadline_ms,
                    confirmation_to_request_deadline_ms,
                ),
            ) = _parse_uia_block(operation_id, uia, backend)

        timeout_s = item["timeout_s"]
        if type(timeout_s) not in {int, float} or not 0.1 <= float(timeout_s) <= 120.0:
            _reject(
                ActionValidationCode.INVALID_REGISTRY,
                f"operation {operation_id!r} timeout is invalid",
            )
        if type(item["safe_to_repeat"]) is not bool:
            _reject(
                ActionValidationCode.INVALID_REGISTRY,
                f"operation {operation_id!r} repeatability is invalid",
            )
        operations[operation_id] = OperationSpec(
            operation_id=operation_id,
            risk=risk,
            backend=backend,
            uia_pattern=uia_pattern,
            identity=identity,
            parameters=MappingProxyType(parameters),
            preconditions=tuple(preconditions),
            postconditions=tuple(postconditions),
            safe_to_repeat=item["safe_to_repeat"],
            effect_key_fields=tuple(effect_fields),
            timeout_s=float(timeout_s),
            confirmation_round_trip_deadline_ms=confirmation_round_trip_deadline_ms,
            confirmation_to_request_deadline_ms=confirmation_to_request_deadline_ms,
        )

    digest = hashlib.sha256(raw).hexdigest()
    registry = OperationRegistry(
        plugin_id=plugin_id,
        plugin_version=plugin_version,
        adapter_sha256=adapter_sha256,
        operations_sha256=digest,
        operations=MappingProxyType(operations),
    )
    _validate_registry(registry)
    return registry


def _validate_registry(registry: OperationRegistry) -> None:
    if _PLUGIN_ID_RE.fullmatch(registry.plugin_id) is None:
        _reject(
            ActionValidationCode.INVALID_REGISTRY,
            "operation registry plugin id is invalid",
        )
    if _VERSION_RE.fullmatch(registry.plugin_version) is None:
        _reject(
            ActionValidationCode.INVALID_REGISTRY,
            "operation registry version is invalid",
        )
    if (
        _SHA256_RE.fullmatch(registry.adapter_sha256) is None
        or _SHA256_RE.fullmatch(registry.operations_sha256) is None
    ):
        _reject(
            ActionValidationCode.INVALID_REGISTRY,
            "operation registry digest is invalid",
        )
    for key, operation in registry.operations.items():
        if key != operation.operation_id:
            _reject(
                ActionValidationCode.INVALID_REGISTRY,
                "operation registry key disagrees",
            )


def _graph_bytes(graph: ActionGraph) -> bytes:
    value = {
        "adapter_sha256": graph.adapter_sha256,
        "edges": [
            {"after": edge.after, "before": edge.before} for edge in sorted(graph.edges)
        ],
        "nodes": [
            {
                "node_id": node.node_id,
                "operation_id": node.operation_id,
                "parameters": {
                    key: _plain(value) for key, value in sorted(node.parameters.items())
                },
            }
            for node in graph.nodes
        ],
        "plugin_id": graph.plugin_id,
        "plugin_version": graph.plugin_version,
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def validate_action_graph(
    graph: ActionGraph,
    registry: OperationRegistry,
    *,
    initial_facts: tuple[str, ...] = (),
) -> ValidatedActionGraph:
    """Reject or freeze the complete graph before the first side effect."""

    _validate_registry(registry)
    if (
        graph.plugin_id != registry.plugin_id
        or graph.plugin_version != registry.plugin_version
        or graph.adapter_sha256 != registry.adapter_sha256
    ):
        _reject(ActionValidationCode.INVALID_GRAPH, "action graph authority disagrees")
    if (
        not graph.nodes
        or len(graph.nodes) > MAX_ACTION_NODES
        or len(graph.edges) > MAX_ACTION_EDGES
    ):
        _reject(
            ActionValidationCode.LIMIT_EXCEEDED, "action graph is empty or too large"
        )
    node_by_id: dict[str, ActionNode] = {}
    for node in graph.nodes:
        if _NODE_ID_RE.fullmatch(node.node_id) is None:
            _reject(
                ActionValidationCode.INVALID_GRAPH,
                "action node id is invalid",
                node_id=node.node_id,
            )
        if node.node_id in node_by_id:
            _reject(
                ActionValidationCode.DUPLICATE_NODE,
                f"duplicate action node {node.node_id!r}",
                node_id=node.node_id,
            )
        operation = registry.operations.get(node.operation_id)
        if operation is None:
            _reject(
                ActionValidationCode.UNKNOWN_OPERATION,
                f"unknown operation {node.operation_id!r}",
                node_id=node.node_id,
            )
        if (
            not isinstance(node.parameters, Mapping)
            or len(node.parameters) > MAX_ACTION_PARAMETERS
        ):
            _reject(
                ActionValidationCode.INVALID_PARAMETER,
                f"node {node.node_id!r} parameters are invalid",
                node_id=node.node_id,
            )
        unknown = set(node.parameters) - set(operation.parameters)
        missing = {
            name
            for name, spec in operation.parameters.items()
            if spec.required and name not in node.parameters
        }
        if unknown or missing:
            _reject(
                ActionValidationCode.INVALID_PARAMETER,
                f"node {node.node_id!r} parameters disagree; missing={sorted(missing)}, extra={sorted(unknown)}",
                node_id=node.node_id,
            )
        frozen_parameters = {}
        for name, raw_value in node.parameters.items():
            value = _freeze(raw_value)
            spec = operation.parameters[name]
            if not _value_matches(spec.kind, value) or (
                spec.allowed_values and value not in spec.allowed_values
            ):
                _reject(
                    ActionValidationCode.INVALID_PARAMETER,
                    f"node {node.node_id!r} parameter {name!r} is invalid",
                    node_id=node.node_id,
                )
            _validate_value_size(value, node_id=node.node_id, name=name)
            frozen_parameters[name] = value
        node_by_id[node.node_id] = ActionNode(
            node.node_id,
            node.operation_id,
            MappingProxyType(frozen_parameters),
        )

    edge_set: set[tuple[str, str]] = set()
    outgoing = {node_id: [] for node_id in node_by_id}
    indegree = {node_id: 0 for node_id in node_by_id}
    for edge in graph.edges:
        if edge.before not in node_by_id or edge.after not in node_by_id:
            _reject(
                ActionValidationCode.UNKNOWN_NODE, "action edge names an unknown node"
            )
        if edge.before == edge.after:
            _reject(
                ActionValidationCode.CYCLE,
                "action node cannot depend on itself",
                node_id=edge.before,
            )
        pair = (edge.before, edge.after)
        if pair in edge_set:
            _reject(ActionValidationCode.DUPLICATE_EDGE, "duplicate action edge")
        edge_set.add(pair)
        outgoing[edge.before].append(edge.after)
        indegree[edge.after] += 1

    ready = list(node_id for node_id, count in indegree.items() if count == 0)
    heapq.heapify(ready)
    ordered_ids = []
    while ready:
        current = heapq.heappop(ready)
        ordered_ids.append(current)
        for child in sorted(outgoing[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, child)
    if len(ordered_ids) != len(node_by_id):
        _reject(ActionValidationCode.CYCLE, "action graph contains a cycle")

    if any(
        not isinstance(fact, str) or _FACT_RE.fullmatch(fact) is None
        for fact in initial_facts
    ) or len(initial_facts) != len(set(initial_facts)):
        _reject(ActionValidationCode.INVALID_GRAPH, "initial facts are invalid")
    facts = set(initial_facts)
    effects: set[tuple[Any, ...]] = set()
    for node_id in ordered_ids:
        node = node_by_id[node_id]
        operation = registry.operations[node.operation_id]
        missing_facts = set(operation.preconditions) - facts
        if missing_facts:
            _reject(
                ActionValidationCode.UNSATISFIED_PRECONDITION,
                f"node {node_id!r} lacks facts: {sorted(missing_facts)}",
                node_id=node_id,
            )
        if not operation.safe_to_repeat:
            key_values = tuple(
                json.dumps(
                    _plain(node.parameters[field]),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for field in operation.effect_key_fields
            )
            effect = (operation.operation_id, *key_values)
            if effect in effects:
                _reject(
                    ActionValidationCode.DUPLICATE_EFFECT,
                    f"node {node_id!r} repeats a non-idempotent effect",
                    node_id=node_id,
                )
            effects.add(effect)
        facts.update(operation.postconditions)

    frozen_graph = ActionGraph(
        graph.plugin_id,
        graph.plugin_version,
        graph.adapter_sha256,
        tuple(node_by_id[node_id] for node_id in ordered_ids),
        tuple(sorted(graph.edges)),
    )
    graph_sha = hashlib.sha256(_graph_bytes(frozen_graph)).hexdigest()
    validation = json.dumps(
        {
            "graph_sha256": graph_sha,
            "initial_facts": sorted(initial_facts),
            "operations_sha256": registry.operations_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return ValidatedActionGraph(
        graph.plugin_id,
        graph.plugin_version,
        graph.adapter_sha256,
        registry.operations_sha256,
        graph_sha,
        hashlib.sha256(validation).hexdigest(),
        tuple(sorted(initial_facts)),
        tuple(node_by_id[node_id] for node_id in ordered_ids),
    )


__all__ = [
    "ActionEdge",
    "ActionGraph",
    "ActionNode",
    "ActionParameterSpec",
    "ActionRisk",
    "ActionValidationCode",
    "ActionValidationError",
    "ActionValueKind",
    "OperationRegistry",
    "OperationSpec",
    "ValidatedActionGraph",
    "load_operation_registry",
    "validate_action_graph",
]
