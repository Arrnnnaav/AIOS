"""Production Act planning and execution over enabled signed plugin authority."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ghostcursor.act_runtime import (
    ActControls,
    ActTarget,
    approve_action_graph,
    execute_approved_graph,
)
from ghostcursor.action_plans import materialize_action_plan
from ghostcursor.packs.compile import compile_matcher
from ghostcursor.packs.workflow import (
    live_window_reader,
    live_windows_for,
    resolve_target,
)
from ghostcursor.plugins.platform import production_store
from ghostcursor.reasoning.planner import (
    CandidateSource,
    IntentCandidate,
    authorize_intent,
)


def _emit(kind: str, **values) -> None:
    print(
        json.dumps({"type": kind, **values}, sort_keys=True, separators=(",", ":")),
        flush=True,
    )


def _revalidate(target: ActTarget) -> None:
    current = live_window_reader()(target.hwnd)
    if current is None:
        raise RuntimeError("approved target no longer exists")
    if current.app.process_id != target.pid:
        raise RuntimeError("approved target handle was recycled")
    if current.app.executable_name.casefold() != target.executable.casefold():
        raise RuntimeError("approved target executable changed")
    if current.app.version != target.executable_version:
        raise RuntimeError("approved target version changed")


@dataclass(frozen=True)
class ActProposal:
    goal: str
    intent_id: str
    plugin_id: str
    output_path: Path
    target: ActTarget
    validated: object
    descriptor: object
    active_index_sha256: str
    catalog_generation: int
    store: object

    @property
    def summary(self) -> str:
        return (
            f"{len(self.validated.ordered_nodes)} low-risk actions will create "
            f"{self.output_path.name} in {self.output_path.parent}."
        )

    @property
    def steps(self) -> tuple[str, ...]:
        return tuple(
            node.operation_id.removeprefix("powerpoint.").replace("_", " ")
            for node in self.validated.ordered_nodes
        )


def prepare_act_goal(
    goal: str,
    *,
    output_path: Path,
    target_hwnd: int | None,
    store=None,
) -> ActProposal:
    """Return one inert, fully validated production proposal."""

    store = store or production_store()
    context = store.load_composition_context()
    match = compile_matcher(context.catalog).classify(goal)
    authorization = authorize_intent(
        context.catalog,
        goal,
        IntentCandidate(
            CandidateSource.DETERMINISTIC,
            match.intent_id,
            match.confidence,
            match.reason,
        ),
    )
    if authorization.authorized is None:
        raise RuntimeError(f"{authorization.status.value}: {authorization.explanation}")
    token = authorization.authorized
    descriptor = context.adapters.get(token.plugin_id)
    if descriptor is None:
        raise RuntimeError("authorized plugin has no signed Act adapter")
    matching = [
        plan for plan in descriptor.plans.values() if plan.intent_id == token.intent_id
    ]
    if len(matching) != 1:
        raise RuntimeError(
            "authorized intent does not map to exactly one signed action plan"
        )
    output = Path(output_path).resolve()
    validated = materialize_action_plan(
        matching[0], {"output_path": str(output)}, descriptor.registry
    )
    packs = [
        pack
        for pack in context.catalog.packs.values()
        if pack.plugin_id == token.plugin_id and token.intent_id in pack.intents
    ]
    if len(packs) != 1:
        raise RuntimeError(
            "authorized intent does not own exactly one application pack"
        )
    selected = resolve_target(
        packs[0],
        live_windows_for(packs[0]),
        target_hwnd=target_hwnd,
        project_root=Path(__file__).resolve().parent.parent,
    )
    target = ActTarget(
        selected.hwnd,
        selected.app.process_id,
        selected.app.executable_name,
        selected.app.version,
    )
    return ActProposal(
        goal,
        token.intent_id,
        token.plugin_id,
        output,
        target,
        validated,
        descriptor,
        context.catalog.index_sha256,
        context.catalog.generation,
        store,
    )


def execute_act_proposal(
    proposal: ActProposal,
    *,
    unattended: bool = False,
    owned_output_root: Path | None = None,
    controls: ActControls | None = None,
    event_sink: Callable[[object], None] | None = None,
):
    """Approve the exact reviewed proposal once, then run its signed plan."""

    descriptor = proposal.descriptor
    approval = approve_action_graph(
        proposal.validated,
        descriptor.registry,
        manifest_sha256=descriptor.manifest_sha256,
        active_index_sha256=proposal.active_index_sha256,
        catalog_generation=proposal.catalog_generation,
        target=proposal.target,
        output_path=proposal.output_path,
        unattended=unattended,
        owned_output_root=owned_output_root,
    )

    def current_authority():
        current = proposal.store.load_composition_context()
        adapter = current.adapters[proposal.plugin_id]
        return (
            current.catalog.index_sha256,
            current.catalog.generation,
            adapter.plugin_version,
            adapter.manifest_sha256,
            adapter.adapter_sha256,
        )

    return execute_approved_graph(
        proposal.validated,
        descriptor.registry,
        approval,
        descriptor=descriptor,
        current_authority=current_authority,
        revalidate_target=_revalidate,
        controls=controls or ActControls(),
        event_sink=event_sink,
    )


def run_act_goal(
    goal: str,
    *,
    output_path: Path,
    target_hwnd: int,
    approved: bool,
    unattended: bool = False,
    owned_output_root: Path | None = None,
) -> int:
    """Classify, authorize, preview, and optionally execute one Act goal."""

    try:
        proposal = prepare_act_goal(
            goal, output_path=output_path, target_hwnd=target_hwnd
        )
    except Exception as exc:
        _emit(
            "refused",
            detail=f"{type(exc).__name__}: {exc}",
        )
        return 2
    _emit(
        "plan",
        graph_sha256=proposal.validated.graph_sha256,
        intent_id=proposal.intent_id,
        nodes=len(proposal.validated.ordered_nodes),
        output_path=str(proposal.output_path),
        plugin_id=proposal.plugin_id,
        target_hwnd=proposal.target.hwnd,
    )
    if not approved:
        _emit(
            "approval_required",
            detail="re-run with --approve after reviewing the complete plan",
        )
        return 4
    result = execute_act_proposal(
        proposal,
        unattended=unattended,
        owned_output_root=owned_output_root,
        event_sink=lambda event: _emit(
            "event",
            event=event.type,
            node_id=event.node_id,
            ordinal=event.ordinal,
            total=event.total,
        ),
    )
    _emit(
        "result",
        code=result.code.value,
        completed=result.completed,
        detail=result.detail,
        output_path=result.output_path,
    )
    return 0 if result.completed else 3


__all__ = [
    "ActProposal",
    "execute_act_proposal",
    "prepare_act_goal",
    "run_act_goal",
]
