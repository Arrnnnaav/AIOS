"""Approval-bound execution of a fully validated autonomous action graph."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping

from ghostcursor.action import (
    ActionGraph,
    ActionRisk,
    OperationRegistry,
    ValidatedActionGraph,
    validate_action_graph,
)
from ghostcursor.adapter_host import (
    AdapterHost,
    AdapterProtocolError,
    AdapterResponse,
    VerifierHost,
)


class ActRunPhase(str, Enum):
    VALIDATION = "validation"
    APPROVAL = "approval"
    EXECUTION = "execution"
    COMPLETE = "complete"


class ActRunCode(str, Enum):
    VALIDATION_REJECTED = "validation_rejected"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_STALE = "approval_stale"
    AUTHORITY_CHANGED = "authority_changed"
    TARGET_CHANGED = "target_changed"
    ADAPTER_FAILED = "adapter_failed"
    VERIFICATION_FAILED = "verification_failed"
    STOPPED = "stopped"
    COMPLETED = "completed"


@dataclass(frozen=True)
class ActTarget:
    hwnd: int
    pid: int
    executable: str
    executable_version: str


@dataclass(frozen=True)
class PlanApproval:
    approval_id: str
    validation_sha256: str
    plugin_id: str
    plugin_version: str
    adapter_sha256: str
    manifest_sha256: str
    active_index_sha256: str
    catalog_generation: int
    target: ActTarget
    output_path: str
    unattended: bool
    approved_at: float
    expires_at: float
    approval_sha256: str


@dataclass(frozen=True)
class AuthorizedAction:
    approval_sha256: str
    validation_sha256: str
    node_id: str
    operation_id: str
    ordinal: int
    authorization_sha256: str


@dataclass(frozen=True)
class ActEvent:
    type: str
    node_id: str | None
    operation_id: str | None
    ordinal: int
    total: int
    detail: str
    at_s: float


@dataclass(frozen=True)
class ActRunResult:
    phase: ActRunPhase
    code: ActRunCode
    detail: str
    validated: ValidatedActionGraph | None = None
    completed_node_ids: tuple[str, ...] = ()
    failed_node_id: str | None = None
    events: tuple[ActEvent, ...] = ()
    output_path: str | None = None

    @property
    def completed(self) -> bool:
        return self.code is ActRunCode.COMPLETED


@dataclass
class ActControls:
    """Thread-safe stop/pause state shared with the manager and CLI."""

    stop_event: threading.Event = field(default_factory=threading.Event)
    _resume_event: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        self._resume_event.set()

    def stop(self) -> None:
        self.stop_event.set()
        self._resume_event.set()

    def pause(self) -> None:
        self._resume_event.clear()

    def resume(self) -> None:
        self._resume_event.set()

    @property
    def paused(self) -> bool:
        return not self._resume_event.is_set()

    def wait_until_runnable(self) -> bool:
        while not self.stop_event.is_set():
            if self._resume_event.wait(timeout=0.05):
                return True
        return False


def approve_action_graph(
    validated: ValidatedActionGraph,
    registry: OperationRegistry,
    *,
    manifest_sha256: str,
    active_index_sha256: str,
    catalog_generation: int,
    target: ActTarget,
    output_path: Path,
    owned_output_root: Path | None = None,
    unattended: bool = False,
    lifetime_s: float = 300.0,
    now: float | None = None,
) -> PlanApproval:
    """Bind one explicit approval to every authority-bearing input."""

    if (
        registry.plugin_id != validated.plugin_id
        or registry.plugin_version != validated.plugin_version
        or registry.adapter_sha256 != validated.adapter_sha256
        or registry.operations_sha256 != validated.operations_sha256
    ):
        raise ValueError("approval registry disagrees with validation")
    if unattended and any(
        registry.operations[node.operation_id].risk is not ActionRisk.LOW
        for node in validated.ordered_nodes
    ):
        raise ValueError("unattended Act accepts only low-risk operations")
    if lifetime_s <= 0 or lifetime_s > 3600:
        raise ValueError("approval lifetime must be in (0, 3600]")
    if (
        target.hwnd <= 0
        or target.pid <= 0
        or not target.executable
        or not target.executable_version
    ):
        raise ValueError("approval target is invalid")
    if len(manifest_sha256) != 64 or len(active_index_sha256) != 64:
        raise ValueError("approval authority digest is invalid")
    output = Path(output_path).resolve()
    if output.exists():
        raise ValueError("Act never overwrites an existing output artifact")
    declared_output_values = [
        node.parameters["output_path"]
        for node in validated.ordered_nodes
        if "output_path" in node.parameters
    ]
    if any(not isinstance(value, str) for value in declared_output_values):
        raise ValueError("action graph output path is invalid")
    declared_outputs = {str(Path(value).resolve()) for value in declared_output_values}
    if declared_outputs and declared_outputs != {str(output)}:
        raise ValueError("action graph output disagrees with the approved artifact")
    if unattended:
        if owned_output_root is None:
            raise ValueError("unattended Act requires an owned output root")
        root = Path(owned_output_root).resolve()
        try:
            output.relative_to(root)
        except ValueError as exc:
            raise ValueError("unattended output escapes the owned root") from exc
    approved_at = time.time() if now is None else now
    approval_id = secrets.token_hex(16)
    value = _approval_payload(
        approval_id=approval_id,
        validated=validated,
        manifest_sha256=manifest_sha256,
        active_index_sha256=active_index_sha256,
        catalog_generation=catalog_generation,
        target=target,
        output_path=str(output),
        unattended=unattended,
        expires_at=approved_at + lifetime_s,
    )
    digest = _digest(value)
    return PlanApproval(
        approval_id=approval_id,
        validation_sha256=validated.validation_sha256,
        plugin_id=validated.plugin_id,
        plugin_version=validated.plugin_version,
        adapter_sha256=validated.adapter_sha256,
        manifest_sha256=manifest_sha256,
        active_index_sha256=active_index_sha256,
        catalog_generation=catalog_generation,
        target=target,
        output_path=str(output),
        unattended=unattended,
        approved_at=approved_at,
        expires_at=approved_at + lifetime_s,
        approval_sha256=digest,
    )


def _approval_payload(
    *,
    approval_id: str,
    validated: ValidatedActionGraph,
    manifest_sha256: str,
    active_index_sha256: str,
    catalog_generation: int,
    target: ActTarget,
    output_path: str,
    unattended: bool,
    expires_at: float,
) -> dict[str, object]:
    return {
        "active_index_sha256": active_index_sha256,
        "adapter_sha256": validated.adapter_sha256,
        "approval_id": approval_id,
        "catalog_generation": catalog_generation,
        "expires_at": expires_at,
        "manifest_sha256": manifest_sha256,
        "output_path": output_path,
        "plugin_id": validated.plugin_id,
        "plugin_version": validated.plugin_version,
        "target": {
            "executable": target.executable.casefold(),
            "executable_version": target.executable_version,
            "hwnd": target.hwnd,
            "pid": target.pid,
        },
        "unattended": unattended,
        "validation_sha256": validated.validation_sha256,
    }


def _digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _approval_is_exact(approval: PlanApproval, validated: ValidatedActionGraph) -> bool:
    expected = _digest(
        _approval_payload(
            approval_id=approval.approval_id,
            validated=validated,
            manifest_sha256=approval.manifest_sha256,
            active_index_sha256=approval.active_index_sha256,
            catalog_generation=approval.catalog_generation,
            target=approval.target,
            output_path=approval.output_path,
            unattended=approval.unattended,
            expires_at=approval.expires_at,
        )
    )
    return secrets.compare_digest(expected, approval.approval_sha256)


def _authorize_node(
    approval: PlanApproval,
    validated: ValidatedActionGraph,
    *,
    node,
    ordinal: int,
) -> AuthorizedAction:
    value = {
        "approval_sha256": approval.approval_sha256,
        "node_id": node.node_id,
        "operation_id": node.operation_id,
        "ordinal": ordinal,
        "parameters": _plain(node.parameters),
        "validation_sha256": validated.validation_sha256,
    }
    digest = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return AuthorizedAction(
        approval.approval_sha256,
        validated.validation_sha256,
        node.node_id,
        node.operation_id,
        ordinal,
        digest,
    )


def _execute_approved_graph(
    validated: ValidatedActionGraph,
    registry: OperationRegistry,
    approval: PlanApproval,
    *,
    descriptor,
    current_authority: Callable[[], tuple[str, int, str, str, str]],
    revalidate_target: Callable[[ActTarget], None],
    verify: Callable[[object, object, AdapterResponse, PlanApproval], bool],
    controls: ActControls,
    event_sink: Callable[[ActEvent], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
) -> ActRunResult:
    """Private effect seam used by production and hermetic contract tests."""

    events: list[ActEvent] = []
    completed: list[str] = []
    started = clock()

    def publish(kind: str, node, ordinal: int, detail: str) -> None:
        event = ActEvent(
            kind,
            getattr(node, "node_id", None),
            getattr(node, "operation_id", None),
            ordinal,
            len(validated.ordered_nodes),
            detail,
            clock() - started,
        )
        events.append(event)
        if event_sink is not None:
            event_sink(event)

    if (
        not _approval_is_exact(approval, validated)
        or approval.validation_sha256 != validated.validation_sha256
        or approval.plugin_id != validated.plugin_id
        or approval.plugin_version != validated.plugin_version
        or approval.adapter_sha256 != validated.adapter_sha256
        or approval.expires_at < wall_clock()
    ):
        return ActRunResult(
            ActRunPhase.APPROVAL,
            ActRunCode.APPROVAL_STALE,
            "approval does not bind the validated action graph",
            validated,
            output_path=approval.output_path,
        )

    if (
        registry.plugin_id != validated.plugin_id
        or registry.plugin_version != validated.plugin_version
        or registry.adapter_sha256 != validated.adapter_sha256
        or registry.operations_sha256 != validated.operations_sha256
        or descriptor.plugin_id != approval.plugin_id
        or descriptor.plugin_version != approval.plugin_version
        or descriptor.adapter_sha256 != approval.adapter_sha256
        or descriptor.manifest_sha256 != approval.manifest_sha256
    ):
        return ActRunResult(
            ActRunPhase.APPROVAL,
            ActRunCode.APPROVAL_STALE,
            "adapter authority disagrees with the approved graph",
            validated,
            output_path=approval.output_path,
        )
    if Path(approval.output_path).exists():
        return ActRunResult(
            ActRunPhase.APPROVAL,
            ActRunCode.APPROVAL_STALE,
            "approved output path now exists",
            validated,
            output_path=approval.output_path,
        )

    try:
        active_sha, generation, plugin_version, manifest_sha, adapter_sha = (
            current_authority()
        )
        if (
            active_sha != approval.active_index_sha256
            or generation != approval.catalog_generation
            or plugin_version != approval.plugin_version
            or manifest_sha != approval.manifest_sha256
            or adapter_sha != approval.adapter_sha256
        ):
            raise RuntimeError("active adapter authority changed")
    except Exception as exc:
        return ActRunResult(
            ActRunPhase.APPROVAL,
            ActRunCode.AUTHORITY_CHANGED,
            f"{type(exc).__name__}: {exc}",
            validated,
            output_path=approval.output_path,
        )
    try:
        revalidate_target(approval.target)
    except Exception as exc:
        return ActRunResult(
            ActRunPhase.APPROVAL,
            ActRunCode.TARGET_CHANGED,
            f"{type(exc).__name__}: {exc}",
            validated,
            output_path=approval.output_path,
        )

    host = AdapterHost(
        descriptor,
        session_nonce=secrets.token_hex(16),
        session_context={
            "output_path": approval.output_path,
            "target": {
                "executable": approval.target.executable.casefold(),
                "executable_version": approval.target.executable_version,
                "hwnd": approval.target.hwnd,
                "pid": approval.target.pid,
            },
        },
    )
    try:
        host.start()
        try:
            host.preflight(
                validated.ordered_nodes,
                validation_sha256=validated.validation_sha256,
                cancel_event=controls.stop_event,
            )
        except AdapterProtocolError as exc:
            return ActRunResult(
                ActRunPhase.VALIDATION,
                ActRunCode.VALIDATION_REJECTED,
                str(exc),
                validated,
                events=tuple(events),
                output_path=approval.output_path,
            )
        for ordinal, node in enumerate(validated.ordered_nodes, 1):
            if not controls.wait_until_runnable():
                publish("stopped", node, ordinal, "stopped before action")
                return ActRunResult(
                    ActRunPhase.EXECUTION,
                    ActRunCode.STOPPED,
                    "Act stopped",
                    validated,
                    tuple(completed),
                    node.node_id,
                    tuple(events),
                    approval.output_path,
                )
            try:
                active_sha, generation, plugin_version, manifest_sha, adapter_sha = (
                    current_authority()
                )
                if (
                    active_sha != approval.active_index_sha256
                    or generation != approval.catalog_generation
                    or plugin_version != approval.plugin_version
                    or manifest_sha != approval.manifest_sha256
                    or adapter_sha != approval.adapter_sha256
                ):
                    raise RuntimeError("active adapter authority changed")
            except Exception as exc:
                publish("refused", node, ordinal, f"authority refused: {exc}")
                return ActRunResult(
                    ActRunPhase.EXECUTION,
                    ActRunCode.AUTHORITY_CHANGED,
                    f"{type(exc).__name__}: {exc}",
                    validated,
                    tuple(completed),
                    node.node_id,
                    tuple(events),
                    approval.output_path,
                )
            try:
                revalidate_target(approval.target)
            except Exception as exc:
                publish("refused", node, ordinal, f"target refused: {exc}")
                return ActRunResult(
                    ActRunPhase.EXECUTION,
                    ActRunCode.TARGET_CHANGED,
                    f"{type(exc).__name__}: {exc}",
                    validated,
                    tuple(completed),
                    node.node_id,
                    tuple(events),
                    approval.output_path,
                )
            operation = registry.operations[node.operation_id]
            token = _authorize_node(approval, validated, node=node, ordinal=ordinal)
            publish("action_started", node, ordinal, "authorized action started")
            try:
                response = host.execute(
                    node.operation_id,
                    node.parameters,
                    node_id=node.node_id,
                    ordinal=ordinal,
                    authorization_sha256=token.authorization_sha256,
                    validation_sha256=validated.validation_sha256,
                    timeout_s=operation.timeout_s,
                    cancel_event=controls.stop_event,
                )
            except AdapterProtocolError as exc:
                publish("action_failed", node, ordinal, str(exc))
                code = (
                    ActRunCode.STOPPED
                    if controls.stop_event.is_set()
                    else ActRunCode.ADAPTER_FAILED
                )
                return ActRunResult(
                    ActRunPhase.EXECUTION,
                    code,
                    str(exc),
                    validated,
                    tuple(completed),
                    node.node_id,
                    tuple(events),
                    approval.output_path,
                )
            if response.outcome != "completed":
                publish("action_failed", node, ordinal, response.detail)
                return ActRunResult(
                    ActRunPhase.EXECUTION,
                    ActRunCode.ADAPTER_FAILED,
                    response.detail,
                    validated,
                    tuple(completed),
                    node.node_id,
                    tuple(events),
                    approval.output_path,
                )
            try:
                verified = verify(node, operation, response, approval)
            except Exception as exc:
                publish("verification_failed", node, ordinal, f"verifier failed: {exc}")
                return ActRunResult(
                    ActRunPhase.EXECUTION,
                    ActRunCode.VERIFICATION_FAILED,
                    f"{type(exc).__name__}: {exc}",
                    validated,
                    tuple(completed),
                    node.node_id,
                    tuple(events),
                    approval.output_path,
                )
            if not verified:
                publish(
                    "verification_failed",
                    node,
                    ordinal,
                    "declared postcondition was not observed",
                )
                return ActRunResult(
                    ActRunPhase.EXECUTION,
                    ActRunCode.VERIFICATION_FAILED,
                    "declared postcondition was not observed",
                    validated,
                    tuple(completed),
                    node.node_id,
                    tuple(events),
                    approval.output_path,
                )
            completed.append(node.node_id)
            publish("action_completed", node, ordinal, response.detail)
    finally:
        host.stop()
    publish("completed", None, len(validated.ordered_nodes), "all actions verified")
    return ActRunResult(
        ActRunPhase.COMPLETE,
        ActRunCode.COMPLETED,
        "Act plan completed",
        validated,
        tuple(completed),
        events=tuple(events),
        output_path=approval.output_path,
    )


def prepare_action_graph(
    graph: ActionGraph,
    registry: OperationRegistry,
    *,
    initial_facts: tuple[str, ...] = (),
) -> ValidatedActionGraph:
    """Public, side-effect-free full-graph validation boundary."""

    return validate_action_graph(graph, registry, initial_facts=initial_facts)


def execute_approved_graph(
    validated: ValidatedActionGraph,
    registry: OperationRegistry,
    approval: PlanApproval,
    *,
    descriptor,
    current_authority: Callable[[], tuple[str, int, str, str, str]],
    revalidate_target: Callable[[ActTarget], None],
    controls: ActControls,
    event_sink: Callable[[ActEvent], None] | None = None,
    instrument_verify: Callable[[Callable], Callable] | None = None,
) -> ActRunResult:
    """Production execution path with the plugin's separate signed verifier.

    ``instrument_verify`` wraps the verification call for diagnostics only.  It
    receives the verifier callable and must return one with the same contract:
    the wrapper may observe and time, but the answer it returns is the
    verifier's own.  It is never consulted about authority, and production runs
    leave it unset.
    """

    verifier = VerifierHost(descriptor)

    def verify(node, operation, _response, current_approval) -> bool:
        result = verifier.verify(
            node=node,
            validation_sha256=validated.validation_sha256,
            output_path=current_approval.output_path,
            target={
                "executable": current_approval.target.executable.casefold(),
                "executable_version": current_approval.target.executable_version,
                "hwnd": current_approval.target.hwnd,
                "pid": current_approval.target.pid,
            },
            timeout_s=min(30.0, max(2.0, operation.timeout_s)),
            cancel_event=controls.stop_event,
        )
        return result.verified

    if instrument_verify is not None:
        verify = instrument_verify(verify)

    return _execute_approved_graph(
        validated,
        registry,
        approval,
        descriptor=descriptor,
        current_authority=current_authority,
        revalidate_target=revalidate_target,
        verify=verify,
        controls=controls,
        event_sink=event_sink,
    )


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


__all__ = [
    "ActControls",
    "ActEvent",
    "ActRunCode",
    "ActRunPhase",
    "ActRunResult",
    "ActTarget",
    "AuthorizedAction",
    "PlanApproval",
    "approve_action_graph",
    "execute_approved_graph",
    "prepare_action_graph",
]
