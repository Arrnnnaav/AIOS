"""No effect may run from a cue the user was never shown.

Every case here is a way a presentation could be reported as acknowledged when
it was not: a receipt from a different cue, from a previous attempt at the
same cue, arriving after its deadline, or arriving out of order. The failure
is silent -- the action simply happens with nothing on screen.
"""

from __future__ import annotations

import pytest

from ghostcursor.act_protocol import (
    Backend,
    fallback_request_for,
    LifecycleState,
    PresentationRequest,
    PresentationWait,
    ProtocolError,
    Receipt,
    ReceiptKind,
    ReceiptPolicy,
    RefusalCode,
    TrustClass,
    VerifierMode,
    receipt_answers,
    trust_for,
)


POLICY = ReceiptPolicy(first_paint_deadline_ms=500, completion_deadline_ms=800)


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


def _receipt(kind: ReceiptKind, **overrides) -> Receipt:
    values = {
        "cue_id": "c1",
        "frame_generation": 1,
        "nonce": "n0",
        "presentation_generation": 1,
        "session_id": "s1",
    }
    values.update(overrides)
    return Receipt(kind, **values)


def _wait(request=None, policy=POLICY, started_ms=0.0) -> PresentationWait:
    return PresentationWait(request or _request(), policy, started_ms=started_ms)


# --- the happy path is the only path to an effect --------------------------


def test_a_geometry_presentation_that_starts_and_completes_may_execute():
    wait = _wait()

    wait.accept(_receipt(ReceiptKind.GEOMETRY_STARTED), now_ms=120.0)
    wait.accept(_receipt(ReceiptKind.PRESENTATION_COMPLETED), now_ms=770.0)

    assert wait.satisfied is True
    assert wait.may_execute is True


def test_a_rail_presentation_may_execute_too():
    wait = _wait()

    wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=40.0)
    wait.accept(_receipt(ReceiptKind.PRESENTATION_COMPLETED), now_ms=700.0)

    assert wait.may_execute is True


def test_nothing_may_execute_before_any_receipt_arrives():
    assert _wait().may_execute is False


def test_a_started_but_never_completed_presentation_may_not_execute():
    """The pointer was painted; the settled display never finished. The user
    saw a flash, not a cue."""

    wait = _wait()
    wait.accept(_receipt(ReceiptKind.GEOMETRY_STARTED), now_ms=100.0)

    assert wait.may_execute is False


# --- a receipt answers exactly one request ---------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_id", "s2"),
        ("cue_id", "c2"),
        ("nonce", "n1"),
        ("presentation_generation", 2),
        ("frame_generation", 2),
    ],
)
def test_a_receipt_from_a_different_request_is_refused(field, value):
    wait = _wait()

    with pytest.raises(ProtocolError, match="does not answer"):
        wait.accept(_receipt(ReceiptKind.RAIL_STARTED, **{field: value}), now_ms=10.0)


def test_a_receipt_from_a_previous_attempt_at_the_same_cue_is_refused():
    """Same session, same cue, older generation. Accepting it would let a
    re-presented cue be satisfied by the render that preceded its own
    re-request."""

    wait = _wait(_request(presentation_generation=3))

    with pytest.raises(ProtocolError, match="generation"):
        wait.accept(
            _receipt(ReceiptKind.RAIL_STARTED, presentation_generation=2),
            now_ms=10.0,
        )


def test_receipt_answers_compares_every_binding_field():
    request = _request()

    assert receipt_answers(request, _receipt(ReceiptKind.RAIL_STARTED)) is True
    assert (
        receipt_answers(request, _receipt(ReceiptKind.RAIL_STARTED, frame_generation=9))
        is False
    )


# --- deadlines, on an injected clock ---------------------------------------


def test_a_start_receipt_after_the_first_paint_deadline_is_a_render_timeout():
    wait = _wait()

    with pytest.raises(ProtocolError, match=RefusalCode.RENDER_TIMEOUT.value):
        wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=500.1)


def test_a_start_receipt_exactly_on_the_deadline_is_accepted():
    wait = _wait()

    wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=500.0)

    assert wait.satisfied is False  # started, not completed


def test_the_completion_deadline_is_measured_from_the_start_receipt():
    """Not from the request. A slow first paint must not eat the settled
    display's budget."""

    wait = _wait()
    wait.accept(_receipt(ReceiptKind.GEOMETRY_STARTED), now_ms=400.0)

    wait.accept(_receipt(ReceiptKind.PRESENTATION_COMPLETED), now_ms=1200.0)

    assert wait.satisfied is True


def test_a_completion_after_its_deadline_is_a_render_timeout():
    wait = _wait()
    wait.accept(_receipt(ReceiptKind.GEOMETRY_STARTED), now_ms=100.0)

    with pytest.raises(ProtocolError, match=RefusalCode.RENDER_TIMEOUT.value):
        wait.accept(_receipt(ReceiptKind.PRESENTATION_COMPLETED), now_ms=900.1)


def test_expiry_is_reported_while_the_receipt_is_still_missing():
    wait = _wait()

    assert wait.expired(now_ms=499.0) is False
    assert wait.expired(now_ms=501.0) is True


def test_expiry_switches_to_the_completion_deadline_once_started():
    wait = _wait()
    wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=100.0)

    assert wait.expired(now_ms=800.0) is False
    assert wait.expired(now_ms=901.0) is True


def test_a_satisfied_presentation_never_expires():
    wait = _wait()
    wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=10.0)
    wait.accept(_receipt(ReceiptKind.PRESENTATION_COMPLETED), now_ms=20.0)

    assert wait.expired(now_ms=10_000.0) is False


# --- ordering --------------------------------------------------------------


def test_a_completion_before_any_start_is_refused():
    wait = _wait()

    with pytest.raises(ProtocolError, match="before it has started"):
        wait.accept(_receipt(ReceiptKind.PRESENTATION_COMPLETED), now_ms=10.0)


def test_two_start_receipts_are_refused():
    wait = _wait()
    wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=10.0)

    with pytest.raises(ProtocolError, match="already started"):
        wait.accept(_receipt(ReceiptKind.GEOMETRY_STARTED), now_ms=20.0)


def test_two_completions_are_refused():
    wait = _wait()
    wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=10.0)
    wait.accept(_receipt(ReceiptKind.PRESENTATION_COMPLETED), now_ms=20.0)

    with pytest.raises(ProtocolError, match="already completed"):
        wait.accept(_receipt(ReceiptKind.PRESENTATION_COMPLETED), now_ms=30.0)


# --- geometry rejection and the rail fallback ------------------------------


def test_a_rejection_does_not_satisfy_the_wait_on_its_own():
    """Production may then request rail presentation -- but the effect still
    waits for that presentation's own receipts."""

    wait = _wait()

    wait.accept(_receipt(ReceiptKind.RENDER_REJECTED), now_ms=50.0)

    assert wait.rejected is True
    assert wait.may_execute is False


@pytest.mark.parametrize(
    "kind",
    [
        ReceiptKind.GEOMETRY_STARTED,
        ReceiptKind.RAIL_STARTED,
        ReceiptKind.PRESENTATION_COMPLETED,
        ReceiptKind.RENDER_REJECTED,
    ],
)
def test_a_refused_presentation_is_terminal_for_every_receipt_kind(kind):
    """Rail fallback is a NEW request with its own generation and receipts.

    Letting the refused wait continue meant the fallback was bound to nothing:
    a RAIL_STARTED plus a completion on the same request reached
    may_execute -- an effect running against a wait that had already refused.
    """

    wait = _wait()
    wait.accept(_receipt(ReceiptKind.RENDER_REJECTED), now_ms=50.0)

    with pytest.raises(ProtocolError, match="needs a new request"):
        wait.accept(_receipt(kind), now_ms=60.0)

    assert wait.may_execute is False


def test_a_rail_fallback_uses_a_fresh_request_and_then_may_execute():
    """The fallback is legitimate -- it just has to be bound."""

    refused = _wait()
    refused.accept(_receipt(ReceiptKind.RENDER_REJECTED), now_ms=50.0)

    fallback_request = _request(presentation_generation=2)
    fallback = _wait(fallback_request)
    fallback.accept(
        _receipt(ReceiptKind.RAIL_STARTED, presentation_generation=2), now_ms=10.0
    )
    fallback.accept(
        _receipt(ReceiptKind.PRESENTATION_COMPLETED, presentation_generation=2),
        now_ms=20.0,
    )

    assert refused.may_execute is False
    assert fallback.may_execute is True


def test_a_geometry_required_presentation_refuses_rather_than_falling_back():
    """A geometry_required acceptance case stops; it does not quietly become a
    rail-only run that still counts."""

    wait = _wait(_request(geometry_required=True))

    with pytest.raises(ProtocolError, match="geometry was required"):
        wait.accept(_receipt(ReceiptKind.RENDER_REJECTED), now_ms=50.0)


# --- trust is derived, never supplied --------------------------------------


@pytest.mark.parametrize(
    "backend,expected",
    [
        (Backend.OBJECT_MODEL, TrustClass.ARTIFACT),
        (Backend.UIA_PATTERN, TrustClass.LIVE_STATE),
        (Backend.LEGACY_IACCESSIBLE, TrustClass.LEGACY_LIVE_STATE),
        (Backend.RAW_INPUT, TrustClass.INFERRED),
    ],
)
def test_a_verified_node_shows_the_trust_its_backend_earned(backend, expected):
    assert trust_for(backend, LifecycleState.VERIFIED) is expected


def test_legacy_never_shows_the_class_a_true_uia_pattern_earns():
    assert trust_for(
        Backend.LEGACY_IACCESSIBLE, LifecycleState.VERIFIED
    ) is not trust_for(Backend.UIA_PATTERN, LifecycleState.VERIFIED)


@pytest.mark.parametrize(
    "state",
    [
        LifecycleState.PREPARING,
        LifecycleState.PRESENTING,
        LifecycleState.CONFIRMING,
        LifecycleState.EXECUTING,
        LifecycleState.VERIFYING,
    ],
)
@pytest.mark.parametrize("backend", list(Backend))
def test_no_backend_shows_a_verified_class_before_verification_returns(backend, state):
    """VERIFYING is the one that matters: the effect has already happened and
    its result is unknown, which is exactly when a success colour would lie."""

    assert trust_for(backend, state) is TrustClass.NEUTRAL


@pytest.mark.parametrize("backend", list(Backend))
def test_a_refused_node_shows_refused_whatever_acted(backend):
    assert trust_for(backend, LifecycleState.REFUSED) is TrustClass.REFUSED


def test_trust_refuses_a_backend_or_state_it_does_not_know():
    with pytest.raises(TypeError):
        trust_for("object_model", LifecycleState.VERIFIED)
    with pytest.raises(TypeError):
        trust_for(Backend.OBJECT_MODEL, "verified")


# --- the policy carries no invented numbers --------------------------------


def test_a_policy_requires_its_deadlines_to_be_supplied():
    """Phase E derives every budget from measurement; a default here would be
    the placeholder that derivation exists to replace."""

    with pytest.raises(TypeError):
        ReceiptPolicy()


@pytest.mark.parametrize("values", [(0, 800), (500, 0), (-1, 800)])
def test_a_non_positive_deadline_is_refused(values):
    with pytest.raises(ProtocolError, match="positive"):
        ReceiptPolicy(*values)


def test_a_fast_settle_after_a_slow_first_paint_is_a_legitimate_budget():
    """The two deadlines are independent and neither is measured from the
    other: first paint runs from the request, completion runs from the START
    RECEIPT. An earlier version refused this pairing on the stated grounds
    that completion was "measured after" first paint, which is not what the
    code does -- and it made a real budget unrepresentable.
    """

    policy = ReceiptPolicy(first_paint_deadline_ms=800, completion_deadline_ms=500)
    wait = PresentationWait(_request(), policy, started_ms=0.0)

    wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=700.0)
    wait.accept(_receipt(ReceiptKind.PRESENTATION_COMPLETED), now_ms=900.0)

    assert wait.may_execute is True


# --- the vocabulary is closed ----------------------------------------------


def test_the_three_verifier_modes_are_exactly_the_declared_ones():
    assert {mode.value for mode in VerifierMode} == {
        "observe_before",
        "confirm_before",
        "verify_after",
    }


def test_every_refusal_code_is_distinct_and_snake_cased():
    values = [code.value for code in RefusalCode]

    assert len(values) == len(set(values))
    assert all(value == value.lower() and " " not in value for value in values)


# --- the closed vocabulary is enforced at runtime --------------------------


def test_an_unknown_receipt_kind_is_refused_at_construction():
    """A plain string kind matched no branch and fell through to the
    completion branch, so it could satisfy a wait and let an effect run."""

    with pytest.raises(ProtocolError, match="not a known kind"):
        Receipt("bogus", "s1", "c1", "n0", 1, 1)


def test_an_unknown_kind_cannot_reach_execution_even_if_one_were_built():
    wait = _wait()
    wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=10.0)
    smuggled = _receipt(ReceiptKind.PRESENTATION_COMPLETED)
    object.__setattr__(smuggled, "kind", "bogus")

    with pytest.raises(ProtocolError, match="is not handled"):
        wait.accept(smuggled, now_ms=20.0)

    assert wait.may_execute is False


@pytest.mark.parametrize("field", ["session_id", "cue_id", "nonce"])
def test_an_empty_identity_is_refused(field):
    """An empty identity matches another empty identity."""

    with pytest.raises(ProtocolError, match="non-empty"):
        _receipt(ReceiptKind.RAIL_STARTED, **{field: ""})


@pytest.mark.parametrize(
    "field", ["presentation_generation", "frame_generation"]
)
@pytest.mark.parametrize("value", [True, -1, 1.0, "1"])
def test_a_generation_that_is_not_a_non_negative_integer_is_refused(field, value):
    """True == 1, so a boolean generation compares equal to the first real
    one -- the binding that stops a replay satisfied by a type confusion."""

    with pytest.raises(ProtocolError, match="non-negative integer"):
        _receipt(ReceiptKind.RAIL_STARTED, **{field: value})


def test_a_request_validates_its_own_identities_too():
    with pytest.raises(ProtocolError, match="non-empty"):
        _request(cue_id="")
    with pytest.raises(ProtocolError, match="boolean"):
        _request(geometry_required="yes")


@pytest.mark.parametrize("values", [(True, True), (500, 800.0), ("500", 800)])
def test_a_deadline_that_is_not_an_integer_is_refused(values):
    """bool is an int subclass, so ReceiptPolicy(True, True) built a policy
    with one-millisecond deadlines that timed out everything."""

    with pytest.raises(ProtocolError, match="must be an integer"):
        ReceiptPolicy(*values)


# --- geometry_required means geometry --------------------------------------


def test_a_geometry_required_cue_may_not_be_satisfied_by_rail_text():
    """Checking only RENDER_REJECTED let the acceptance case pass while
    proving none of the geometry it exists to prove."""

    wait = _wait(_request(geometry_required=True))

    with pytest.raises(ProtocolError, match="started as rail_started"):
        wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=10.0)

    assert wait.may_execute is False


def test_a_geometry_required_cue_is_satisfied_by_geometry():
    wait = _wait(_request(geometry_required=True))

    wait.accept(_receipt(ReceiptKind.GEOMETRY_STARTED), now_ms=10.0)
    wait.accept(_receipt(ReceiptKind.PRESENTATION_COMPLETED), now_ms=20.0)

    assert wait.may_execute is True


# --- ordering and clock sanity ---------------------------------------------


def test_geometry_cannot_be_refused_after_the_presentation_started():
    wait = _wait()
    wait.accept(_receipt(ReceiptKind.GEOMETRY_STARTED), now_ms=10.0)

    with pytest.raises(ProtocolError, match="after this presentation started"):
        wait.accept(_receipt(ReceiptKind.RENDER_REJECTED), now_ms=20.0)


def test_a_clock_that_moves_backwards_before_the_start_is_refused():
    """A negative elapsed time passes every deadline comparison."""

    wait = _wait(started_ms=100.0)

    with pytest.raises(ProtocolError, match="moved backwards"):
        wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=50.0)


def test_a_clock_that_moves_backwards_before_the_completion_is_refused():
    wait = _wait(started_ms=0.0)
    wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=100.0)

    with pytest.raises(ProtocolError, match="moved backwards"):
        wait.accept(_receipt(ReceiptKind.PRESENTATION_COMPLETED), now_ms=50.0)


# --- the clock only moves forward ------------------------------------------


def test_a_wait_that_already_expired_cannot_then_be_satisfied():
    """The central defect. `expired()` reported the deadline passed, and a
    receipt submitted against an earlier reading still reached may_execute --
    reachable through an ordinary polling loop."""

    wait = _wait()

    assert wait.expired(now_ms=9999.0) is True

    with pytest.raises(ProtocolError, match="moved backwards"):
        wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=400.0)

    assert wait.may_execute is False


def test_asking_whether_it_expired_advances_the_same_clock():
    """Asking the question is observing the clock."""

    wait = _wait()
    wait.expired(now_ms=300.0)

    with pytest.raises(ProtocolError, match="moved backwards"):
        wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=200.0)


def test_a_receipt_refused_as_late_cannot_be_resubmitted_earlier():
    wait = _wait()
    with pytest.raises(ProtocolError):
        wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=10_000.0)

    with pytest.raises(ProtocolError, match="moved backwards"):
        wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=100.0)

    assert wait.may_execute is False


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_clock_reading_is_refused(bad):
    """`NaN < x` and `NaN > x` are both False, so NaN passes every deadline
    comparison and reaches may_execute with nothing enforced."""

    wait = _wait()

    with pytest.raises(ProtocolError, match="finite"):
        wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=bad)
    with pytest.raises(ProtocolError, match="finite"):
        wait.expired(now_ms=bad)


@pytest.mark.parametrize("bad", [float("nan"), True, "0", None])
def test_a_wait_validates_its_own_start_time(bad):
    with pytest.raises(ProtocolError):
        PresentationWait(_request(), POLICY, started_ms=bad)


def test_a_wait_validates_its_request_and_policy():
    with pytest.raises(ProtocolError, match="PresentationRequest"):
        PresentationWait(object(), POLICY, started_ms=0.0)
    with pytest.raises(ProtocolError, match="ReceiptPolicy"):
        PresentationWait(_request(), object(), started_ms=0.0)


def test_only_a_receipt_may_be_accepted():
    with pytest.raises(ProtocolError, match="only a Receipt"):
        _wait().accept(object(), now_ms=10.0)


# --- expired() and accept() share one predicate ----------------------------


def test_expired_and_accept_agree_on_the_boundary_instant():
    """They computed this separately and could disagree about the same
    instant -- one reporting a timeout while the other still accepted."""

    on_time = _wait()
    assert on_time.expired(now_ms=500.0) is False
    on_time.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=500.0)

    late = _wait()
    assert late.expired(now_ms=500.1) is True
    with pytest.raises(ProtocolError, match=RefusalCode.RENDER_TIMEOUT.value):
        late.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=500.1)


def test_a_refused_presentation_is_not_reported_as_expired():
    """It ended. Reporting a render timeout for a clean rejection puts the
    wrong refusal code in the run record."""

    wait = _wait()
    wait.accept(_receipt(ReceiptKind.RENDER_REJECTED), now_ms=50.0)

    assert wait.expired(now_ms=9999.0) is False
    assert wait.rejected is True


def test_a_rejection_is_itself_subject_to_the_first_paint_deadline():
    """It was handled before the clock guard and bound by no deadline at
    all -- accepted long after expired() had already returned True."""

    wait = _wait()

    with pytest.raises(ProtocolError, match=RefusalCode.RENDER_TIMEOUT.value):
        wait.accept(_receipt(ReceiptKind.RENDER_REJECTED), now_ms=10_000.0)


# --- a rail fallback is genuinely fresh ------------------------------------


def test_a_hand_built_fallback_with_the_same_identity_is_the_hazard():
    """The wait cannot enforce freshness -- it never sees the other request --
    so the helper is what makes the binding distinguish them."""

    rejected = _request()
    fallback = fallback_request_for(rejected, nonce="n1")

    assert fallback.presentation_generation > rejected.presentation_generation
    assert fallback.frame_generation > rejected.frame_generation
    assert fallback.nonce != rejected.nonce
    assert fallback.geometry_required is False


def test_receipts_for_the_rejected_request_do_not_satisfy_its_fallback():
    rejected = _request()
    fallback = fallback_request_for(rejected, nonce="n1")
    wait = PresentationWait(fallback, POLICY, started_ms=0.0)

    with pytest.raises(ProtocolError, match="does not answer"):
        wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=10.0)


def test_a_fallback_of_a_geometry_required_request_drops_the_requirement():
    """A fallback exists precisely because geometry was unavailable."""

    fallback = fallback_request_for(_request(geometry_required=True), nonce="n1")

    assert fallback.geometry_required is False


# --- trust fails closed on a new state -------------------------------------


def test_every_lifecycle_state_is_explicitly_classified():
    """The real hazard: a member added later and never classified.

    A new Backend fails closed with a KeyError, but a new STATE used to fall
    through to the backend's VERIFIED class -- the wrong way round for a
    module whose premise is that a viewer cannot check the colour. Adding a
    member without putting it in exactly one bucket fails here.
    """

    from ghostcursor.act_protocol import UNPROVEN_STATES

    classified = set(UNPROVEN_STATES) | {
        LifecycleState.REFUSED,
        LifecycleState.VERIFIED,
    }

    assert classified == set(LifecycleState)
    assert LifecycleState.VERIFIED not in UNPROVEN_STATES
    assert LifecycleState.REFUSED not in UNPROVEN_STATES


def test_a_state_that_is_neither_proven_nor_unproven_refuses(monkeypatch):
    """Exercises the branch directly by removing a state from the unproven
    set: it is then neither REFUSED, nor unproven, nor VERIFIED."""

    from ghostcursor import act_protocol

    monkeypatch.setattr(
        act_protocol,
        "UNPROVEN_STATES",
        frozenset(act_protocol.UNPROVEN_STATES - {LifecycleState.EXECUTING}),
    )

    with pytest.raises(ProtocolError, match="no defined trust class"):
        act_protocol.trust_for(Backend.OBJECT_MODEL, LifecycleState.EXECUTING)


def test_every_declared_lifecycle_state_has_a_defined_trust_class():
    for state in LifecycleState:
        assert isinstance(trust_for(Backend.OBJECT_MODEL, state), TrustClass)


# --- refusals are machine-readable -----------------------------------------


def test_a_render_timeout_carries_its_code_not_only_its_message():
    """A caller could only tell a timeout from an ordering error by matching
    prose, which made the message string load-bearing."""

    wait = _wait()

    with pytest.raises(ProtocolError) as raised:
        wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=10_000.0)

    assert raised.value.code is RefusalCode.RENDER_TIMEOUT


def test_an_ordering_error_carries_its_own_code_not_merely_a_different_one():
    """This asserted only `is not RENDER_TIMEOUT`, which `code is None`
    satisfies -- so it passed while the code was never set at all."""

    wait = _wait()

    with pytest.raises(ProtocolError) as raised:
        wait.accept(_receipt(ReceiptKind.PRESENTATION_COMPLETED), now_ms=10.0)

    assert raised.value.code is RefusalCode.PRESENTATION_OUT_OF_ORDER


def test_every_refusal_this_module_raises_carries_a_code():
    """A caller must not have to string-match prose to tell refusals apart.
    29 assertions in this file matched messages and 2 matched codes."""

    import ast
    import pathlib as _pathlib

    from ghostcursor import act_protocol

    source = _pathlib.Path(act_protocol.__file__).read_text(encoding="utf-8")
    codeless = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        call = node.exc
        if not isinstance(call, ast.Call):
            continue
        name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
        if name == "ProtocolError" and len(call.args) < 2:
            codeless.append(node.lineno)

    assert not codeless, f"ProtocolError raised with no RefusalCode at {codeless}"


@pytest.mark.parametrize(
    "code",
    [
        RefusalCode.RENDER_TIMEOUT,
        RefusalCode.PRESENTATION_OUT_OF_ORDER,
        RefusalCode.PRESENTATION_REFUSED,
        RefusalCode.CLOCK_REGRESSED,
        RefusalCode.RECEIPT_UNBOUND,
    ],
)
def test_each_presentation_refusal_code_is_actually_reachable(code):
    """Seven of nine codes were raised nowhere; a code nothing raises is a
    label, not a refusal."""

    import ast
    import pathlib as _pathlib

    from ghostcursor import act_protocol

    source = _pathlib.Path(act_protocol.__file__).read_text(encoding="utf-8")

    assert f"RefusalCode.{code.name}" in source


def test_a_clock_regression_is_told_apart_from_a_timeout():
    wait = _wait(started_ms=100.0)

    with pytest.raises(ProtocolError) as raised:
        wait.accept(_receipt(ReceiptKind.RAIL_STARTED), now_ms=50.0)

    assert raised.value.code is RefusalCode.CLOCK_REGRESSED


def test_an_unbound_receipt_is_told_apart_from_an_ordering_error():
    wait = _wait()

    with pytest.raises(ProtocolError) as raised:
        wait.accept(_receipt(ReceiptKind.RAIL_STARTED, cue_id="other"), now_ms=10.0)

    assert raised.value.code is RefusalCode.RECEIPT_UNBOUND


# --- a rejection ends the wait however it is classified --------------------


def test_a_geometry_required_rejection_also_terminates_the_wait():
    """The terminal flag was set only on the permissive path. A
    geometry_required cue could be refused and then satisfied by a start and a
    completion on the identical nonce and generation, reaching may_execute."""

    wait = _wait(_request(geometry_required=True))

    with pytest.raises(ProtocolError, match="geometry was required"):
        wait.accept(_receipt(ReceiptKind.RENDER_REJECTED), now_ms=50.0)

    assert wait.rejected is True
    with pytest.raises(ProtocolError, match="needs a new request"):
        wait.accept(_receipt(ReceiptKind.GEOMETRY_STARTED), now_ms=60.0)
    assert wait.may_execute is False


def test_a_late_rejection_also_terminates_the_wait():
    wait = _wait()
    wait.accept(_receipt(ReceiptKind.GEOMETRY_STARTED), now_ms=10.0)

    with pytest.raises(ProtocolError, match="after this presentation started"):
        wait.accept(_receipt(ReceiptKind.RENDER_REJECTED), now_ms=20.0)

    assert wait.rejected is True
    with pytest.raises(ProtocolError, match="needs a new request"):
        wait.accept(_receipt(ReceiptKind.PRESENTATION_COMPLETED), now_ms=30.0)
    assert wait.may_execute is False


# --- the fallback mints its own nonce --------------------------------------


def test_a_fallback_mints_its_own_nonce_by_default():
    """It was caller-supplied, so `fallback_request_for(r, nonce=r.nonce)`
    returned the rejected request's own nonce -- the collision the helper
    exists to prevent, while its docstring claimed it minted one."""

    rejected = _request()
    a = fallback_request_for(rejected)
    b = fallback_request_for(rejected)

    assert a.nonce != rejected.nonce
    assert b.nonce != a.nonce
    assert len(a.nonce) >= 16


def test_a_fallback_may_not_be_handed_the_rejected_nonce():
    rejected = _request()

    with pytest.raises(ProtocolError, match="may not reuse"):
        fallback_request_for(rejected, nonce=rejected.nonce)


def test_an_unmapped_backend_refuses_as_a_protocol_error():
    """It escaped as a KeyError from a function that otherwise raises
    ProtocolError, so a caller catching ProtocolError took a crash."""

    from ghostcursor import act_protocol

    original = dict(act_protocol._VERIFIED_TRUST)
    try:
        act_protocol._VERIFIED_TRUST.clear()
        with pytest.raises(ProtocolError, match="no defined trust class"):
            trust_for(Backend.OBJECT_MODEL, LifecycleState.VERIFIED)
    finally:
        act_protocol._VERIFIED_TRUST.update(original)
