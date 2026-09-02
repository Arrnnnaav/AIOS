"""The closed vocabulary Act's session surfaces and verifier speak.

Receipt kinds, refusal codes, verifier modes, lifecycle states and trust
classes are fixed here before any ordered-sequence test is written against
them, because a test that pins a name which later changes proves nothing about
the system that shipped.

Three rules this module exists to make unrepresentable:

**No effect runs from a cue whose presentation was never acknowledged.** The
overlay reports that it painted; the worker waits for that report. A cue that
was requested and never confirmed is a cue the user did not see, and running
the action anyway is the autonomous-agent failure this whole design is built
to avoid.

**A receipt answers exactly one request.** Receipts carry the session, the cue,
the nonce, and the presentation and frame generations they were produced for.
Without that binding a receipt from an earlier cue satisfies a later wait, and
the wait silently becomes decorative -- the same shape of defect as a replayed
authorization.

**A weaker backend never wears a stronger backend's appearance.** Trust class
is derived from the backend that actually acted and the verification that
actually happened. It is never passed in as presentation, because the one
thing a viewer cannot check is whether the colour they are looking at was
earned.

Timing bounds are NOT declared here. `ReceiptPolicy` requires them and has no
defaults, because Phase E derives every budget from measurement and a
plausible-looking constant in this file is exactly the placeholder that
derivation is meant to replace.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class VerifierMode(str, Enum):
    """The three one-shot requests the signed verifier answers.

    Separate modes rather than one call with a flag: each runs in its own
    fresh process, each has its own derived timeout in the signed operation
    policy, and each has a distinct visible state. Collapsing them would make
    one timeout stand for three very different waits.
    """

    OBSERVE_BEFORE = "observe_before"
    CONFIRM_BEFORE = "confirm_before"
    VERIFY_AFTER = "verify_after"


class ReceiptKind(str, Enum):
    """What the overlay reports back about one presentation request."""

    #: First paint completed with trustworthy geometry drawn.
    GEOMETRY_STARTED = "geometry_started"
    #: First paint completed as rail text, with no pointer, ring or arrow.
    RAIL_STARTED = "rail_started"
    #: Geometry was refused -- unusable coordinate contract, or none offered.
    #: Not a failure of the run; production may then request rail presentation.
    RENDER_REJECTED = "render_rejected"
    #: The full settled presentation finished. Only after this may semantic
    #: confirmation begin.
    PRESENTATION_COMPLETED = "presentation_completed"


#: The kinds that mean "a presentation has begun and was seen".
START_RECEIPTS = frozenset({ReceiptKind.GEOMETRY_STARTED, ReceiptKind.RAIL_STARTED})


class RefusalCode(str, Enum):
    """Every way Act stops before or instead of an effect.

    Closed on purpose. A free-text reason would let two different refusals
    look alike in a run record, and these are the records a campaign is
    judged on.
    """

    #: Semantic state changed between observe_before and confirm_before.
    PRECONDITION_DRIFTED = "precondition_drifted"
    #: The confirmation was too old by the time the adapter was asked to act.
    PRECONDITION_STALE = "precondition_stale"
    #: confirm_before did not answer inside its signed timeout.
    PRECONDITION_CONFIRMATION_TIMEOUT = "precondition_confirmation_timeout"
    #: A required presentation receipt never arrived.
    RENDER_TIMEOUT = "render_timeout"
    #: The one-use authorization expired before the pattern call.
    AUTHORIZATION_EXPIRED = "authorization_expired"
    #: The control resolved, but not to the identity that was authorized.
    TARGET_IDENTITY_MISMATCH = "target_identity_mismatch"
    #: The selector matched zero or several controls where one was required.
    TARGET_CARDINALITY_REFUSED = "target_cardinality_refused"
    #: No reviewed backend can drive this control.
    UNSUPPORTED_ACTION_SURFACE = "unsupported_action_surface"
    #: Plugin, catalog, approval or target authority changed mid-run.
    AUTHORITY_CHANGED = "authority_changed"


class LifecycleState(str, Enum):
    """What the session surface shows about one node, in order."""

    PREPARING = "preparing"
    PRESENTING = "presenting"
    CONFIRMING = "confirming"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    REFUSED = "refused"


#: States in which nothing has been proven yet, so none of them may be shown
#: in a backend's verified colour. `VERIFYING` is the one that matters: an
#: action has already taken effect and its result is not yet known, which is
#: precisely when a success colour would be a lie.
UNPROVEN_STATES = frozenset(
    {
        LifecycleState.PREPARING,
        LifecycleState.PRESENTING,
        LifecycleState.CONFIRMING,
        LifecycleState.EXECUTING,
        LifecycleState.VERIFYING,
    }
)


class Backend(str, Enum):
    """What actually performed the effect."""

    OBJECT_MODEL = "object_model"
    UIA_PATTERN = "uia_pattern"
    LEGACY_IACCESSIBLE = "legacy_iaccessible"
    #: Reserved. Nothing in v1 may select it; it exists so the trust class it
    #: would carry is defined before anything can quietly acquire it.
    RAW_INPUT = "raw_input"


class TrustClass(str, Enum):
    """How strongly a completed node was proven, for presentation."""

    #: Verified by reading the saved artifact.
    ARTIFACT = "artifact"
    #: Verified from fresh live UI state after a true UIA pattern.
    LIVE_STATE = "live_state"
    #: Verified from live state after a LegacyIAccessible default action.
    #: Weaker targeting semantics than LIVE_STATE, and never presented as it.
    LEGACY_LIVE_STATE = "legacy_live_state"
    #: Future inferred or raw-input action. Unused in v1.
    INFERRED = "inferred"
    #: Nothing proven yet.
    NEUTRAL = "neutral"
    #: Refused or failed.
    REFUSED = "refused"


#: The one mapping from what acted to what may be claimed. Deliberately not
#: invertible and deliberately not a parameter: a caller that could pass a
#: trust class in could pass a stronger one than it earned.
_VERIFIED_TRUST: Mapping[Backend, TrustClass] = {
    Backend.OBJECT_MODEL: TrustClass.ARTIFACT,
    Backend.UIA_PATTERN: TrustClass.LIVE_STATE,
    Backend.LEGACY_IACCESSIBLE: TrustClass.LEGACY_LIVE_STATE,
    Backend.RAW_INPUT: TrustClass.INFERRED,
}


def trust_for(backend: Backend, state: LifecycleState) -> TrustClass:
    """The only trust class this backend may show in this state.

    A verified colour is earned by two things together -- which backend acted
    and that verification has returned -- so every unproven state collapses to
    NEUTRAL regardless of how strong the backend is.
    """

    if not isinstance(backend, Backend) or not isinstance(state, LifecycleState):
        raise TypeError("trust class needs a known backend and lifecycle state")
    if state is LifecycleState.REFUSED:
        return TrustClass.REFUSED
    if state in UNPROVEN_STATES:
        return TrustClass.NEUTRAL
    return _VERIFIED_TRUST[backend]


class ProtocolError(ValueError):
    """A receipt or presentation sequence that must not be acted on."""


@dataclass(frozen=True)
class Receipt:
    """One acknowledgement, bound to the exact request it answers."""

    kind: ReceiptKind
    session_id: str
    cue_id: str
    nonce: str
    presentation_generation: int
    frame_generation: int


@dataclass(frozen=True)
class ReceiptPolicy:
    """Deadlines for one presentation.

    No defaults. Phase E derives these from measurement, and a plausible
    constant here is the placeholder that derivation exists to replace -- it
    would also be the number every test silently agreed with.
    """

    first_paint_deadline_ms: int
    completion_deadline_ms: int

    def __post_init__(self) -> None:
        if self.first_paint_deadline_ms <= 0 or self.completion_deadline_ms <= 0:
            raise ProtocolError("receipt deadlines must be positive")
        if self.completion_deadline_ms < self.first_paint_deadline_ms:
            raise ProtocolError(
                "the completion deadline must not be shorter than the "
                "first-paint deadline it is measured after"
            )


@dataclass(frozen=True)
class PresentationRequest:
    """What the worker asked the overlay to show, and for which node."""

    session_id: str
    cue_id: str
    nonce: str
    presentation_generation: int
    frame_generation: int
    geometry_required: bool = False


def receipt_answers(request: PresentationRequest, receipt: Receipt) -> bool:
    """Whether this receipt was produced for this exact request.

    Every field is compared. A receipt matching on session and cue but not on
    presentation generation is a receipt for a previous attempt at the same
    cue, and accepting it would let a re-presented cue be satisfied by the
    render that preceded its own re-request.
    """

    return (
        receipt.session_id == request.session_id
        and receipt.cue_id == request.cue_id
        and receipt.nonce == request.nonce
        and receipt.presentation_generation == request.presentation_generation
        and receipt.frame_generation == request.frame_generation
    )


class PresentationWait:
    """Tracks one cue's presentation against its policy, on an injected clock.

    Ordered-sequence rather than end-state (D026): the questions that matter
    are *when* each receipt arrived relative to which deadline, and an
    end-state check cannot tell a completion that arrived late from one that
    arrived at all.
    """

    def __init__(
        self,
        request: PresentationRequest,
        policy: ReceiptPolicy,
        *,
        started_ms: float,
    ) -> None:
        self._request = request
        self._policy = policy
        self._started_ms = started_ms
        self._start_receipt: Receipt | None = None
        self._start_ms: float | None = None
        self._completed = False
        self._rejected = False

    @property
    def rejected(self) -> bool:
        """Geometry was refused. Production may re-present as rail text."""

        return self._rejected

    @property
    def satisfied(self) -> bool:
        """Both required receipts arrived inside their deadlines."""

        return self._start_receipt is not None and self._completed

    @property
    def may_execute(self) -> bool:
        """The single question the worker asks before an effect."""

        return self.satisfied

    def accept(self, receipt: Receipt, *, now_ms: float) -> None:
        """Record one receipt, or refuse the whole presentation."""

        if not receipt_answers(self._request, receipt):
            raise ProtocolError(
                f"receipt for cue {receipt.cue_id!r} generation "
                f"{receipt.presentation_generation} does not answer the "
                f"request for cue {self._request.cue_id!r} generation "
                f"{self._request.presentation_generation}"
            )
        if receipt.kind is ReceiptKind.RENDER_REJECTED:
            if self._request.geometry_required:
                raise ProtocolError(
                    "geometry was required for this presentation and was refused"
                )
            self._rejected = True
            return
        if receipt.kind in START_RECEIPTS:
            if receipt.kind is ReceiptKind.GEOMETRY_STARTED and self._rejected:
                raise ProtocolError(
                    "geometry was already refused for this presentation"
                )
            if self._start_receipt is not None:
                raise ProtocolError("this presentation already started")
            if now_ms - self._started_ms > self._policy.first_paint_deadline_ms:
                raise ProtocolError(RefusalCode.RENDER_TIMEOUT.value)
            self._start_receipt = receipt
            self._start_ms = now_ms
            return
        # PRESENTATION_COMPLETED
        if self._start_receipt is None:
            raise ProtocolError("a presentation cannot complete before it has started")
        if self._completed:
            raise ProtocolError("this presentation already completed")
        assert self._start_ms is not None
        if now_ms - self._start_ms > self._policy.completion_deadline_ms:
            raise ProtocolError(RefusalCode.RENDER_TIMEOUT.value)
        self._completed = True

    def expired(self, *, now_ms: float) -> bool:
        """Whether a deadline has passed with the receipt still missing."""

        if self._start_receipt is None:
            return now_ms - self._started_ms > self._policy.first_paint_deadline_ms
        if not self._completed:
            assert self._start_ms is not None
            return now_ms - self._start_ms > self._policy.completion_deadline_ms
        return False


__all__ = [
    "Backend",
    "LifecycleState",
    "PresentationRequest",
    "PresentationWait",
    "ProtocolError",
    "Receipt",
    "ReceiptKind",
    "ReceiptPolicy",
    "RefusalCode",
    "START_RECEIPTS",
    "TrustClass",
    "UNPROVEN_STATES",
    "VerifierMode",
    "receipt_answers",
    "trust_for",
]
