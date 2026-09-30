"""One node's journey from authorized to verified, with the user watching.

This is the first caller of `act_protocol` and `uia_identity` together.
Until it existed those contracts had only ever been judged against their own
docstrings (D107).

Every presentation rectangle carries the producer's bracketed coordinate
contract.  The overlay independently samples its own process/thread/window
space before drawing; the geometry remains presentation-only and never
becomes authorization or learned identity.

The order is fixed and the reasons are separate:

    observe_before      what the world looked like before we showed anything
    present + receipts  the user is shown where this will happen, and the
                        overlay confirms it painted
    confirm_before      what the world looks like NOW, after the cue elapsed
    authorize           a one-use token bound to both observations
    dispatch            the effect, at the point the pointer is sitting on
    verify_after        an independent process reads the result

`confirm_before` exists because the cue takes real time -- deliberately, so a
person can follow it (D109) -- and the user can act during it. Comparing the
post-action state against an observation taken before that gap would let their
change be reported as ours.

**Object-model nodes take a shorter path.** They drive an application API, so
there is no control to resolve, no identity to hold, and nothing to point at.
They present a rail label, dispatch, and verify from the saved artifact. A
pointer is never drawn for them, and this module cannot be configured to draw
one: it asks the signed operation, and `draws_a_pointer` is False for every
object-model operation by construction.

Every collaborator is injected. That is not test scaffolding -- it is how the
authority boundary stays visible: this module sequences, and owns none of the
authority it sequences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Callable, Mapping, Sequence

from ghostcursor.action import _freeze, _plain

from ghostcursor.act_protocol import (
    Backend,
    LifecycleState,
    PresentationRequest,
    PresentationWait,
    ProtocolError,
    Receipt,
    ReceiptPolicy,
    RefusalCode,
    TrustClass,
    trust_for,
)
from ghostcursor.coordinate_space import BracketedGeometry, bracket_disagreements
from ghostcursor.uia_identity import compare_identity, identity_evidence


class NodeRefused(RuntimeError):
    """A node that must not proceed, carrying why."""

    def __init__(self, code: RefusalCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Observation:
    """One read of the world by the signed read-only verifier."""

    #: Whatever the operation's postcondition is computed from. Compared for
    #: equality between observe_before and confirm_before, so it must be
    #: canonical -- a set rendered as an unordered list would drift on its own.
    semantic: Any
    #: The control's identity at that instant. None for an object-model node.
    identity: Mapping[str, Any] | None = None
    #: Presentation-only, never authority (D106/D109).
    rectangle: tuple[int, int, int, int] | None = None
    #: Cross-process provenance for ``rectangle``. Ephemeral and deliberately
    #: absent from semantic/identity digests and run persistence.
    geometry: BracketedGeometry | None = None
    match_count: int = 1

    def __post_init__(self) -> None:
        # Copy recursively at the observation boundary, not after the cue:
        # providers may reuse their dictionaries for the next read.
        object.__setattr__(self, "semantic", _freeze(_plain(self.semantic)))
        if self.identity is not None:
            object.__setattr__(self, "identity", _freeze(_plain(self.identity)))

    @property
    def semantic_sha256(self) -> str:
        return hashlib.sha256(json.dumps(
            _plain(self.semantic), sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()


@dataclass(frozen=True)
class NodeOutcome:
    node_id: str
    verified: bool
    trust: TrustClass
    detail: str
    refusal: RefusalCode | None = None
    identity_record: Mapping[str, Any] | None = None
    states: tuple[LifecycleState, ...] = field(default_factory=tuple)


_BACKEND_BY_NAME = {
    "object_model": Backend.OBJECT_MODEL,
    "uia_pattern": Backend.UIA_PATTERN,
    "legacy_iaccessible": Backend.LEGACY_IACCESSIBLE,
}


def execute_node(
    node,
    spec,
    *,
    request: PresentationRequest,
    policy: ReceiptPolicy,
    observe: Callable[[str], Observation],
    present: Callable[
        [
            PresentationRequest,
            "Observation | None",
            Callable[[Receipt, float], None],
        ],
        Sequence[Receipt],
    ],
    authorize: Callable[[Mapping[str, Any]], Any],
    dispatch: Callable[[Any, Observation | None, float | None], Any],
    verify: Callable[[Any, Observation | None], bool],
    clock: Callable[[], float],
    on_state: Callable[[LifecycleState], None] | None = None,
    should_continue: Callable[[], bool] | None = None,
    dispatch_permitted: Callable[[], bool] | None = None,
) -> NodeOutcome:
    """Run one authorized node, refusing rather than guessing at every gap.

    ``should_continue`` is the operator's Stop/Pause checkpoint, asked at the
    two phase
    boundaries where stopping is still free: before the confirmation, and
    before the dispatch. It can only ever REDUCE what happens -- there is no
    answer it can give that makes a node succeed -- which is why it is safe
    to accept a callable here at all.

    It is deliberately NOT asked after the dispatch. Once an effect has been
    issued, verification must run: skipping it because someone pressed Stop
    would leave an effect that happened and was never checked, which is a
    worse outcome than a stop that arrives a second late.

    Without it, a Stop landing after the cue completed was not noticed until
    the node ended -- confirmation, authorization, dispatch and verification
    all ran -- which for a UIA node is an unresponsive window measured in
    seconds against D020's half-second ceiling.

    ``dispatch_permitted`` is a final, non-blocking read after authorization
    and immediately before the adapter receives the token. A Pause arriving
    while authority is being revalidated must not let the already-confirmed
    action start invisibly; it refuses this node and requires a fresh run
    instead of waiting with a stale confirmation.
    """

    def stopped_here(phase: str) -> None:
        if should_continue is not None and not should_continue():
            raise NodeRefused(
                RefusalCode.OPERATOR_STOPPED,
                f"the operator stopped the run before {phase}",
            )

    backend = _BACKEND_BY_NAME.get(spec.backend)
    if backend is None:
        raise NodeRefused(
            RefusalCode.UNSUPPORTED_ACTION_SURFACE,
            f"operation backend {spec.backend!r} is unknown",
        )
    if spec.backend == "uia_pattern" and any(
        getattr(spec, name, None) is None
        for name in (
            "confirmation_round_trip_deadline_ms",
            "confirmation_to_request_deadline_ms",
        )
    ):
        raise NodeRefused(
            RefusalCode.PRECONDITION_CONFIRMATION_TIMEOUT,
            "a UIA operation has no complete signed timing policy",
        )
    states: list[LifecycleState] = []

    def enter(state: LifecycleState) -> None:
        states.append(state)
        if on_state is not None:
            on_state(state)

    def outcome(
        verified: bool, detail: str, *, refusal=None, identity_record=None
    ) -> NodeOutcome:
        state = LifecycleState.VERIFIED if verified else LifecycleState.REFUSED
        enter(state)
        return NodeOutcome(
            node_id=node.node_id,
            verified=verified,
            trust=trust_for(backend, state),
            detail=detail,
            refusal=refusal,
            identity_record=identity_record,
            states=tuple(states),
        )

    # --- observe -----------------------------------------------------------
    enter(LifecycleState.PREPARING)
    baseline = observe("observe_before") if spec.draws_a_pointer else None
    if baseline is not None and baseline.identity is None:
        raise NodeRefused(
            RefusalCode.TARGET_IDENTITY_MISMATCH,
            "the baseline observation carries no target identity",
        )

    # --- present, and require the receipts ---------------------------------
    enter(LifecycleState.PRESENTING)
    if request.geometry_required and not spec.draws_a_pointer:
        # D109 from the other direction: a node that cannot point at anything
        # must not be asked to prove geometry it will never have.
        raise NodeRefused(
            RefusalCode.UNSUPPORTED_ACTION_SURFACE,
            "an object-model node cannot satisfy a geometry-required cue",
        )
    wait = PresentationWait(request, policy, started_ms=clock())
    try:
        # The wait is fed AS EACH RECEIPT HAPPENS, not from the returned
        # sequence. `present` only returns once the whole presentation is
        # over, so timestamping its results afterwards judged a first paint
        # that arrived promptly against the moment the settle ended -- a
        # 900ms dwell passed a 2000ms first-paint deadline and a 4000ms dwell
        # did not, though both painted immediately. The deadlines existed and
        # measured the wrong interval.
        present(request, baseline, lambda receipt, at_ms: wait.accept(receipt, now_ms=at_ms))
    except ProtocolError as exc:
        raise NodeRefused(exc.code or RefusalCode.RENDER_TIMEOUT, str(exc)) from None
    if not wait.may_execute:
        raise NodeRefused(
            RefusalCode.RENDER_TIMEOUT,
            "the presentation for this node was never acknowledged",
        )

    # --- confirm -----------------------------------------------------------
    identity_record = None
    confirmed = None
    confirmation_completed_at = None
    if spec.draws_a_pointer:
        stopped_here("the confirmation")
        enter(LifecycleState.CONFIRMING)
        confirmed = observe("confirm_before")
        confirmation_completed_at = clock()
        if confirmed.semantic != baseline.semantic:
            raise NodeRefused(
                RefusalCode.PRECONDITION_DRIFTED,
                "the world changed between observing this node and acting on it",
            )
        if confirmed.identity is None:
            raise NodeRefused(
                RefusalCode.TARGET_IDENTITY_MISMATCH,
                "the confirmation carries no target identity",
            )
        reasons = compare_identity(
            spec.identity,
            baseline.identity,
            confirmed.identity,
            match_count=confirmed.match_count,
        )
        if reasons:
            raise NodeRefused(RefusalCode.TARGET_IDENTITY_MISMATCH, "; ".join(reasons))
        if confirmed.rectangle != baseline.rectangle:
            raise NodeRefused(
                RefusalCode.TARGET_IDENTITY_MISMATCH,
                "the confirmed target moved away from the displayed cue",
            )
        if baseline.geometry is None or confirmed.geometry is None:
            raise NodeRefused(
                RefusalCode.TARGET_IDENTITY_MISMATCH,
                "the displayed and confirmed targets need coordinate provenance",
            )
        geometry_reasons = (
            bracket_disagreements(baseline.geometry.before, baseline.geometry)
            + bracket_disagreements(baseline.geometry.before, confirmed.geometry)
        )
        if geometry_reasons:
            raise NodeRefused(
                RefusalCode.TARGET_IDENTITY_MISMATCH,
                "the target coordinate space changed after the cue: "
                + "; ".join(dict.fromkeys(geometry_reasons)),
            )
        identity_record = identity_evidence(spec.identity, confirmed.identity)

    # --- authorize and dispatch -------------------------------------------
    # The last point at which stopping costs nothing. After this line an
    # effect may exist, and the run owes it a verification.
    stopped_here("the dispatch")
    enter(LifecycleState.EXECUTING)
    token = authorize(
        {
            "backend": spec.backend,
            "identity": identity_record,
            "node_id": node.node_id,
            "operation_id": node.operation_id,
            "baseline_sha256": baseline.semantic_sha256 if baseline else None,
            "confirmation_sha256": confirmed.semantic_sha256 if confirmed else None,
        }
    )
    request_deadline_ms = getattr(
        spec, "confirmation_to_request_deadline_ms", None
    )
    if request_deadline_ms is not None and confirmation_completed_at is None:
        raise NodeRefused(
            RefusalCode.PRECONDITION_STALE,
            "the signed dispatch window has no confirmation instant to start from",
        )
    if confirmation_completed_at is not None and request_deadline_ms is not None:
        if clock() - confirmation_completed_at > request_deadline_ms:
            raise NodeRefused(
                RefusalCode.PRECONDITION_STALE,
                "the confirmed target became stale before dispatch",
            )
    if dispatch_permitted is not None and not dispatch_permitted():
        raise NodeRefused(
            RefusalCode.OPERATOR_STOPPED,
            "the operator paused or stopped the run after authorization "
            "and before dispatch",
        )
    if confirmation_completed_at is not None and request_deadline_ms is not None:
        if clock() - confirmation_completed_at > request_deadline_ms:
            raise NodeRefused(
                RefusalCode.PRECONDITION_STALE,
                "the confirmed target became stale before dispatch",
            )
    dispatch(token, confirmed, confirmation_completed_at)

    # --- verify ------------------------------------------------------------
    enter(LifecycleState.VERIFYING)
    if verify(node, baseline):
        return outcome(
            True,
            "the declared postcondition was independently observed",
            identity_record=identity_record,
        )
    return outcome(
        False,
        "the declared postcondition was not observed",
        refusal=RefusalCode.UNSUPPORTED_ACTION_SURFACE,
        identity_record=identity_record,
    )


__all__ = ["NodeOutcome", "NodeRefused", "Observation", "execute_node"]
