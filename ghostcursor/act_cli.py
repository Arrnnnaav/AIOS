"""Production Act planning and execution over enabled signed plugin authority."""

from __future__ import annotations

import json
from contextlib import contextmanager
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
    presentation=None,
):
    """Approve the exact reviewed proposal once, then run its signed plan.

    ``presentation`` is where a control-driving node's cue is drawn. It is
    passed through untouched: this function decides nothing about how a cue
    looks and cannot dispatch through it. A plan whose signed operations are
    all object-model needs none, and `run_act_goal` does not create one --
    see `plan_draws_a_pointer`.
    """

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
        presentation=presentation,
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
    sink = lambda event: _emit(  # noqa: E731 - one expression, used twice
        "event",
        event=event.type,
        node_id=event.node_id,
        ordinal=event.ordinal,
        total=event.total,
    )
    # A surface is created only for a plan whose SIGNED operations include a
    # control-driving one. An object-model plan gets none, and the runtime
    # then refuses any pointer-drawing node by construction rather than by
    # this function having remembered to check.
    if not plan_draws_a_pointer(proposal):
        result = execute_act_proposal(
            proposal,
            unattended=unattended,
            owned_output_root=owned_output_root,
            event_sink=sink,
        )
    else:
        with _pointer_surface() as presentation:
            result = execute_act_proposal(
                proposal,
                unattended=unattended,
                owned_output_root=owned_output_root,
                event_sink=sink,
                presentation=presentation,
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
    "plan_draws_a_pointer",
    "prepare_act_goal",
    "run_act_goal",
]


def plan_draws_a_pointer(proposal: ActProposal) -> bool:
    """Whether any node in this approved plan may show a pointer (D109).

    Asked from the SIGNED registry, never from a flag a caller passed. It is
    what decides whether a run needs a presentation surface at all, and an
    object-model plan must not get one: a window nothing draws in is still a
    window, and creating it would suggest a pointer path exists where the
    backend has no control to hold.
    """

    operations = proposal.descriptor.registry.operations
    return any(
        operations[node.operation_id].draws_a_pointer
        for node in proposal.validated.ordered_nodes
    )


@contextmanager
def _pointer_surface():
    """A real overlay window for the length of one run, then destroyed.

    Imported lazily and created only on the pointer path. `act_cli` is
    imported by hermetic tests that have no desktop, and a Win32 window at
    module import would make the whole production planning path require one.

    The window is destroyed in a `finally`, including when the run raises:
    a leaked topmost click-through window covering the screen is exactly the
    failure the ESC and timeout rules in `run.py` exist to prevent.
    """

    from ghostcursor.act_overlay import CueBudget, overlay_presenter
    from ghostcursor.act_protocol import ReceiptPolicy, TrustClass
    from ghostcursor.act_runtime import PresentationSurface
    from ghostcursor.overlay import window as overlay_window

    hwnd = overlay_window.create_overlay_window()
    try:
        policy = ReceiptPolicy(
            first_paint_deadline_ms=2000, completion_deadline_ms=8000
        )
        overlay = overlay_presenter(
            hwnd,
            budget=CueBudget(),
            policy=policy,
            # The label names what the observation actually found. A fixed
            # string here would let the cue describe a control the run did
            # not resolve.
            label_for=lambda observation: str(
                dict(getattr(observation, "identity", {}) or {}).get("name", "")
            ),
            # What a UIA node earns ONCE VERIFIED. The cue itself is always
            # drawn NEUTRAL while presenting, however strong the backend
            # (D109, amended by D112).
            backend_trust=TrustClass.LIVE_STATE,
            keep_running=lambda: True,
        )
        yield PresentationSurface(overlay=overlay, policy=policy)
    finally:
        overlay_window.destroy_overlay_window(hwnd)
