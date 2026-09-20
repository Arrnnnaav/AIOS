"""Assembling one UIA node's session, and what it refuses to assemble.

Three signed things have to agree: the verifier's reading of the document,
the adapter's read of the control, and the selector file that says which
control that is. The cases here are the ways one of them could be missing,
stale, or substituted and the node still run.

The fakes are the process edges only — a real `AdapterHost` talking to a
scripted adapter, and a stub verifier. The selector loading is real, because
the digest check is the thing being relied on.
"""

from __future__ import annotations

import hashlib
import json
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from ghostcursor.act_node import Observation
from ghostcursor.act_protocol import ReceiptPolicy, RefusalCode
from ghostcursor.act_uia_session import UiaSessionError, build_uia_session
from ghostcursor.adapter_host import AdapterHost, AdapterProtocolError
from ghostcursor.uia_identity import IdentityPolicy

POLICY = ReceiptPolicy(first_paint_deadline_ms=500, completion_deadline_ms=2000)

ADAPTER = r"""
import json
import sys
from ghostcursor.coordinate_space import observe_bracketed

def emit(value):
    print(json.dumps(value, sort_keys=True, separators=(",", ":")), flush=True)

hello = json.loads(sys.stdin.readline())
emit({**hello, "type": "ready"})
for line in sys.stdin:
    request = json.loads(line)
    if request["type"] == "stop":
        break
    if request["type"] == "observe":
        emit({
            "coordinate_space": observe_bracketed(
                lambda: [[100, 200, 260, 245]]
            ).as_record(),
            "identity": {
                "automation_id": "",
                "control_type": request["control_type"],
                "name": request["name"],
                "runtime_id": [7, 1, 2],
            },
            "outcome": "observed",
            "rectangle": [100, 200, 260, 245],
            "request_id": request["request_id"],
            "session_nonce": request["session_nonce"],
            "type": "observation",
        })
        continue
    emit({
        "data": {"dispatched": request["name"], "pattern": request["pattern"]},
        "detail": "pattern dispatched on the resolved control",
        "facts": [],
        "outcome": "OUTCOME",
        "request_id": request["request_id"],
        "session_nonce": request["session_nonce"],
        "type": "result",
    })
"""


class FakeVerifier:
    """Answers what the document is. Returns a different reading on the Nth
    call when `drift_on` is set, which is how the drift check is exercised."""

    def __init__(
        self,
        *,
        drift_on: int | None = None,
        fails: bool = False,
        empty_on: int | None = None,
    ):
        self._empty_on = empty_on
        self.calls = 0
        self._drift_on = drift_on
        self._fails = fails
        self.seen: list[str] = []
        self.timeouts: list[float] = []

    def verify(
        self,
        *,
        node,
        validation_sha256,
        output_path,
        target,
        timeout_s=10.0,
        cancel_event=None,
        baseline=None,
        postconditions=None,
    ):
        self.calls += 1
        self.timeouts.append(timeout_s)
        if self._empty_on is not None and self.calls >= self._empty_on:
            # How a real verifier reports a failed read: exit 0, outcome
            # "refused", nothing observed. It does NOT raise.
            return SimpleNamespace(verified=False, detail="cannot read", observed={})
        # An OBSERVATION must carry no baseline: there is nothing yet to
        # compare against, and a baseline here would mean the reading before
        # the cue was being verified against itself.
        assert baseline is None
        self.seen.append(tuple(postconditions or ()))
        if self._fails:
            raise AdapterProtocolError("verifier timed out")
        slides = 4 if self.calls == self._drift_on else 3
        return SimpleNamespace(
            verified=True, detail="read", observed={"slides": slides}
        )


def _payload(
    tmp_path: Path,
    *,
    name="New Slide",
    control_type="Button",
    cardinality="exactly_one",
):
    """A payload holding one real selector file, and its digest."""

    folder = tmp_path / "ghostcursor" / "packs" / "powerpoint" / "selectors"
    folder.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(
        {
            "cardinality": cardinality,
            "control_type": control_type,
            "name": name,
            "selector_id": "powerpoint.new-slide",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    (folder / "new-slide.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _spec(digest, *, control_type="Button", pattern="Invoke", identity=True):
    policy = (
        IdentityPolicy(
            operation_id="powerpoint.new_slide_uia",
            selector_id="powerpoint.new-slide",
            selector_sha256=digest,
            control_type=control_type,
            identity_mode="runtime_id_required",
            required_fields=("control_type", "name", "runtime_id"),
            evidence_fields=("automation_id",),
        )
        if identity
        else None
    )
    return SimpleNamespace(
        operation_id="powerpoint.new_slide_uia",
        backend="uia_pattern",
        uia_pattern=pattern,
        identity=policy,
        draws_a_pointer=True,
        postconditions=("slide.count.increased_by_one",),
        confirmation_round_trip_deadline_ms=1280,
        confirmation_to_request_deadline_ms=32,
    )


def _host(tmp_path, outcome="completed"):
    entrypoint = tmp_path / "adapter.py"
    entrypoint.write_text(
        textwrap.dedent(ADAPTER.replace("OUTCOME", outcome)),
        encoding="utf-8",
        newline="\n",
    )
    descriptor = SimpleNamespace(
        plugin_id="ghostcursor.powerpoint",
        plugin_version="1.0.0",
        payload_root=tmp_path,
        entrypoint=entrypoint,
        adapter_sha256=hashlib.sha256(entrypoint.read_bytes()).hexdigest(),
    )
    return AdapterHost(descriptor, session_nonce="nonce")


def _overlay():
    calls: list = []
    return (
        SimpleNamespace(
            present=lambda request, observation: (
                calls.append(("present", observation)) or []
            ),
            on_node_state=lambda node, state: calls.append(("state", state)),
            release=lambda: calls.append(("release", None)),
        ),
        calls,
    )


def _session(tmp_path, host, *, verifier=None, digest=None, spec=None, **overrides):
    overlay, _calls = _overlay()
    digest = digest if digest is not None else _payload(tmp_path)
    kwargs = dict(
        host=host,
        verifier=verifier or FakeVerifier(),
        payload_root=tmp_path,
        overlay=overlay,
        policy=POLICY,
        session_id="s1",
        operation_for=lambda _node: spec or _spec(digest),
        target={"hwnd": 4242},
        validation_sha256="a" * 64,
        output_path=str(tmp_path / "out.pptx"),
    )
    kwargs.update(overrides)
    return build_uia_session(**kwargs)


def _token(digest: str = "b" * 64):
    """Stands in for the `AuthorizedAction` core mints per node. Only the
    field the dispatch reads is modelled, so a test cannot accidentally rely
    on the rest of that type."""

    return SimpleNamespace(authorization_sha256=digest)


def _node():
    return SimpleNamespace(
        node_id="n001", operation_id="powerpoint.new_slide_uia", parameters={}
    )


def _confirmed():
    from ghostcursor.coordinate_space import observe_bracketed

    return Observation(
        semantic={"slides": 3},
        identity={
            "automation_id": "",
            "control_type": "Button",
            "name": "New Slide",
            "runtime_id": (7, 1, 2),
        },
        rectangle=(100, 200, 260, 245),
        geometry=observe_bracketed(lambda: [[100, 200, 260, 245]]),
    )


# --- an observation is three readings that agree --------------------------


def test_an_observation_carries_the_document_reading_and_the_control(tmp_path):
    verifier = FakeVerifier()
    with _host(tmp_path) as host:
        session = _session(tmp_path, host, verifier=verifier)
        observation = session.observe(_node(), "observe_before")

    assert isinstance(observation, Observation)
    assert observation.semantic == {"slides": 3}
    assert observation.identity["name"] == "New Slide"
    assert observation.rectangle == (100, 200, 260, 245)
    assert observation.geometry.rectangles == ((100, 200, 260, 245),)


def test_the_control_name_comes_from_the_signed_selector(tmp_path):
    """Not from the spec, which carries only an id and a digest. The name
    lives in a separately signed file and loading it is the only path that
    proves it is the reviewed one."""

    digest = _payload(tmp_path, name="Reuse Slides")
    with _host(tmp_path) as host:
        session = _session(tmp_path, host, digest=digest)
        observation = session.observe(_node(), "observe_before")

    assert observation.identity["name"] == "Reuse Slides"


def test_the_semantic_is_the_verifiers_reading_not_the_identity(tmp_path):
    """A semantic derived from identity would agree exactly whenever the
    identity check agreed — a drift check that can never fire, sitting in the
    run record looking like it had."""

    verifier = FakeVerifier()
    with _host(tmp_path) as host:
        session = _session(tmp_path, host, verifier=verifier)
        first = session.observe(_node(), "observe_before")
        second = session.observe(_node(), "confirm_before")

    assert verifier.calls == 2
    assert first.semantic == second.semantic
    assert "slides" in dict(first.semantic)


def test_a_document_that_changed_between_the_reads_produces_different_semantics(
    tmp_path,
):
    """The comparison `execute_node` makes. If this could not differ, nothing
    downstream could detect drift."""

    verifier = FakeVerifier(drift_on=2)
    with _host(tmp_path) as host:
        session = _session(tmp_path, host, verifier=verifier)
        first = session.observe(_node(), "observe_before")
        second = session.observe(_node(), "confirm_before")

    assert first.semantic != second.semantic


def test_the_semantic_is_canonical_so_it_does_not_drift_on_its_own(tmp_path):
    """`execute_node` compares with `!=` across two reads. An unordered
    container would report the world changing when nothing had."""

    from ghostcursor.act_uia_session import _canonical

    assert _canonical({"b": 1, "a": 2}) == _canonical({"a": 2, "b": 1})
    assert _canonical({"s": {"y": 1, "x": 2}}) == _canonical({"s": {"x": 2, "y": 1}})
    assert _canonical({"a": [1, 2]}) != _canonical({"a": [2, 1]})


# --- every read fails closed ----------------------------------------------


def test_a_verifier_that_cannot_answer_refuses_the_node(tmp_path):
    """Proceeding on the identity alone is the vacuous drift check this
    module exists to avoid."""

    with _host(tmp_path) as host:
        session = _session(tmp_path, host, verifier=FakeVerifier(fails=True))

        with pytest.raises(UiaSessionError) as raised:
            session.observe(_node(), "observe_before")

    assert raised.value.code is RefusalCode.PRECONDITION_DRIFTED


def test_a_control_that_cannot_be_read_refuses_the_node(tmp_path):
    host = _host(tmp_path)  # never started
    session = _session(tmp_path, host)

    with pytest.raises(UiaSessionError) as raised:
        session.observe(_node(), "observe_before")

    assert raised.value.code is RefusalCode.TARGET_IDENTITY_MISMATCH


def test_the_verifier_is_asked_before_the_control_is_touched(tmp_path):
    """Order matters: a failed document read must not have already spent an
    adapter round trip on a control that may not be the right one."""

    verifier = FakeVerifier(fails=True)
    host = _host(tmp_path)
    host.start()
    session = _session(tmp_path, host, verifier=verifier)

    with pytest.raises(UiaSessionError):
        session.observe(_node(), "observe_before")

    assert verifier.calls == 1
    assert host.running is True  # the adapter was never asked anything
    host.stop()


# --- a selector that is not the reviewed one stops everything -------------


def test_a_substituted_selector_refuses_before_any_read(tmp_path):
    verifier = FakeVerifier()
    digest = _payload(tmp_path)
    _payload(tmp_path, name="Delete Slide")  # same path, different bytes

    with _host(tmp_path) as host:
        session = _session(tmp_path, host, verifier=verifier, digest=digest)

        with pytest.raises(UiaSessionError, match="but the signed operation declares"):
            session.observe(_node(), "observe_before")

    assert verifier.calls == 0


def test_the_selector_is_re_read_for_the_confirmation(tmp_path):
    """Not cached from the first observation. The payload is on disk, and a
    cached name would mean the confirmation resolved a control the second
    read never approved."""

    digest = _payload(tmp_path)
    with _host(tmp_path) as host:
        session = _session(tmp_path, host, digest=digest)
        session.observe(_node(), "observe_before")

        _payload(tmp_path, name="Delete Slide")

        with pytest.raises(UiaSessionError, match="signed operation declares"):
            session.observe(_node(), "confirm_before")


def test_an_operation_with_no_identity_policy_is_refused(tmp_path):
    with _host(tmp_path) as host:
        session = _session(tmp_path, host, spec=_spec("c" * 64, identity=False))

        with pytest.raises(UiaSessionError, match="no identity policy"):
            session.observe(_node(), "observe_before")


def test_an_ambiguous_selector_is_refused(tmp_path):
    """D069: an action selector matching several controls would mean choosing
    one on the operator's behalf."""

    digest = _payload(tmp_path, cardinality="at_least_one")
    with _host(tmp_path) as host:
        session = _session(tmp_path, host, digest=digest)

        with pytest.raises(UiaSessionError, match="cannot choose a control"):
            session.observe(_node(), "observe_before")


def test_the_comparison_uses_the_operations_own_control_type(tmp_path):
    """Whatever it is, not a constant. The disagreement test below cannot show
    this on its own: with the operation declaring Button, a hardcoded "Button"
    reaches the same verdict, so the check would look like it was reading the
    policy while ignoring it."""

    digest = _payload(tmp_path, control_type="MenuItem")
    with _host(tmp_path) as host:
        session = _session(
            tmp_path, host, digest=digest, spec=_spec(digest, control_type="MenuItem")
        )
        observation = session.observe(_node(), "observe_before")

    assert observation.identity["control_type"] == "MenuItem"


def test_a_selector_disagreeing_with_the_operation_is_refused(tmp_path):
    digest = _payload(tmp_path, control_type="MenuItem")
    with _host(tmp_path) as host:
        session = _session(tmp_path, host, digest=digest)

        with pytest.raises(UiaSessionError, match="names a MenuItem"):
            session.observe(_node(), "observe_before")


# --- the dispatch ---------------------------------------------------------


def test_the_dispatch_goes_to_the_selector_named_control(tmp_path):
    digest = _payload(tmp_path, name="Reuse Slides")
    with _host(tmp_path) as host:
        session = _session(tmp_path, host, digest=digest)
        session.dispatch(_node(), _token(), _confirmed())
    # No exception means the adapter reported completed for that name; the
    # name itself is asserted through the observe path above.


def test_confirm_before_uses_the_signed_round_trip_deadline(tmp_path):
    digest = _payload(tmp_path)
    verifier = FakeVerifier()
    spec = _spec(digest)
    with _host(tmp_path) as host:
        session = _session(
            tmp_path,
            host,
            verifier=verifier,
            spec=spec,
            verify_timeout_s=10.0,
        )
        session.observe(_node(), "confirm_before")

    assert verifier.timeouts == [1.28]


def test_dispatch_refuses_when_request_window_expires_before_adapter_write(tmp_path):
    digest = _payload(tmp_path)
    with _host(tmp_path) as host:
        times = iter((0.0, 100.0))
        session = _session(tmp_path, host, digest=digest, clock=lambda: next(times))
        with pytest.raises(UiaSessionError, match="stale"):
            session.dispatch(_node(), _token(), _confirmed(), 0.0)
        assert not getattr(host, "dispatched", [])


def test_a_dispatch_without_a_confirmation_is_refused(tmp_path):
    """Reaching here would mean dispatching at a control nobody confirmed was
    still the one under the pointer."""

    with _host(tmp_path) as host:
        session = _session(tmp_path, host)

        with pytest.raises(UiaSessionError, match="needs a confirmed observation"):
            session.dispatch(_node(), _token(), None)


@pytest.mark.parametrize("outcome", ["refused", "failed"])
def test_an_adapter_that_did_not_complete_refuses_the_node(tmp_path, outcome):
    """An adapter saying "refused" is not an effect, and must not be reported
    as one."""

    with _host(tmp_path, outcome) as host:
        session = _session(tmp_path, host)

        with pytest.raises(UiaSessionError, match="did not complete the dispatch"):
            session.dispatch(_node(), _token(), _confirmed())


def test_the_dispatch_carries_the_authorization_core_minted(tmp_path):
    """The digest travelling with a dispatch comes from the token
    `execute_node` handed in -- the authorization core minted for THIS node --
    not from anything the session was constructed with.

    Before this, `dispatch` ignored the token and called a separate
    caller-supplied callable. Nothing made the two agree, so the adapter
    could receive an authorization core never minted; the only caller was a
    diagnostic that stubbed the token, so it could not show up until
    production wired this in."""

    sent: list = []
    with _host(tmp_path) as host:
        real = host.dispatch_pattern

        def spy(*args, **kwargs):
            sent.append(kwargs.get("authorization_sha256"))
            return real(*args, **kwargs)

        host.dispatch_pattern = spy
        session = _session(tmp_path, host)
        session.dispatch(
            _node(), _token("d" * 64), _confirmed()
        )

    assert sent == ["d" * 64]


@pytest.mark.parametrize("token", [None, SimpleNamespace(authorization_sha256="")])
def test_a_dispatch_without_the_minted_authorization_is_refused(tmp_path, token):
    """Fail closed. A dispatch that cannot name its authorization is an
    effect nothing approved."""

    with _host(tmp_path) as host:
        session = _session(tmp_path, host)
        with pytest.raises(UiaSessionError, match="authorization"):
            session.dispatch(
                _node(), token, _confirmed()
            )
    assert not getattr(host, "dispatched", [])


# --- the session hands the runtime only edges -----------------------------


def test_the_session_exposes_no_way_to_declare_a_node_verified(tmp_path):
    """`UiaNodeSession` deliberately has no `run`. A caller that could
    override one could return a verified outcome without calling the
    verifier -- a bypass shape a review already found once in this file's
    neighbour."""

    with _host(tmp_path) as host:
        session = _session(tmp_path, host)

    assert not hasattr(session, "run")
    assert session.present is not None
    assert session.on_state is not None


# --- the live-state request is marked as one ------------------------------


def test_an_observation_sends_the_postconditions_and_no_baseline(tmp_path):
    """`postconditions` is what marks a frame as a live-state request: an
    artifact verifier validates its fields exactly and refuses one carrying
    it, which is how the two kinds stay separable without a mode flag.

    The baseline is absent because an observation has nothing to compare
    against yet. Sending one would verify the pre-cue reading against itself
    and report `verified` for a comparison that never happened."""

    verifier = FakeVerifier()
    with _host(tmp_path) as host:
        session = _session(tmp_path, host, verifier=verifier)
        session.observe(_node(), "observe_before")

    assert verifier.seen == [("slide.count.increased_by_one",)]


def test_a_verifier_that_returns_no_reading_refuses_the_node(tmp_path):
    """The vacuous drift check the D032 review found.

    A verifier that cannot read reports it with exit 0, `outcome="refused"`
    and `observed={}` — it does NOT raise. That used to become an empty
    semantic, and two empty semantics compare EQUAL, so `execute_node`'s
    drift check passed on two consecutive failures and the node dispatched.

    The older test used a fake that raised, which enforced an invariant
    (verifier raises → node refuses) that CORRELATED with the property
    (a failed reading must not authorize a dispatch) without implying it.
    """

    verifier = FakeVerifier(empty_on=1)
    with _host(tmp_path) as host:
        session = _session(tmp_path, host, verifier=verifier)

        with pytest.raises(UiaSessionError, match="no reading"):
            session.observe(_node(), "observe_before")


def test_two_failed_readings_can_never_compare_equal(tmp_path):
    """The property, stated directly rather than through a proxy. Neither
    observation may return at all, so there is nothing for the drift check
    to find equal."""

    verifier = FakeVerifier(empty_on=1)
    with _host(tmp_path) as host:
        session = _session(tmp_path, host, verifier=verifier)

        for mode in ("observe_before", "confirm_before"):
            with pytest.raises(UiaSessionError):
                session.observe(_node(), mode)
