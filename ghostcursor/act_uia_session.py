"""Assembles the `UiaNodeSession` a control-driving node runs through.

Three separate signed things have to agree for one UIA node, and this is
where they are put together — and only put together. It resolves nothing,
authorizes nothing and verifies nothing; every one of those stays where the
runtime already does it.

- The **verifier** answers what the document currently is. Its reading is the
  node's `semantic`, and it is what `execute_node` compares between
  `observe_before` and `confirm_before` to catch the world changing under the
  cue.
- The **adapter's read-only path** answers where the control is and what its
  identity is. `observe_control` sends no pattern, so this half cannot act.
- The **overlay** shows the cue and returns the receipts that make the effect
  permissible at all.

**Why the semantic comes from the verifier and not from the identity.** The
tempting shortcut is to use the control's own identity as the semantic value:
it is already in hand and it is already stable. But `execute_node` compares
identity separately and in more detail, so a semantic derived from it would
agree exactly whenever the identity check agreed — a drift check that can
never fire, sitting in the run record looking like it had. The verifier reads
something the adapter cannot see, which is the only reason the comparison
means anything.

It costs two extra verifier spawns per node. That is the price of the drift
check being real, and Phase E measures it rather than assuming it is small.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Mapping

from ghostcursor.act_node import Observation
from ghostcursor.act_overlay import OverlaySession
from ghostcursor.act_protocol import ReceiptPolicy, RefusalCode
from ghostcursor.act_runtime import UiaNodeSession
from ghostcursor.adapter_host import AdapterHost, AdapterProtocolError, VerifierHost
from ghostcursor.selectors import SelectorError, load_action_selector
from ghostcursor.uia_identity import compare_identity


class UiaSessionError(RuntimeError):
    """The session could not be assembled or a read failed closed."""

    def __init__(self, detail: str, code: RefusalCode) -> None:
        super().__init__(detail)
        self.detail = detail
        self.code = code


def build_uia_session(
    *,
    host: AdapterHost,
    verifier: VerifierHost,
    payload_root: Path,
    overlay: OverlaySession,
    policy: ReceiptPolicy,
    session_id: str,
    operation_for: Callable[[object], Any],
    target: Mapping[str, Any],
    validation_sha256: str,
    output_path: str | None,
    cancel_event: "threading.Event | None" = None,
    observe_timeout_s: float = 5.0,
    dispatch_timeout_s: float = 10.0,
    verify_timeout_s: float = 10.0,
    clock: Callable[[], float] | None = None,
) -> UiaNodeSession:
    """Compose one run's session. Every argument is already-approved data.

    ``operation_for`` returns the signed `OperationSpec` for a node, so the
    selector and pattern come from the signed registry rather than from
    anything this function was told.

    The digest that travels with a dispatch is taken from the token
    `execute_node` hands to `dispatch` -- the authorization core minted for
    that node -- never from anything this function was given. There is one
    source, so there is nothing to diverge.

    ``cancel_event`` lets a READ be abandoned when the operator stops. It is
    passed to the observation and deliberately not to the dispatch: a read
    can be given up freely, but abandoning a dispatch that has already been
    sent loses the ability to verify an effect that may have landed. A
    dispatch is instead bounded by its own timeout.
    """

    def observe(node, mode: str) -> Observation:
        spec = operation_for(node)
        # Re-resolved on EVERY observation, not cached from the first. The
        # payload is on disk and the selector file could be replaced between
        # the two reads; a cached name would mean the confirmation resolved a
        # control the second read never approved.
        selector = _resolve_selector(payload_root, spec)

        # The document reading first. If the verifier cannot answer, there is
        # no semantic to compare and the node must not proceed on the
        # identity alone -- that is exactly the vacuous drift check this
        # module exists to avoid.
        try:
            # No baseline on an OBSERVATION: there is nothing yet to compare
            # against, and the live verifier answers `refused` with a reading
            # rather than inventing a verdict. `postconditions` is still sent,
            # because its presence is what marks this as a live-state request
            # -- an artifact verifier validates its fields exactly and would
            # refuse a frame carrying either key.
            answer = verifier.verify(
                node=node,
                validation_sha256=validation_sha256,
                output_path=output_path,
                target=target,
                timeout_s=verify_timeout_s,
                cancel_event=cancel_event,
                baseline=None,
                postconditions=spec.postconditions,
            )
        except AdapterProtocolError as exc:
            raise UiaSessionError(
                f"the read-only verifier could not answer for {mode}: {exc}",
                RefusalCode.PRECONDITION_DRIFTED,
            ) from None

        # A verifier that CANNOT READ reports it the normal way: exit 0,
        # `outcome="refused"`, `observed={}`. `VerifierHost.verify` accepts
        # that without raising, because "refused" is a legitimate answer.
        #
        # So a failed reading used to become an empty semantic -- and two
        # empty semantics compare EQUAL, which meant `execute_node`'s drift
        # check passed on two consecutive failures and the node dispatched.
        # The test that claimed to cover this used a fake that RAISED, which
        # is not how the real verifier reports a failed read: it enforced an
        # invariant that correlated with the property instead of implying it
        # (D031). Found by the D032 review of 4 September 2026.
        if not answer.observed:
            raise UiaSessionError(
                f"the read-only verifier returned no reading for {mode}: "
                f"{answer.detail}",
                RefusalCode.PRECONDITION_DRIFTED,
            )

        try:
            seen = host.observe_control(
                selector.control_type,
                selector.name,
                timeout_s=observe_timeout_s,
                cancel_event=cancel_event,
            )
        except AdapterProtocolError as exc:
            raise UiaSessionError(
                f"the control could not be read for {mode}: {exc}",
                RefusalCode.TARGET_IDENTITY_MISMATCH,
            ) from None

        return Observation(
            semantic=answer.observed,
            identity=seen.identity,
            rectangle=seen.rectangle,
            geometry=seen.geometry,
            match_count=1,
        )

    def dispatch(node, token, confirmed: Observation | None) -> None:
        spec = operation_for(node)
        if token is None or not getattr(token, "authorization_sha256", ""):
            # The authorization core minted for THIS node, or nothing. An
            # earlier version ignored the token and sent a digest computed by
            # a separate callable the caller supplied. Nothing made the two
            # agree, so the adapter could be handed an authorization core had
            # never minted -- and the only caller was a diagnostic that
            # stubbed the token, so the divergence could not show up until
            # production wired this in.
            raise UiaSessionError(
                "a control-driving dispatch needs the authorization core "
                "minted for this node",
                RefusalCode.TARGET_IDENTITY_MISMATCH,
            )
        if confirmed is None:
            # Unreachable through `execute_node` for a pointer-drawing node,
            # and refused rather than asserted: reaching here would mean
            # dispatching at a control nobody confirmed was still the one
            # under the pointer.
            raise UiaSessionError(
                "a control-driving dispatch needs a confirmed observation",
                RefusalCode.TARGET_IDENTITY_MISMATCH,
            )
        selector = _resolve_selector(payload_root, spec)
        if (
            confirmed.identity is None
            or confirmed.rectangle is None
            or confirmed.geometry is None
        ):
            raise UiaSessionError(
                "dispatch requires confirmed identity and bracketed geometry",
                RefusalCode.TARGET_IDENTITY_MISMATCH,
            )
        reasons = compare_identity(
            spec.identity, confirmed.identity, confirmed.identity,
            match_count=confirmed.match_count,
        )
        if reasons:
            raise UiaSessionError("; ".join(reasons), RefusalCode.TARGET_IDENTITY_MISMATCH)
        response = host.dispatch_pattern(
            selector.control_type,
            selector.name,
            spec.uia_pattern,
            authorization_sha256=token.authorization_sha256,
            expected_identity={field: confirmed.identity[field]
                               for field in spec.identity.required_fields},
            expected_rectangle=confirmed.rectangle,
            expected_geometry=confirmed.geometry,
            timeout_s=dispatch_timeout_s,
        )
        if response.outcome != "completed":
            raise UiaSessionError(
                f"the adapter did not complete the dispatch: {response.detail}",
                RefusalCode.UNSUPPORTED_ACTION_SURFACE,
            )

    session = UiaNodeSession(
        observe=observe,
        present=overlay.present,
        dispatch=dispatch,
        policy=policy,
        session_id=session_id,
        on_state=overlay.on_node_state,
    )
    if clock is not None:
        session.clock = clock
    return session


def _resolve_selector(payload_root: Path, spec):
    """The control the signed selector names, digest-checked.

    Read through `load_action_selector` rather than off the spec, because the
    spec carries only a selector ID and a digest -- the NAME lives in a
    separate signed file, and loading it is the only path that proves the
    name is the reviewed one. A name obtained any other way would mean the
    thing choosing what gets clicked was not the signed plugin.
    """

    policy = spec.identity
    if policy is None:
        raise UiaSessionError(
            f"operation {spec.operation_id!r} declares no identity policy",
            RefusalCode.TARGET_IDENTITY_MISMATCH,
        )
    try:
        return load_action_selector(
            payload_root,
            policy.selector_id,
            policy.selector_sha256,
            control_type=policy.control_type,
        )
    except SelectorError as exc:
        raise UiaSessionError(str(exc), RefusalCode.TARGET_IDENTITY_MISMATCH) from None


def _canonical(observed: Mapping[str, Any]) -> Any:
    """A comparable form of the verifier's reading.

    `execute_node` compares this with `!=` across two separate reads, so an
    unordered container would drift on its own and report the world changing
    when nothing had.
    """

    if isinstance(observed, Mapping):
        return tuple(
            sorted((key, _canonical(value)) for key, value in observed.items())
        )
    if isinstance(observed, (list, tuple)):
        return tuple(_canonical(item) for item in observed)
    if isinstance(observed, set):
        return tuple(sorted(_canonical(item) for item in observed))
    return observed


__all__ = ["UiaSessionError", "build_uia_session"]
