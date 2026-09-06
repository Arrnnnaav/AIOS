"""Approval-bound execution of a fully validated autonomous action graph."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from types import SimpleNamespace
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Sequence

from ghostcursor.action import (
    ActionGraph,
    ActionRisk,
    OperationRegistry,
    ValidatedActionGraph,
    validate_action_graph,
)
from ghostcursor.act_node import NodeRefused, Observation, execute_node
from ghostcursor.act_pacing import QUICK, Pace, interruptible_wait
from ghostcursor.act_protocol import (
    LifecycleState,
    PresentationRequest,
    Receipt,
    ReceiptPolicy,
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
    #: Screen rect of the document region this node changed, or None.
    #: PRESENTATION ONLY (D106) -- it exists so a session surface can show
    #: where a change landed, and nothing downstream may treat it as
    #: authority. Typed as four integers rather than an open data bag on
    #: purpose: a general dict here would be a channel for anything an
    #: adapter felt like sending, and presentation is all this may carry.
    region: tuple[int, int, int, int] | None = None


def _region_of(value) -> "tuple[int, int, int, int] | None":
    """Four integers, or nothing.

    Validated here rather than trusted, because it arrives from an adapter
    subprocess. A malformed rect is dropped rather than raised: this is
    presentation, and a highlight that cannot be drawn must never fail an
    authorized effect that already happened.
    """

    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    if any(isinstance(part, bool) or not isinstance(part, int) for part in value):
        return None
    left, top, right, bottom = value
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


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


@dataclass
class UiaNodeSession:
    """Everything a control-driving node needs, supplied by the caller.

    Kept out of `act_runtime` on purpose. The runtime decides WHETHER a node
    may run; this decides how it is observed, shown and dispatched, and a run
    that cannot do those things simply does not get one -- which is what makes
    "no effect without an acknowledged presentation" structural rather than a
    rule someone has to remember.
    """

    #: Reads the world through the signed read-only path. Called twice per
    #: node: once before the cue and once after it.
    observe: Callable[[object, str], Observation]
    #: Shows the cue and returns the overlay's receipts for it.
    present: Callable[
        [PresentationRequest, "Observation | None", Callable[[Receipt, float], None]],
        Sequence[Receipt],
    ]
    #: Dispatches the pattern on the control that was just compared.
    dispatch: Callable[[object, object, Observation], None]
    #: NOTE: this type deliberately has no `run` method. An earlier version
    #: had one, and a caller could have overridden it to return a verified
    #: outcome without ever calling the verifier -- the same bypass shape a
    #: review already found once in this file. Core calls `execute_node`
    #: itself and supplies the real verifier; the session only supplies edges.
    policy: ReceiptPolicy
    session_id: str
    clock: Callable[[], float] = lambda: time.monotonic() * 1000.0
    on_state: Callable[[object, LifecycleState], None] | None = None


@dataclass(frozen=True)
class PresentationSurface:
    """Where a control-driving node's cue is shown, and how long it may take.

    This is what a production caller supplies instead of a `UiaNodeSession`.
    The difference matters: a session carries `dispatch`, so a caller handing
    one in decides what a node does to the application. A surface can draw a
    cue and hand back receipts, and there is no path from it to an effect --
    the runtime composes the session itself, around the adapter host it owns
    and never exposes.

    That is why this is not a factory taking the host. A factory would be
    simpler and would give every caller the live adapter, which is strictly
    more authority than injecting a session already was.
    """

    #: Draws the cue and returns its receipts. `OverlaySession` in production.
    overlay: object
    #: Receipt deadlines. Data, not behaviour.
    policy: ReceiptPolicy


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
    observation_facts: Mapping[str, object] | None = None,
) -> AuthorizedAction:
    value = {
        "approval_sha256": approval.approval_sha256,
        "node_id": node.node_id,
        "operation_id": node.operation_id,
        "ordinal": ordinal,
        "parameters": _plain(node.parameters),
        "validation_sha256": validated.validation_sha256,
    }
    if observation_facts is not None:
        value["observation_facts"] = _plain(observation_facts)
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
    uia_session: "UiaNodeSession | None" = None,
    presentation: "PresentationSurface | None" = None,
    live_verifier: "VerifierHost | None" = None,
    pace: Pace = QUICK,
) -> ActRunResult:
    """Private effect seam used by production and hermetic contract tests."""

    events: list[ActEvent] = []
    completed: list[str] = []
    started = clock()

    def publish(kind: str, node, ordinal: int, detail: str, region=None) -> None:
        event = ActEvent(
            kind,
            getattr(node, "node_id", None),
            getattr(node, "operation_id", None),
            ordinal,
            len(validated.ordered_nodes),
            detail,
            clock() - started,
            _region_of(region),
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
    writes_artifact = any(
        not registry.operations[node.operation_id].draws_a_pointer
        for node in validated.ordered_nodes
    )
    if writes_artifact and Path(approval.output_path).exists():
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

    object_nodes = tuple(n for n in validated.ordered_nodes
                         if not registry.operations[n.operation_id].draws_a_pointer)
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
    uia_host = None
    try:
        if object_nodes:
            host.start()
        try:
            if object_nodes:
                host.preflight(
                    object_nodes,
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

        if uia_session is None and presentation is not None:
            # Composed HERE, after the host is running, because the session
            # reads and dispatches through that host. A caller cannot build
            # one for the same reason: it never gets the host.
            #
            # A live verifier is required rather than optional. `observe`
            # asks it what the document currently is, and that reading is the
            # semantic the drift check compares -- without it the node would
            # be left comparing identity against itself, which is the vacuous
            # check `act_uia_session` exists to avoid.
            if live_verifier is None:
                return ActRunResult(
                    ActRunPhase.EXECUTION,
                    ActRunCode.ADAPTER_FAILED,
                    "a control-driving run needs the plugin's signed "
                    "read-only live verifier, and this plugin ships none",
                    validated,
                    events=tuple(events),
                    output_path=approval.output_path,
                )
            from ghostcursor.act_uia_session import build_uia_session

            try:
                if getattr(descriptor, "uia_entrypoint", None) is None:
                    raise AdapterProtocolError("plugin ships no signed UIA adapter")
                uia_host = AdapterHost(
                    SimpleNamespace(
                        plugin_id=descriptor.plugin_id,
                        plugin_version=descriptor.plugin_version,
                        payload_root=descriptor.payload_root,
                        entrypoint=descriptor.uia_entrypoint,
                        adapter_sha256=descriptor.uia_adapter_sha256,
                    ),
                    session_nonce=secrets.token_hex(16),
                    session_context={"target": host.session_context["target"]},
                )
                uia_host.start()
                uia_session = build_uia_session(
                    host=uia_host,
                    verifier=live_verifier,
                    payload_root=Path(descriptor.payload_root),
                    overlay=presentation.overlay,
                    policy=presentation.policy,
                    session_id=approval.approval_id,
                    operation_for=lambda node: registry.operations[node.operation_id],
                    target={
                        "executable": approval.target.executable.casefold(),
                        "executable_version": approval.target.executable_version,
                        "hwnd": approval.target.hwnd,
                        "pid": approval.target.pid,
                    },
                    validation_sha256=validated.validation_sha256,
                    output_path=approval.output_path,
                    # A read may be abandoned when the operator stops; a
                    # dispatch may not, and is bounded by its own timeout.
                    cancel_event=controls.stop_event,
                )
            except Exception as exc:  # noqa: BLE001 - fail closed, never run
                return ActRunResult(
                    ActRunPhase.EXECUTION,
                    ActRunCode.ADAPTER_FAILED,
                    f"the presentation session could not be assembled: "
                    f"{type(exc).__name__}: {exc}",
                    validated,
                    events=tuple(events),
                    output_path=approval.output_path,
                )

        def _paced(milliseconds: int, node, ordinal: int) -> bool:
            """Wait, staying stoppable throughout. False means Stop was read.

            Sliced rather than slept, so Watch Build gives the user MORE
            chances to stop the run than Quick Build, not fewer. A plain
            sleep here would put the run inside an uninterruptible call for
            tenths of a second while D020 allows half a second for the whole
            abort path.
            """

            if milliseconds <= 0:
                return not controls.stop_event.is_set()
            return interruptible_wait(
                milliseconds,
                poll=lambda: not controls.stop_event.is_set(),
                clock=lambda: clock() * 1000.0,
            )

        for ordinal, node in enumerate(validated.ordered_nodes, 1):
            if not controls.wait_until_runnable() or not _paced(
                pace.before_node_ms, node, ordinal
            ):
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

            if operation.draws_a_pointer:
                # A control-driving node takes the three-observation path and
                # cannot run without an acknowledged presentation (D109). No
                # presenter means no UIA execution -- refused by construction
                # rather than by convention, because the alternative is an
                # effect the user never saw.
                if uia_session is None:
                    publish(
                        "refused",
                        node,
                        ordinal,
                        "this run has no presentation surface, so a "
                        "control-driving operation cannot be shown or run",
                    )
                    return ActRunResult(
                        ActRunPhase.EXECUTION,
                        ActRunCode.ADAPTER_FAILED,
                        "a UIA operation requires a presentation surface",
                        validated,
                        tuple(completed),
                        node.node_id,
                        tuple(events),
                        approval.output_path,
                    )
                publish("action_started", node, ordinal, "authorized action started")
                request = PresentationRequest(
                    session_id=uia_session.session_id,
                    cue_id=f"{node.node_id}:{ordinal}",
                    nonce=secrets.token_hex(16),
                    presentation_generation=1,
                    frame_generation=1,
                    geometry_required=True,
                )
                try:
                    # execute_node is called HERE, by core, with core's own
                    # verifier. The session contributes observe, present and
                    # dispatch and nothing else.
                    def authorize_observed(facts):
                        # The cue and confirmation can take seconds. The
                        # node-entry authority check is no longer fresh here.
                        if approval.expires_at < wall_clock():
                            raise AdapterProtocolError("approval expired during presentation")
                        if current_authority() != (
                            approval.active_index_sha256, approval.catalog_generation,
                            approval.plugin_version, approval.manifest_sha256,
                            approval.adapter_sha256,
                        ):
                            raise AdapterProtocolError("authority changed during presentation")
                        revalidate_target(approval.target)
                        return _authorize_node(
                            approval, validated, node=node, ordinal=ordinal,
                            observation_facts=facts,
                        )

                    outcome = execute_node(
                        node,
                        operation,
                        request=request,
                        policy=uia_session.policy,
                        observe=lambda mode: uia_session.observe(node, mode),
                        present=uia_session.present,
                        authorize=authorize_observed,
                        dispatch=lambda token, confirmed: uia_session.dispatch(
                            node, token, confirmed
                        ),
                        verify=lambda target, baseline: verify(
                            target, operation, baseline, approval
                        ),
                        clock=uia_session.clock,
                        # The operator's Stop, asked at the two boundaries
                        # where stopping is still free. Without it a Stop
                        # landing after the cue completed went unnoticed
                        # until the node ended.
                        should_continue=lambda: not controls.stop_event.is_set(),
                        on_state=(
                            None
                            if uia_session.on_state is None
                            else (lambda state: uia_session.on_state(node, state))
                        ),
                    )
                except NodeRefused as exc:
                    publish("action_failed", node, ordinal, exc.detail)
                    return ActRunResult(
                        ActRunPhase.EXECUTION,
                        ActRunCode.ADAPTER_FAILED,
                        f"{exc.code.value}: {exc.detail}",
                        validated,
                        tuple(completed),
                        node.node_id,
                        tuple(events),
                        approval.output_path,
                    )
                except Exception as exc:  # noqa: BLE001 - see below
                    # Everything else the session or the verifier can raise:
                    # a failed or empty verifier reading, a control that could
                    # not be read, the missing-authorization refusal, an
                    # incomplete dispatch, a bad selector, an adapter protocol
                    # fault from `choose_verifier`.
                    #
                    # These used to escape as unhandled exceptions, which is
                    # fail-CLOSED on the effect and fail-OPEN on the
                    # bookkeeping: the run record, its events and its output
                    # path were lost, `act_cli` never reached its staging
                    # cleanup so a partial artifact kept its staging file
                    # unlabelled, and the CLI died with a traceback and no
                    # result line. The object-model path already converts its
                    # failures into a result; this makes the two agree.
                    publish(
                        "action_failed",
                        node,
                        ordinal,
                        f"{type(exc).__name__}: {exc}",
                    )
                    return ActRunResult(
                        ActRunPhase.EXECUTION,
                        ActRunCode.ADAPTER_FAILED,
                        f"{type(exc).__name__}: {exc}",
                        validated,
                        tuple(completed),
                        node.node_id,
                        tuple(events),
                        approval.output_path,
                    )
                if not outcome.verified:
                    publish("verification_failed", node, ordinal, outcome.detail)
                    return ActRunResult(
                        ActRunPhase.EXECUTION,
                        ActRunCode.VERIFICATION_FAILED,
                        outcome.detail,
                        validated,
                        tuple(completed),
                        node.node_id,
                        tuple(events),
                        approval.output_path,
                    )
                completed.append(node.node_id)
                publish("action_completed", node, ordinal, outcome.detail)
                _paced(pace.after_node_ms, node, ordinal)
                continue

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
            publish(
                "action_completed",
                node,
                ordinal,
                response.detail,
                region=response.data.get("region"),
            )
            # The beat that lets the change register. A slide that appears and
            # is immediately replaced reads as a flicker, not as an action.
            # Zero in Quick Build, so this costs that mode nothing.
            _paced(pace.after_node_ms, node, ordinal)
    finally:
        try:
            if uia_host is not None:
                uia_host.stop()
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


def choose_verifier(artifact, live, operation, *, observation=None):
    """Which verifier may answer for this operation, and with what.

    Returns `(verifier, baseline, postconditions)`. Module level rather than a
    closure so it can be called directly: as a closure the only way to reach
    it was through a subprocess-spawning run, which meant the routing was
    effectively untested.

    Routing is by the OPERATION's signed backend declaration, never by
    anything a caller chooses. An object-model effect is a file and is
    verified by reading it; a UIA effect exists only in the running
    application and no file reflects it until somebody saves.

    A control-driving operation with no live verifier shipped is REFUSED
    rather than falling back to the artifact one. That fallback is what made
    a UIA effect look unverifiable when it was merely being asked the wrong
    question, and a silent fallback would hide it again.

    An object-model operation gets `None` and `()` so nothing extra is sent
    to a verifier that validates its request fields exactly -- including the
    one Phase A's 255/255 was measured against.
    """

    if getattr(operation, "backend", "object_model") == "object_model":
        return artifact, None, ()
    if live is None:
        raise AdapterProtocolError(
            f"operation {operation.operation_id!r} declares backend "
            f"{operation.backend!r} but the plugin ships no live_verifier; "
            "the artifact verifier cannot answer for a live effect"
        )
    if (not isinstance(observation, Observation)
            or not isinstance(observation.semantic, Mapping)
            or not observation.semantic):
        raise AdapterProtocolError("live verification requires the node's nonempty baseline")
    if not operation.postconditions:
        raise AdapterProtocolError("live verification requires declared postconditions")
    return live, observation.semantic, tuple(operation.postconditions)


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
    verify_observer: Callable[[str, Mapping[str, object]], None] | None = None,
    presentation: "PresentationSurface | None" = None,
    pace: Pace = QUICK,
) -> ActRunResult:
    """Production execution path with the plugin's separate signed verifier.

    ``verify_observer`` is told when verification starts and what it answered.
    It is an OBSERVER, not a wrapper: core calls the signed verifier itself,
    core keeps the answer, and the observer's return value is discarded. An
    earlier design handed the verifier callable to a diagnostic wrapper and
    asked it to return the same answer; nothing enforced that, so
    ``lambda verify: lambda *_a: True`` would have turned every verification
    into a success without the signed verifier running at all. A diagnostic
    seam on the production path must be incapable of that, not merely
    documented against it.

    The observer's ordinary exceptions are caught for the same reason in
    reverse: instrumentation must not be able to fail a run either. That is
    `Exception`, not `BaseException` -- swallowing a `KeyboardInterrupt` or a
    `SystemExit` would be worse than the failure it prevents -- so an observer
    raising one of those does propagate out, with `host.stop()` still running
    on the way. Fail-safe in direction, but not the blanket guarantee an
    earlier version of this docstring claimed.
    """

    verifier = VerifierHost(descriptor)

    # The LIVE-state verifier, when the plugin ships one. Routing is by the
    # OPERATION's signed backend declaration, not by anything the caller
    # chooses: an object-model effect is a file and is verified by reading
    # it; a UIA effect exists only in the running application and no file
    # reflects it until somebody saves. Before this, every node was verified
    # by the artifact verifier, so a UIA effect was checked by the one thing
    # that can only decline it (D032 review, F10-F12).
    live_verifier = None
    if getattr(descriptor, "live_verifier", None) is not None:
        live_verifier = VerifierHost(
            SimpleNamespace(
                plugin_id=descriptor.plugin_id,
                plugin_version=descriptor.plugin_version,
                payload_root=descriptor.payload_root,
                verifier=descriptor.live_verifier,
                verifier_sha256=descriptor.live_verifier_sha256,
            )
        )

    def _verifier_for(operation, observation):
        return choose_verifier(verifier, live_verifier, operation, observation=observation)

    def observe(phase: str, facts: Mapping[str, object]) -> None:
        if verify_observer is None:
            return
        try:
            verify_observer(phase, facts)
        except Exception:  # noqa: BLE001 - diagnostics never affect a run
            pass

    def verify(node, operation, _response, current_approval) -> bool:
        node_id = getattr(node, "node_id", None)
        observe("verify_started", {"node_id": node_id})
        started = time.monotonic()
        chosen, baseline, postconditions = _verifier_for(operation, _response)
        try:
            result = chosen.verify(
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
                **(
                    {}
                    if not postconditions
                    else {"baseline": baseline, "postconditions": postconditions}
                ),
            )
        except Exception as exc:
            observe(
                "verify_finished",
                {
                    "error": f"{type(exc).__name__}: {exc}",
                    "node_id": node_id,
                    "operation_id": getattr(node, "operation_id", None),
                    "seconds": time.monotonic() - started,
                    "verified": None,
                },
            )
            raise
        observe(
            "verify_finished",
            {
                "error": None,
                "node_id": node_id,
                "operation_id": getattr(node, "operation_id", None),
                "seconds": time.monotonic() - started,
                "verified": result.verified,
            },
        )
        return result.verified

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
        presentation=presentation,
        live_verifier=live_verifier,
        pace=pace,
    )


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


__all__ = [
    "ActControls",
    "PresentationSurface",
    "ActEvent",
    "ActRunCode",
    "ActRunPhase",
    "ActRunResult",
    "ActTarget",
    "choose_verifier",
    "UiaNodeSession",
    "AuthorizedAction",
    "PlanApproval",
    "approve_action_graph",
    "execute_approved_graph",
    "prepare_action_graph",
]
