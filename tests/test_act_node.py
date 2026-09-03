"""The node flow is where four contracts finally meet a caller.

Every case here is a way an effect could happen that the user did not see,
did not authorize, or that landed on something other than what was shown.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ghostcursor.act_node import (
    NodeRefused,
    Observation,
    execute_node,
)
from ghostcursor.act_protocol import (
    LifecycleState,
    PresentationRequest,
    Receipt,
    ReceiptKind,
    ReceiptPolicy,
    RefusalCode,
    TrustClass,
)
from ghostcursor.uia_identity import IdentityPolicy

POLICY = ReceiptPolicy(first_paint_deadline_ms=500, completion_deadline_ms=800)
DIGEST = "a" * 64


def _identity_policy(**overrides) -> IdentityPolicy:
    values = {
        "control_type": "Button",
        "evidence_fields": ("automation_id",),
        "identity_mode": "runtime_id_required",
        "operation_id": "powerpoint.new_slide",
        "required_fields": ("control_type", "name", "runtime_id"),
        "selector_id": "powerpoint.new-slide",
        "selector_sha256": DIGEST,
    }
    values.update(overrides)
    return IdentityPolicy(**values)


def _spec(backend="uia_pattern", **overrides):
    values = {
        "backend": backend,
        "draws_a_pointer": backend != "object_model",
        "identity": _identity_policy() if backend != "object_model" else None,
        "uia_pattern": "Invoke" if backend != "object_model" else None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _node(node_id="n001", operation_id="powerpoint.new_slide"):
    return SimpleNamespace(node_id=node_id, operation_id=operation_id)


def _request(**overrides) -> PresentationRequest:
    values = {
        "cue_id": "c1",
        "frame_generation": 1,
        "geometry_required": False,
        "nonce": "n0",
        "presentation_generation": 1,
        "session_id": "s1",
    }
    values.update(overrides)
    return PresentationRequest(**values)


def _receipts(request, kinds=None, sink=None, clock=None):
    # `kinds or default` would treat an empty tuple as absent, which is
    # exactly the no-receipts case one of these tests needs.
    if kinds is None:
        kinds = (ReceiptKind.GEOMETRY_STARTED, ReceiptKind.PRESENTATION_COMPLETED)
    issued = [
        Receipt(
            kind,
            request.session_id,
            request.cue_id,
            request.nonce,
            request.presentation_generation,
            request.frame_generation,
        )
        for kind in kinds
    ]
    if sink is not None:
        # Reported one at a time, as the real presenter does. Handing the
        # whole list back and letting the caller timestamp it afterwards is
        # exactly the defect this argument exists to prevent.
        #
        # The times come from the SAME clock `execute_node` is using. A fake
        # that invented its own numbers reported receipts from before the
        # wait had started, which the wait correctly rejects as the clock
        # moving backwards -- proving nothing about the deadlines.
        for receipt in issued:
            sink(receipt, clock() if clock is not None else 0.0)
    return issued


def _identity(**overrides):
    values = {
        "automation_id": "SheetTab",
        "control_type": "Button",
        "name": "New Slide",
        "runtime_id": (7, 1, 2, 3),
    }
    values.update(overrides)
    return values


def _observation(**overrides) -> Observation:
    values = {
        "identity": _identity(),
        "match_count": 1,
        "rectangle": (10, 20, 110, 60),
        "semantic": {"slides": 3},
    }
    values.update(overrides)
    return Observation(**values)


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 10.0
        return self.now


def _run(
    spec=None,
    *,
    observations=None,
    receipt_kinds=None,
    verified=True,
    request=None,
    on_state=None,
):
    spec = spec or _spec()
    request = request or _request()
    calls = {"authorized": [], "dispatched": [], "verified": []}
    seq = list(observations or [_observation(), _observation()])
    # One clock, shared by the node and the fake presenter. Two clocks would
    # let receipts be reported from an instant the wait never saw.
    clock = _Clock()

    def observe(mode):
        return seq.pop(0)

    def present(req, baseline, sink=None):
        return _receipts(req, receipt_kinds, sink, clock)

    def authorize(facts):
        calls["authorized"].append(facts)
        return SimpleNamespace(token="t")

    def dispatch(token, confirmed):
        calls["dispatched"].append((token, confirmed))

    def verify(node):
        calls["verified"].append(node)
        return verified

    outcome = execute_node(
        _node(),
        spec,
        request=request,
        policy=POLICY,
        observe=observe,
        present=present,
        authorize=authorize,
        dispatch=dispatch,
        verify=verify,
        clock=clock,
        on_state=on_state,
    )
    return outcome, calls


# --- the happy path, and its order -----------------------------------------


def test_a_uia_node_observes_presents_confirms_authorizes_dispatches_verifies():
    seen: list[LifecycleState] = []
    outcome, calls = _run(on_state=seen.append)

    assert outcome.verified is True
    assert outcome.trust is TrustClass.LIVE_STATE
    assert seen == [
        LifecycleState.PREPARING,
        LifecycleState.PRESENTING,
        LifecycleState.CONFIRMING,
        LifecycleState.EXECUTING,
        LifecycleState.VERIFYING,
        LifecycleState.VERIFIED,
    ]
    assert len(calls["dispatched"]) == 1


def test_an_object_model_node_skips_observation_and_never_points():
    """It drives an application API: no control to resolve, nothing to point
    at, and verification comes from the saved artifact."""

    seen: list[LifecycleState] = []
    outcome, calls = _run(_spec("object_model"), observations=[], on_state=seen.append)

    assert outcome.verified is True
    assert outcome.trust is TrustClass.ARTIFACT
    assert LifecycleState.CONFIRMING not in seen
    assert calls["dispatched"][0][1] is None


def test_a_legacy_node_carries_the_weaker_trust_class():
    outcome, _calls = _run(_spec("legacy_iaccessible"))

    assert outcome.trust is TrustClass.LEGACY_LIVE_STATE


# --- nothing dispatches without an acknowledged presentation ---------------


def test_a_node_whose_cue_never_completed_does_not_dispatch():
    with pytest.raises(NodeRefused) as raised:
        _run(receipt_kinds=(ReceiptKind.GEOMETRY_STARTED,))

    assert raised.value.code is RefusalCode.RENDER_TIMEOUT


def test_a_node_whose_cue_was_never_acknowledged_at_all_does_not_dispatch():
    with pytest.raises(NodeRefused) as raised:
        _run(receipt_kinds=())

    assert raised.value.code is RefusalCode.RENDER_TIMEOUT


def test_a_receipt_for_another_request_does_not_authorize_this_node():
    clock = _Clock()

    def present(req, baseline, sink=None):
        other = PresentationRequest(
            cue_id="other",
            frame_generation=1,
            geometry_required=False,
            nonce="n0",
            presentation_generation=1,
            session_id="s1",
        )
        return _receipts(other, sink=sink, clock=clock)

    with pytest.raises(NodeRefused) as raised:
        execute_node(
            _node(),
            _spec(),
            request=_request(),
            policy=POLICY,
            observe=lambda mode: _observation(),
            present=present,
            authorize=lambda facts: None,
            dispatch=lambda token, confirmed: pytest.fail("must not dispatch"),
            verify=lambda node: True,
            clock=clock,
        )

    assert raised.value.code is RefusalCode.RECEIPT_UNBOUND


def test_an_object_model_node_may_not_be_asked_to_prove_geometry():
    """D109 from the other side: a node that cannot point at anything must not
    be asked for geometry it will never have."""

    with pytest.raises(NodeRefused, match="cannot satisfy a geometry-required"):
        _run(
            _spec("object_model"),
            observations=[],
            request=_request(geometry_required=True),
        )


# --- the world may not move between the cue and the act --------------------


def test_a_semantic_change_during_the_cue_refuses_before_dispatch():
    """The cue takes real time on purpose, and the user can act during it.
    Comparing the result against a pre-cue observation would report their
    change as ours."""

    with pytest.raises(NodeRefused) as raised:
        _run(
            observations=[
                _observation(semantic={"slides": 3}),
                _observation(semantic={"slides": 4}),
            ]
        )

    assert raised.value.code is RefusalCode.PRECONDITION_DRIFTED


def test_a_moved_target_identity_refuses_before_dispatch():
    with pytest.raises(NodeRefused) as raised:
        _run(
            observations=[
                _observation(),
                _observation(identity=_identity(runtime_id=(9, 9, 9, 9))),
            ]
        )

    assert raised.value.code is RefusalCode.TARGET_IDENTITY_MISMATCH


def test_a_control_of_the_wrong_type_refuses_even_when_nothing_else_moved():
    with pytest.raises(NodeRefused) as raised:
        _run(
            observations=[
                _observation(identity=_identity(control_type="TabItem")),
                _observation(identity=_identity(control_type="TabItem")),
            ]
        )

    assert raised.value.code is RefusalCode.TARGET_IDENTITY_MISMATCH


def test_a_selector_matching_more_than_one_control_refuses():
    with pytest.raises(NodeRefused) as raised:
        _run(observations=[_observation(), _observation(match_count=2)])

    assert raised.value.code is RefusalCode.TARGET_IDENTITY_MISMATCH


@pytest.mark.parametrize("which", [0, 1])
def test_an_observation_without_identity_refuses(which):
    observations = [_observation(), _observation()]
    observations[which] = _observation(identity=None)

    with pytest.raises(NodeRefused) as raised:
        _run(observations=observations)

    assert raised.value.code is RefusalCode.TARGET_IDENTITY_MISMATCH


# --- authorization happens after confirmation, never before ----------------


def test_the_token_is_minted_only_after_the_identity_check_passes():
    minted: list = []
    clock = _Clock()

    def authorize(facts):
        minted.append(facts)
        return SimpleNamespace(token="t")

    with pytest.raises(NodeRefused):
        execute_node(
            _node(),
            _spec(),
            request=_request(),
            policy=POLICY,
            observe=lambda mode: _observation(
                identity=_identity(
                    runtime_id=(1,) if mode == "confirm_before" else (2,)
                )
            ),
            present=lambda req, baseline, sink=None: _receipts(
                req, sink=sink, clock=clock
            ),
            authorize=authorize,
            dispatch=lambda token, confirmed: pytest.fail("must not dispatch"),
            verify=lambda node: True,
            clock=clock,
        )

    assert minted == []


def test_the_authorization_carries_the_confirmed_identity():
    _outcome, calls = _run()

    facts = calls["authorized"][0]
    assert facts["operation_id"] == "powerpoint.new_slide"
    assert facts["identity"]["required"]["control_type"] == "Button"
    assert facts["identity"]["selector_sha256"] == DIGEST


# --- verification decides the outcome, not the dispatcher ------------------


def test_a_dispatched_node_whose_verification_fails_is_not_verified():
    outcome, calls = _run(verified=False)

    assert outcome.verified is False
    assert outcome.trust is TrustClass.REFUSED
    assert len(calls["dispatched"]) == 1


def test_an_unknown_backend_refuses_before_anything_happens():
    with pytest.raises(NodeRefused) as raised:
        _run(_spec("vision"))

    assert raised.value.code is RefusalCode.UNSUPPORTED_ACTION_SURFACE
