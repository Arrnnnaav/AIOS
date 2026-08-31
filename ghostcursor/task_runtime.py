"""Fail-closed execution of validated single-plugin capability graphs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from ghostcursor.task_graph import (
    CapabilityRegistry,
    TaskGraph,
    TaskGraphValidationError,
    ValidatedTaskGraph,
    capability_registry_sha256,
    validate_task_graph,
)
from ghostcursor.session import GuidanceValue


class TaskRunPhase(str, Enum):
    VALIDATION = "validation"
    EXECUTION = "execution"
    COMPLETE = "complete"


class TaskRunCode(str, Enum):
    COMPLETED = "completed"
    VALIDATION_REJECTED = "validation_rejected"
    AUTHORITY_UNAVAILABLE = "authority_unavailable"
    AUTHORITY_CHANGED = "authority_changed"
    AUTHORIZATION_REFUSED = "authorization_refused"
    TARGET_NOT_RUNNING = "target_not_running"
    TARGET_CHOICE_REQUIRED = "target_choice_required"
    NODE_FAILED = "node_failed"


@dataclass(frozen=True)
class TaskGraphRunResult:
    """One graph outcome with validation and runtime failures kept distinct."""

    phase: TaskRunPhase
    code: TaskRunCode
    detail: str
    validated: ValidatedTaskGraph | None = None
    completed_node_ids: tuple[str, ...] = ()
    failed_node_id: str | None = None
    target_candidates: tuple[object, ...] = ()

    @property
    def completed(self) -> bool:
        return self.code is TaskRunCode.COMPLETED


def _current_registry(context, plugin_id: str) -> CapabilityRegistry:
    registry = context.registries.get(plugin_id)
    if registry is None:
        raise LookupError(f"plugin {plugin_id!r} has no active capability registry")
    return registry


def _same_validation_epoch(
    validated: ValidatedTaskGraph,
    registry: CapabilityRegistry,
) -> bool:
    return (
        registry.plugin_id == validated.plugin_id
        and registry.plugin_version == validated.plugin_version
        and registry.catalog_sha256 == validated.catalog_sha256
        and registry.catalog_generation == validated.catalog_generation
        and capability_registry_sha256(registry) == validated.registry_sha256
    )


def _authorize_capability(catalog, capability):
    """Cross the canonical intent gate using only the signed exact phrase."""

    from ghostcursor.packs.compile import EXACT_CONFIDENCE
    from ghostcursor.reasoning.planner import (
        CandidateSource,
        IntentCandidate,
        authorize_intent,
    )

    return authorize_intent(
        catalog,
        capability.authorization_goal,
        IntentCandidate(
            CandidateSource.DETERMINISTIC,
            capability.intent_id,
            EXACT_CONFIDENCE,
            "signed capability exact phrase",
        ),
    )


def _guidance_values(node) -> tuple[GuidanceValue, ...]:
    """Canonical presentation-only view of already-validated node parameters."""

    return tuple(
        GuidanceValue(name, value)
        for name, value in sorted(node.parameters.items())
    )


def _execute_task_graph(
    graph: TaskGraph,
    *,
    initial_facts: tuple[str, ...],
    target_title_re: str | None,
    target_hwnd: int | None,
    seconds_per_node: float,
    load_context: Callable[[], object],
    authorize: Callable[[object, object], object],
    bind: Callable[..., object],
    run: Callable[..., int],
) -> TaskGraphRunResult:
    """Private seam: tests may replace effects, never production authority."""

    try:
        initial_context = load_context()
        registry = _current_registry(initial_context, graph.plugin_id)
        validated = validate_task_graph(
            graph,
            registry,
            initial_facts=initial_facts,
        )
    except TaskGraphValidationError as exc:
        return TaskGraphRunResult(
            TaskRunPhase.VALIDATION,
            TaskRunCode.VALIDATION_REJECTED,
            f"{exc.code.value}: {exc}",
            failed_node_id=exc.node_id,
        )
    except Exception as exc:
        return TaskGraphRunResult(
            TaskRunPhase.VALIDATION,
            TaskRunCode.AUTHORITY_UNAVAILABLE,
            f"{type(exc).__name__}: {exc}",
        )

    completed: list[str] = []
    bound_target_hwnd = target_hwnd
    for node in validated.ordered_nodes:
        try:
            # A disable, upgrade, registry replacement, or any active-catalog
            # publication after validation invalidates the complete proposal.
            # Nothing silently revalidates the remaining suffix against a new
            # authority epoch.
            context = load_context()
            current_registry = _current_registry(context, validated.plugin_id)
            if not _same_validation_epoch(validated, current_registry):
                return TaskGraphRunResult(
                    TaskRunPhase.EXECUTION,
                    TaskRunCode.AUTHORITY_CHANGED,
                    "active capability authority changed after graph validation",
                    validated,
                    tuple(completed),
                    node.node_id,
                )
            capability = current_registry.capabilities[node.capability_id]
            authorization = authorize(context.catalog, capability)
            token = getattr(authorization, "authorized", None)
            if token is None:
                return TaskGraphRunResult(
                    TaskRunPhase.EXECUTION,
                    TaskRunCode.AUTHORIZATION_REFUSED,
                    getattr(authorization, "explanation", "intent authorization refused"),
                    validated,
                    tuple(completed),
                    node.node_id,
                )
            workflow = bind(
                token,
                capability.authorization_goal,
                target_title_re=target_title_re,
                target_hwnd=bound_target_hwnd,
            )
            workflow_hwnd = getattr(getattr(workflow, "target", None), "hwnd", None)
            if bound_target_hwnd is None and workflow_hwnd is not None:
                bound_target_hwnd = int(workflow_hwnd)
            elif (
                bound_target_hwnd is not None
                and workflow_hwnd is not None
                and int(workflow_hwnd) != bound_target_hwnd
            ):
                raise RuntimeError("bound workflow changed the graph target HWND")
            exit_code = run(
                workflow,
                seconds=seconds_per_node,
                guidance_values=_guidance_values(node),
            )
        except Exception as exc:  # fail closed at the node boundary
            name = type(exc).__name__
            code = {
                "TargetNotRunning": TaskRunCode.TARGET_NOT_RUNNING,
                "TargetChoiceRequired": TaskRunCode.TARGET_CHOICE_REQUIRED,
                "WorkflowUnavailable": TaskRunCode.AUTHORITY_CHANGED,
            }.get(name, TaskRunCode.NODE_FAILED)
            return TaskGraphRunResult(
                TaskRunPhase.EXECUTION,
                code,
                f"{name}: {exc}",
                validated,
                tuple(completed),
                node.node_id,
                tuple(getattr(exc, "candidates", ())),
            )
        if exit_code != 0:
            return TaskGraphRunResult(
                TaskRunPhase.EXECUTION,
                TaskRunCode.NODE_FAILED,
                f"node {node.node_id!r} exited with code {exit_code}",
                validated,
                tuple(completed),
                node.node_id,
            )
        completed.append(node.node_id)

    return TaskGraphRunResult(
        TaskRunPhase.COMPLETE,
        TaskRunCode.COMPLETED,
        "task graph completed",
        validated,
        tuple(completed),
    )


def execute_task_graph(
    graph: TaskGraph,
    *,
    initial_facts: tuple[str, ...] = (),
    target_title_re: str | None = None,
    target_hwnd: int | None = None,
    seconds_per_node: float = 60.0,
) -> TaskGraphRunResult:
    """Validate then execute a graph through production-selected authority.

    The public boundary accepts proposal data and operator narrowing only. It
    deliberately offers no catalog loader, authorizer, window reader, binder,
    or workflow runner injection seam.
    """

    if seconds_per_node <= 0:
        return TaskGraphRunResult(
            TaskRunPhase.VALIDATION,
            TaskRunCode.VALIDATION_REJECTED,
            "seconds_per_node must be positive",
        )

    from ghostcursor.packs.workflow import bind_workflow
    from ghostcursor.plugins.platform import load_composition_context
    from ghostcursor.run import run_tour_for_workflow

    return _execute_task_graph(
        graph,
        initial_facts=initial_facts,
        target_title_re=target_title_re,
        target_hwnd=target_hwnd,
        seconds_per_node=seconds_per_node,
        load_context=load_composition_context,
        authorize=_authorize_capability,
        bind=bind_workflow,
        run=run_tour_for_workflow,
    )
