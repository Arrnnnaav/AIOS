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

from pathlib import Path
from typing import Any, Callable, Mapping

from ghostcursor.act_node import Observation
from ghostcursor.act_overlay import OverlaySession
from ghostcursor.act_protocol import ReceiptPolicy, RefusalCode
from ghostcursor.act_runtime import UiaNodeSession
from ghostcursor.adapter_host import AdapterHost, AdapterProtocolError, VerifierHost
from ghostcursor.selectors import SelectorError, load_action_selector


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
    output_path: str,
    authorization_for: Callable[[object], str],
    observe_timeout_s: float = 5.0,
    dispatch_timeout_s: float = 10.0,
    verify_timeout_s: float = 10.0,
    clock: Callable[[], float] | None = None,
) -> UiaNodeSession:
    """Compose one run's session. Every argument is already-approved data.

    ``operation_for`` returns the signed `OperationSpec` for a node, so the
    selector and pattern come from the signed registry rather than from
    anything this function was told.

    ``authorization_for`` returns the digest that must travel with the
    dispatch. It is a callable rather than a value because a digest is minted
    per node, and one reused across nodes would be an authorization for
    something else.
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
            answer = verifier.verify(
                node=node,
                validation_sha256=validation_sha256,
                output_path=output_path,
                target=target,
                timeout_s=verify_timeout_s,
            )
        except AdapterProtocolError as exc:
            raise UiaSessionError(
                f"the read-only verifier could not answer for {mode}: {exc}",
                RefusalCode.PRECONDITION_DRIFTED,
            ) from None

        try:
            seen = host.observe_control(
                selector.control_type,
                selector.name,
                timeout_s=observe_timeout_s,
            )
        except AdapterProtocolError as exc:
            raise UiaSessionError(
                f"the control could not be read for {mode}: {exc}",
                RefusalCode.TARGET_IDENTITY_MISMATCH,
            ) from None

        return Observation(
            semantic=_canonical(answer.observed),
            identity=seen.identity,
            rectangle=seen.rectangle,
            match_count=1,
        )

    def dispatch(node, _token, confirmed: Observation | None) -> None:
        spec = operation_for(node)
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
        response = host.dispatch_pattern(
            selector.control_type,
            selector.name,
            spec.uia_pattern,
            authorization_sha256=authorization_for(node),
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
