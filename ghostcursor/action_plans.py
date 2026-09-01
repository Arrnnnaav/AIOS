"""Signed plugin-owned templates that materialize bounded action graphs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

from ghostcursor.action import (
    MAX_ACTION_EDGES,
    MAX_ACTION_NODES,
    ActionEdge,
    ActionGraph,
    ActionNode,
    OperationRegistry,
    ValidatedActionGraph,
    validate_action_graph,
)


ACTION_PLAN_INDEX_PATH = "ghostcursor/action-plans.json"
MAX_PLAN_INDEX_BYTES = 256 * 1024
MAX_PLAN_BYTES = 2 * 1024 * 1024
_PLAN_ID_RE = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+")
_INTENT_ID_RE = re.compile(r"[A-Z][A-Z0-9_]*")
_PARAMETER_RE = re.compile(r"[a-z][a-z0-9_]*")
_SHA_RE = re.compile(r"[0-9a-f]{64}")


class ActionPlanError(ValueError):
    pass


@dataclass(frozen=True)
class ActionPlanParameter:
    kind: str
    required: bool


@dataclass(frozen=True)
class ActionPlanTemplate:
    plan_id: str
    intent_id: str
    plugin_id: str
    plugin_version: str
    adapter_sha256: str
    plan_sha256: str
    parameters: Mapping[str, ActionPlanParameter]
    nodes: tuple[Mapping[str, Any], ...]
    edges: tuple[ActionEdge, ...]


def _strict(raw: bytes, *, label: str, limit: int) -> dict[str, Any]:
    if len(raw) > limit or raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
        raise ActionPlanError(f"{label} bytes are invalid")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ActionPlanError(f"{label} is not UTF-8") from exc

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ActionPlanError(f"{label} repeats key {key!r}")
            value[key] = item
        return value

    try:
        value = json.loads(text, object_pairs_hook=pairs)
    except json.JSONDecodeError as exc:
        raise ActionPlanError(f"{label} is not JSON") from exc
    if not isinstance(value, dict):
        raise ActionPlanError(f"{label} must be an object")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    if canonical != raw.removesuffix(b"\n"):
        raise ActionPlanError(f"{label} is not canonical JSON")
    return value


def _safe_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ActionPlanError("action plan path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ActionPlanError("action plan path is unsafe")
    if not value.startswith("ghostcursor/action-plans/") or not value.endswith(".json"):
        raise ActionPlanError("action plan path is outside its signed namespace")
    return value


def load_action_plan_templates(
    index_raw: bytes,
    files: Mapping[str, bytes],
    *,
    plugin_id: str,
    plugin_version: str,
    adapter_sha256: str,
) -> Mapping[str, ActionPlanTemplate]:
    index = _strict(index_raw, label="action plan index", limit=MAX_PLAN_INDEX_BYTES)
    if set(index) != {"plans", "plugin_id", "plugin_version", "schema_version"}:
        raise ActionPlanError("action plan index fields are invalid")
    if (
        index["schema_version"] != 1
        or index["plugin_id"] != plugin_id
        or index["plugin_version"] != plugin_version
    ):
        raise ActionPlanError("action plan index authority disagrees")
    declared = index["plans"]
    if not isinstance(declared, dict) or not declared or len(declared) > 64:
        raise ActionPlanError("action plan index is empty or too large")
    templates = {}
    seen_intents = set()
    for plan_id, item in declared.items():
        if not isinstance(plan_id, str) or _PLAN_ID_RE.fullmatch(plan_id) is None:
            raise ActionPlanError("action plan id is invalid")
        if not isinstance(item, dict) or set(item) != {
            "intent_id",
            "parameters",
            "path",
            "sha256",
        }:
            raise ActionPlanError(f"action plan {plan_id!r} index entry is invalid")
        intent_id = item["intent_id"]
        if (
            not isinstance(intent_id, str)
            or _INTENT_ID_RE.fullmatch(intent_id) is None
            or intent_id in seen_intents
        ):
            raise ActionPlanError("action plan intent is invalid or duplicated")
        seen_intents.add(intent_id)
        path = _safe_path(item["path"])
        digest = item["sha256"]
        if (
            not isinstance(digest, str)
            or _SHA_RE.fullmatch(digest) is None
            or path not in files
        ):
            raise ActionPlanError(f"action plan {plan_id!r} file binding is invalid")
        raw = files[path]
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ActionPlanError(f"action plan {plan_id!r} digest disagrees")
        parameters_value = item["parameters"]
        if not isinstance(parameters_value, dict) or len(parameters_value) > 16:
            raise ActionPlanError("action plan parameters are invalid")
        parameters = {}
        for name, spec in parameters_value.items():
            if (
                not isinstance(name, str)
                or _PARAMETER_RE.fullmatch(name) is None
                or not isinstance(spec, dict)
                or set(spec) != {"kind", "required"}
                or spec["kind"] not in {"string", "integer", "number", "boolean"}
                or type(spec["required"]) is not bool
            ):
                raise ActionPlanError("action plan parameter declaration is invalid")
            parameters[name] = ActionPlanParameter(spec["kind"], spec["required"])
        plan = _strict(raw, label=f"action plan {plan_id}", limit=MAX_PLAN_BYTES)
        if (
            set(plan) != {"edges", "nodes", "plan_id", "schema_version"}
            or plan["schema_version"] != 1
            or plan["plan_id"] != plan_id
        ):
            raise ActionPlanError(f"action plan {plan_id!r} fields disagree")
        nodes_value, edges_value = plan["nodes"], plan["edges"]
        if (
            not isinstance(nodes_value, list)
            or not 1 <= len(nodes_value) <= MAX_ACTION_NODES
        ):
            raise ActionPlanError(f"action plan {plan_id!r} node count is invalid")
        if not isinstance(edges_value, list) or len(edges_value) > MAX_ACTION_EDGES:
            raise ActionPlanError(f"action plan {plan_id!r} edge count is invalid")
        nodes = []
        for node in nodes_value:
            if (
                not isinstance(node, dict)
                or set(node) != {"node_id", "operation_id", "parameters"}
                or not isinstance(node["parameters"], dict)
            ):
                raise ActionPlanError(f"action plan {plan_id!r} node is invalid")
            _validate_markers(node["parameters"], parameters)
            nodes.append(_freeze(node))
        edges = []
        for edge in edges_value:
            if not isinstance(edge, dict) or set(edge) != {"after", "before"}:
                raise ActionPlanError(f"action plan {plan_id!r} edge is invalid")
            edges.append(ActionEdge(edge["before"], edge["after"]))
        templates[plan_id] = ActionPlanTemplate(
            plan_id,
            intent_id,
            plugin_id,
            plugin_version,
            adapter_sha256,
            digest,
            MappingProxyType(parameters),
            tuple(nodes),
            tuple(edges),
        )
    return MappingProxyType(templates)


def _validate_markers(
    value: Any, parameters: Mapping[str, ActionPlanParameter]
) -> None:
    if isinstance(value, Mapping):
        if set(value) == {"$parameter"}:
            if value["$parameter"] not in parameters:
                raise ActionPlanError("action plan names an undeclared parameter")
            return
        for item in value.values():
            _validate_markers(item, parameters)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_markers(item, parameters)


def _materialize(value: Any, values: Mapping[str, Any]) -> Any:
    if isinstance(value, Mapping):
        if set(value) == {"$parameter"}:
            return values[value["$parameter"]]
        return {key: _materialize(item, values) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_materialize(item, values) for item in value]
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def materialize_action_plan(
    template: ActionPlanTemplate,
    values: Mapping[str, Any],
    registry: OperationRegistry,
) -> ValidatedActionGraph:
    missing = {
        name
        for name, spec in template.parameters.items()
        if spec.required and name not in values
    }
    extra = set(values) - set(template.parameters)
    if missing or extra:
        raise ActionPlanError(
            f"action plan arguments disagree; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    for name, value in values.items():
        kind = template.parameters[name].kind
        valid = (
            (kind == "string" and isinstance(value, str))
            or (kind == "integer" and type(value) is int)
            or (kind == "number" and type(value) in {int, float})
            or (kind == "boolean" and type(value) is bool)
        )
        if not valid:
            raise ActionPlanError(f"action plan argument {name!r} has the wrong type")
    nodes = tuple(
        ActionNode(
            node["node_id"],
            node["operation_id"],
            _materialize(node["parameters"], values),
        )
        for node in template.nodes
    )
    return validate_action_graph(
        ActionGraph(
            template.plugin_id,
            template.plugin_version,
            template.adapter_sha256,
            nodes,
            template.edges,
        ),
        registry,
    )


__all__ = [
    "ACTION_PLAN_INDEX_PATH",
    "ActionPlanError",
    "ActionPlanParameter",
    "ActionPlanTemplate",
    "load_action_plan_templates",
    "materialize_action_plan",
]
