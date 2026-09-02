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
    if state is not LifecycleState.VERIFIED:
        # Explicit rather than a fall-through. Without this a lifecycle state
        # added later -- CANCELLED, say -- would inherit the backend's
        # VERIFIED colour by default. A new Backend already fails closed with
        # a KeyError; a new state has to fail closed too, or the one thing a
        # viewer cannot check is the one thing that degrades silently.
        raise ProtocolError(
            f"lifecycle state {state.value!r} has no defined trust class",
            RefusalCode.UNSUPPORTED_ACTION_SURFACE,
        )
    return _VERIFIED_TRUST[backend]


class ProtocolError(ValueError):
    """A receipt or presentation sequence that must not be acted on.

    Carries the machine-readable `RefusalCode` as well as the message. An
    earlier version carried only a string, which meant a caller could only
    tell a render timeout from an ordering error by matching prose -- and the
    tests did exactly that, making the message text load-bearing. Structuring
    it before any caller exists is far cheaper than retrofitting it after.
    """

    def __init__(self, message: str, code: "RefusalCode | None" = None) -> None:
        super().__init__(message)
        self.code = code


def _finite(value: object, label: str) -> float:
    """A real, finite clock reading.

    NaN is the reason this exists: `NaN < x` and `NaN > x` are both False, so
    a NaN timestamp passes every deadline comparison in this module and
    reaches `may_execute` with no deadline enforced at all. bool is excluded
    for the same reason generations exclude it -- `True == 1` is a timestamp
    nobody meant.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"{label} must be a real number")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ProtocolError(f"{label} must be finite")
    return number


@dataclass(frozen=True)
class Receipt:
    """One acknowledgement, bound to the exact request it answers."""

    kind: ReceiptKind
    session_id: str
    cue_id: str
    nonce: str
    presentation_generation: int
    frame_generation: int

    def __post_init__(self) -> None:
        # The vocabulary is closed, and it has to be closed at RUNTIME: a
        # plain string kind matches none of the branches below and would fall
        # through to the completion branch, satisfying a wait.
        if not isinstance(self.kind, ReceiptKind):
            raise ProtocolError(f"receipt kind {self.kind!r} is not a known kind")
        _identity(self.session_id, "session_id")
        _identity(self.cue_id, "cue_id")
        _identity(self.nonce, "nonce")
        _generation(self.presentation_generation, "presentation_generation")
        _generation(self.frame_generation, "frame_generation")


def _identity(value: object, label: str) -> str:
    """A non-empty identity. An empty one matches another empty one."""

    if not isinstance(value, str) or not value:
        raise ProtocolError(f"{label} must be a non-empty string")
    return value


def _generation(value: object, label: str) -> int:
    """A non-negative integer, and not a bool.

    `True == 1`, so a boolean generation compares equal to the first real
    generation -- the binding that stops a replayed receipt would then be
    satisfied by a type confusion.
    """

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProtocolError(f"{label} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class ReceiptPolicy:
    """Deadlines for one presentation.

    No defaults. Phase E derives these from measurement, and a plausible
    constant here is the placeholder that derivation exists to replace -- it
    would also be the number every test silently agreed with.

    The two deadlines are independent and deliberately unordered relative to
    each other. `first_paint_deadline_ms` runs from the request;
    `completion_deadline_ms` runs from the START RECEIPT, not from the
    first-paint deadline. An earlier version refused a completion deadline
    shorter than the first-paint one on the stated grounds that it was
    "measured after" it, which is not what the code does -- and that made a
    legitimate budget (slow first paint, fast settle) unrepresentable.
    """

    first_paint_deadline_ms: int
    completion_deadline_ms: int

    def __post_init__(self) -> None:
        for label in ("first_paint_deadline_ms", "completion_deadline_ms"):
            value = getattr(self, label)
            # bool is an int subclass, so ReceiptPolicy(True, True) built a
            # policy with one-millisecond deadlines that timed out everything.
            if isinstance(value, bool) or not isinstance(value, int):
                raise ProtocolError(f"{label} must be an integer")
            if value <= 0:
                raise ProtocolError(f"{label} must be positive")


@dataclass(frozen=True)
class PresentationRequest:
    """What the worker asked the overlay to show, and for which node."""

    session_id: str
    cue_id: str
    nonce: str
    presentation_generation: int
    frame_generation: int
    geometry_required: bool = False

    def __post_init__(self) -> None:
        _identity(self.session_id, "session_id")
        _identity(self.cue_id, "cue_id")
        _identity(self.nonce, "nonce")
        _generation(self.presentation_generation, "presentation_generation")
        _generation(self.frame_generation, "frame_generation")
        if not isinstance(self.geometry_required, bool):
            raise ProtocolError("geometry_required must be a boolean")


def fallback_request_for(
    rejected: PresentationRequest, *, nonce: str
) -> PresentationRequest:
    """A rail presentation to replace one whose geometry was refused.

    A `PresentationWait` is terminal after a rejection, but it cannot enforce
    that the REPLACEMENT is new -- it never sees the other request. Built by
    hand with the same identity, the fallback is satisfiable by receipts
    minted for the request it replaced. This mints the new generation and
    nonce so the binding actually distinguishes them, and drops
    `geometry_required`, since a fallback exists precisely because geometry
    was unavailable.
    """

    if not isinstance(rejected, PresentationRequest):
        raise ProtocolError("a fallback replaces a PresentationRequest")
    return PresentationRequest(
        session_id=rejected.session_id,
        cue_id=rejected.cue_id,
        nonce=_identity(nonce, "nonce"),
        presentation_generation=rejected.presentation_generation + 1,
        frame_generation=rejected.frame_generation + 1,
        geometry_required=False,
    )


def receipt_answers(request: PresentationRequest, receipt: Receipt) -> bool:
    """Whether this receipt was produced for this exact request.

    Every binding field is compared -- `kind` is not one, since a request does
    not say which kind will answer it. A receipt matching on session and cue
    but not on presentation generation is a receipt for a previous attempt at
    the same cue, and accepting it would let a re-presented cue be satisfied
    by the render that preceded its own re-request.
    """

    if not isinstance(request, PresentationRequest) or not isinstance(
        receipt, Receipt
    ):
        raise ProtocolError("receipt_answers compares a request with a receipt")
    return (
        receipt.session_id == request.session_id
        and receipt.cue_id == request.cue_id
        and receipt.nonce == request.nonce
        and receipt.presentation_generation == request.presentation_generation
        and receipt.frame_generation == request.frame_generation
    )


class PresentationWait:
    """Tracks one cue's presentation against its policy, on an injected clock.

    Ordered-sequence rather than end-state (D026): what matters is *when* each
    receipt arrived relative to which deadline.

    **The clock only moves forward.** The wait keeps a high-water mark of
    every `now_ms` it has been shown, including the ones passed to
    `expired()`, and refuses any reading below it. Without that, a caller
    could ask `expired()` at 9999, be told the deadline had passed, then
    submit a receipt at 400 and reach `may_execute` -- the exact outcome this
    module exists to prevent, reachable through an ordinary polling loop.
    """

    def __init__(
        self,
        request: PresentationRequest,
        policy: ReceiptPolicy,
        *,
        started_ms: float,
    ) -> None:
        if not isinstance(request, PresentationRequest):
            raise ProtocolError("a presentation wait needs a PresentationRequest")
        if not isinstance(policy, ReceiptPolicy):
            raise ProtocolError("a presentation wait needs a ReceiptPolicy")
        self._request = request
        self._policy = policy
        self._started_ms = _finite(started_ms, "started_ms")
        self._last_ms = self._started_ms
        self._start_receipt: Receipt | None = None
        self._start_ms: float | None = None
        self._completed = False
        self._rejected = False

    @property
    def rejected(self) -> bool:
        """Geometry was refused. A rail fallback needs a fresh request."""

        return self._rejected

    @property
    def satisfied(self) -> bool:
        """Both required receipts arrived, each inside its own deadline.

        Guaranteed by `accept()`, which is the only path to either flag and
        refuses a late or backwards reading.
        """

        return self._start_receipt is not None and self._completed

    @property
    def may_execute(self) -> bool:
        """The single question the worker asks before an effect."""

        return self.satisfied

    def _observe(self, now_ms: object, label: str) -> float:
        moment = _finite(now_ms, label)
        if moment < self._last_ms:
            raise ProtocolError(
                "the presentation clock moved backwards", RefusalCode.RENDER_TIMEOUT
            )
        self._last_ms = moment
        return moment

    def _deadline_passed(self, moment: float) -> bool:
        """One predicate, shared by `accept()` and `expired()`.

        They used to compute this separately and could disagree about the same
        instant -- one reporting a timeout while the other still accepted.
        """

        if self._rejected or self.satisfied:
            return False
        if self._start_receipt is None:
            return moment - self._started_ms > self._policy.first_paint_deadline_ms
        assert self._start_ms is not None
        return moment - self._start_ms > self._policy.completion_deadline_ms

    def accept(self, receipt: Receipt, *, now_ms: float) -> None:
        """Record one receipt, or refuse the whole presentation."""

        if not isinstance(receipt, Receipt):
            raise ProtocolError("only a Receipt may be accepted")
        moment = self._observe(now_ms, "now_ms")
        if self._rejected:
            # A rejected presentation is TERMINAL. Rail fallback is a new
            # request with its own generation; letting this one continue would
            # mean the fallback was never bound to anything.
            raise ProtocolError(
                "this presentation was refused; rail fallback needs a new request",
                RefusalCode.RENDER_TIMEOUT,
            )
        if not receipt_answers(self._request, receipt):
            raise ProtocolError(
                f"receipt for cue {receipt.cue_id!r} generation "
                f"{receipt.presentation_generation} does not answer the request "
                f"for cue {self._request.cue_id!r} generation "
                f"{self._request.presentation_generation}"
            )
        if self._deadline_passed(moment):
            raise ProtocolError(
                RefusalCode.RENDER_TIMEOUT.value, RefusalCode.RENDER_TIMEOUT
            )

        if receipt.kind is ReceiptKind.RENDER_REJECTED:
            if self._start_receipt is not None or self._completed:
                raise ProtocolError(
                    "geometry cannot be refused after this presentation started"
                )
            if self._request.geometry_required:
                raise ProtocolError(
                    "geometry was required for this presentation and was refused"
                )
            self._rejected = True
            return

        if receipt.kind in START_RECEIPTS:
            if (
                self._request.geometry_required
                and receipt.kind is not ReceiptKind.GEOMETRY_STARTED
            ):
                # Checking only RENDER_REJECTED let a geometry_required cue be
                # satisfied by rail text: the acceptance case would pass while
                # proving none of the geometry it exists to prove.
                raise ProtocolError(
                    "geometry was required for this presentation but it "
                    f"started as {receipt.kind.value}"
                )
            if self._start_receipt is not None:
                raise ProtocolError("this presentation already started")
            self._start_receipt = receipt
            self._start_ms = moment
            return

        if receipt.kind is not ReceiptKind.PRESENTATION_COMPLETED:
            # Unreachable while ReceiptKind stays closed and Receipt validates
            # its kind. Kept because the cost of being wrong about that is an
            # unknown kind falling into the completion branch.
            raise ProtocolError(f"receipt kind {receipt.kind!r} is not handled")
        if self._start_receipt is None:
            raise ProtocolError("a presentation cannot complete before it has started")
        if self._completed:
            raise ProtocolError("this presentation already completed")
        self._completed = True

    def expired(self, *, now_ms: float) -> bool:
        """Whether a deadline has passed with a required receipt still missing.

        Shares `_deadline_passed` with `accept()`, and advances the same
        high-water mark -- asking the question is observing the clock, and a
        caller must not be able to learn the deadline passed and then submit
        against an earlier reading.

        A refused presentation is not expired: it ended, and reporting a
        render timeout for a clean rejection would put the wrong refusal code
        in the run record.
        """

        return self._deadline_passed(self._observe(now_ms, "now_ms"))


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
    "fallback_request_for",
    "receipt_answers",
    "trust_for",
]
