"""Production Act planning and execution over enabled signed plugin authority."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
import uuid
from pathlib import Path
from typing import Callable

from ghostcursor.act_runtime import (
    ActRunCode,
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
    #: Where the artifact is DELIVERED. The plan is materialized against the
    #: staging path below, so the adapter is never told this one.
    output_path: Path
    target: ActTarget
    validated: object
    descriptor: object
    active_index_sha256: str
    catalog_generation: int
    store: object
    #: The runtime-owned staging area, when the caller supplied an owned
    #: root. None means this run writes its final path directly, which is
    #: what every production run did before staging existed.
    staging: object = None

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
    owned_output_root: Path | None = None,
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
    # Stage when an owned root is available. The plan is materialized against
    # the STAGING path, so the adapter is never told where the final artifact
    # goes and cannot expose a partial one (D032 review, F1). Without an owned
    # root there is nowhere the runtime owns to stage into, and the run writes
    # its final path directly — as every production run did before staging
    # existed.
    staging = None
    written = output
    if owned_output_root is not None:
        from ghostcursor.act_staging import open_staging

        staging = open_staging(
            output, owned_root=Path(owned_output_root), run_id=uuid.uuid4().hex[:12]
        )
        written = staging.staging
    validated = materialize_action_plan(
        matching[0], {"output_path": str(written)}, descriptor.registry
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
        staging,
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
        # The path the run WRITES. Staged runs write the staging file and the
        # final path comes into existence once, atomically, after everything
        # verified.
        output_path=(
            proposal.staging.staging
            if proposal.staging is not None
            else proposal.output_path
        ),
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

    result = execute_approved_graph(
        proposal.validated,
        descriptor.registry,
        approval,
        descriptor=descriptor,
        current_authority=current_authority,
        revalidate_target=_revalidate,
        controls=controls or ActControls(),
        event_sink=event_sink,
    )
    if proposal.staging is None:
        return result

    from ghostcursor.act_staging import StagingError, abandon, publish

    if not result.completed:
        # Stopped, refused or failed. The staging file stays, labelled, and
        # the final path was never created.
        abandon(proposal.staging)
        return result
    try:
        publish(proposal.staging)
    except StagingError as exc:
        # A run that verified but could not publish is NOT completed. Saying
        # otherwise would report a deck at a path where nothing exists.
        abandon(proposal.staging)
        return replace(
            result,
            code=ActRunCode.ADAPTER_FAILED,
            detail=f"the verified run could not be published: {exc}",
            output_path=str(proposal.staging.staging),
        )
    return replace(result, output_path=str(proposal.output_path))


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
            goal,
            output_path=output_path,
            target_hwnd=target_hwnd,
            owned_output_root=owned_output_root,
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
