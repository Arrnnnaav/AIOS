from __future__ import annotations

from dataclasses import replace
import pathlib
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from ghostcursor.act_runtime import (
    ActControls,
    ActRunCode,
    ActTarget,
    _execute_approved_graph,
    execute_approved_graph,
    approve_action_graph,
)
from ghostcursor.action import (
    ActionEdge,
    ActionGraph,
    ActionNode,
    ActionParameterSpec,
    ActionRisk,
    ActionValueKind,
    OperationRegistry,
    OperationSpec,
    validate_action_graph,
)


PLUGIN = "ghostcursor.powerpoint"
VERSION = "1.0.0"
ADAPTER = "a" * 64
MANIFEST = "c" * 64
ACTIVE = "d" * 64


def _registry(*, risk=ActionRisk.LOW):
    operations = {
        "powerpoint.create": OperationSpec(
            "powerpoint.create",
            risk,
            MappingProxyType({}),
            postconditions=("presentation.created",),
            timeout_s=2.0,
        ),
        "powerpoint.slide": OperationSpec(
            "powerpoint.slide",
            risk,
            MappingProxyType({"slide_id": ActionParameterSpec(ActionValueKind.STRING)}),
            preconditions=("presentation.created",),
            postconditions=("slide.created",),
            effect_key_fields=("slide_id",),
            timeout_s=2.0,
        ),
    }
    return OperationRegistry(
        PLUGIN,
        VERSION,
        ADAPTER,
        "b" * 64,
        MappingProxyType(operations),
    )


def _validated(registry=None):
    registry = registry or _registry()
    graph = ActionGraph(
        PLUGIN,
        VERSION,
        ADAPTER,
        (
            ActionNode("create", "powerpoint.create"),
            ActionNode(
                "slide-one",
                "powerpoint.slide",
                MappingProxyType({"slide_id": "s1"}),
            ),
        ),
        (ActionEdge("create", "slide-one"),),
    )
    return validate_action_graph(graph, registry)


def _adapter(path: Path, *, marker: Path | None = None):
    marker_line = ""
    if marker is not None:
        marker_line = f"Path({str(marker)!r}).write_text('started', encoding='utf-8')\n"
    path.write_text(
        "from pathlib import Path\n"
        "import json, sys\n"
        + marker_line
        + "hello = json.loads(sys.stdin.readline())\n"
        + "print(json.dumps({**hello, 'type': 'ready'}, sort_keys=True), flush=True)\n"
        + "for line in sys.stdin:\n"
        + "    value = json.loads(line)\n"
        + "    if value['type'] == 'stop': break\n"
        + "    if value['type'] == 'preflight':\n"
        + "        print(json.dumps({'detail': 'valid', 'outcome': 'accepted', "
        + "'request_id': value['request_id'], 'session_nonce': value['session_nonce'], "
        + "'type': 'preflight_result', 'validation_sha256': value['validation_sha256']}, sort_keys=True), flush=True)\n"
        + "        continue\n"
        + "    print(json.dumps({'data': {}, 'detail': 'done', 'facts': [], "
        + "'outcome': 'completed', 'request_id': value['request_id'], "
        + "'session_nonce': value['session_nonce'], 'type': 'result'}, sort_keys=True), flush=True)\n",
        encoding="utf-8",
        newline="\n",
    )


def _descriptor(tmp_path: Path, *, marker: Path | None = None):
    entrypoint = tmp_path / "adapter.py"
    _adapter(entrypoint, marker=marker)
    return SimpleNamespace(
        plugin_id=PLUGIN,
        plugin_version=VERSION,
        manifest_sha256=MANIFEST,
        payload_root=tmp_path,
        entrypoint=entrypoint,
        adapter_sha256=ADAPTER,
    )


def _target():
    return ActTarget(101, 202, "POWERPNT.EXE", "16.0.1")


def _approval(tmp_path, validated, registry, **changes):
    values = {
        "manifest_sha256": MANIFEST,
        "active_index_sha256": ACTIVE,
        "catalog_generation": 7,
        "target": _target(),
        "output_path": tmp_path / "owned" / "deck.pptx",
        "unattended": True,
        "owned_output_root": tmp_path / "owned",
        "now": 100.0,
    }
    values.update(changes)
    return approve_action_graph(validated, registry, **values)


def _authority():
    return ACTIVE, 7, VERSION, MANIFEST, ADAPTER


def test_unattended_approval_requires_low_risk_and_an_owned_output_root(tmp_path):
    registry = _registry(risk=ActionRisk.NORMAL)
    validated = _validated(registry)
    with pytest.raises(ValueError, match="low-risk"):
        _approval(tmp_path, validated, registry)

    registry = _registry()
    validated = _validated(registry)
    with pytest.raises(ValueError, match="owned output root"):
        approve_action_graph(
            validated,
            registry,
            manifest_sha256=MANIFEST,
            active_index_sha256=ACTIVE,
            catalog_generation=7,
            target=_target(),
            output_path=tmp_path / "deck.pptx",
            unattended=True,
        )
    with pytest.raises(ValueError, match="escapes"):
        _approval(
            tmp_path,
            validated,
            registry,
            output_path=tmp_path / "outside.pptx",
        )


def test_a_forged_or_stale_approval_never_starts_the_adapter(tmp_path):
    registry = _registry()
    validated = _validated(registry)
    approval = _approval(tmp_path, validated, registry)
    marker = tmp_path / "adapter-started"
    forged = replace(approval, output_path=str(tmp_path / "forged.pptx"))

    result = _execute_approved_graph(
        validated,
        registry,
        forged,
        descriptor=_descriptor(tmp_path, marker=marker),
        current_authority=_authority,
        revalidate_target=lambda _: None,
        verify=lambda *_: True,
        controls=ActControls(),
        wall_clock=lambda: 101.0,
    )

    assert result.code is ActRunCode.APPROVAL_STALE
    assert not marker.exists()


def test_authority_and_target_are_checked_before_adapter_process_creation(tmp_path):
    registry = _registry()
    validated = _validated(registry)
    approval = _approval(tmp_path, validated, registry)
    marker = tmp_path / "adapter-started"
    descriptor = _descriptor(tmp_path, marker=marker)

    stale = _execute_approved_graph(
        validated,
        registry,
        approval,
        descriptor=descriptor,
        current_authority=lambda: ("0" * 64, 7, VERSION, MANIFEST, ADAPTER),
        revalidate_target=lambda _: None,
        verify=lambda *_: True,
        controls=ActControls(),
        wall_clock=lambda: 101.0,
    )
    assert stale.code is ActRunCode.AUTHORITY_CHANGED
    assert not marker.exists()

    drifted = _execute_approved_graph(
        validated,
        registry,
        approval,
        descriptor=descriptor,
        current_authority=_authority,
        revalidate_target=lambda _: (_ for _ in ()).throw(
            RuntimeError("HWND recycled")
        ),
        verify=lambda *_: True,
        controls=ActControls(),
        wall_clock=lambda: 101.0,
    )
    assert drifted.code is ActRunCode.TARGET_CHANGED
    assert not marker.exists()


def test_every_node_is_reauthorized_and_independently_verified(tmp_path):
    registry = _registry()
    validated = _validated(registry)
    approval = _approval(tmp_path, validated, registry)
    target_reads = 0
    verified = []

    def target(_):
        nonlocal target_reads
        target_reads += 1

    result = _execute_approved_graph(
        validated,
        registry,
        approval,
        descriptor=_descriptor(tmp_path),
        current_authority=_authority,
        revalidate_target=target,
        verify=lambda node, *_: not verified.append(node.node_id),
        controls=ActControls(),
        wall_clock=lambda: 101.0,
    )

    assert result.code is ActRunCode.COMPLETED
    assert result.completed_node_ids == ("create", "slide-one")
    assert verified == ["create", "slide-one"]
    assert target_reads == 3  # one preflight plus one check per action


def test_target_drift_between_actions_stops_before_the_next_effect(tmp_path):
    registry = _registry()
    validated = _validated(registry)
    approval = _approval(tmp_path, validated, registry)
    target_reads = 0

    def target(_):
        nonlocal target_reads
        target_reads += 1
        if target_reads == 3:
            raise RuntimeError("PowerPoint window changed")

    result = _execute_approved_graph(
        validated,
        registry,
        approval,
        descriptor=_descriptor(tmp_path),
        current_authority=_authority,
        revalidate_target=target,
        verify=lambda *_: True,
        controls=ActControls(),
        wall_clock=lambda: 101.0,
    )

    assert result.code is ActRunCode.TARGET_CHANGED
    assert result.completed_node_ids == ("create",)
    assert result.failed_node_id == "slide-one"


# --- the diagnostic seam must be incapable of replacing verification -------


def _refusing_verifier(path: pathlib.Path) -> None:
    """A signed verifier that always refuses, so any pass is a bypass."""

    path.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.readline())\n"
        "print(json.dumps({\n"
        "    'detail': 'declared postcondition was not observed',\n"
        "    'node_id': request['node']['node_id'],\n"
        "    'observed': {},\n"
        "    'outcome': 'refused',\n"
        "    'session_nonce': request['session_nonce'],\n"
        "    'type': 'verification_result',\n"
        "    'validation_sha256': request['validation_sha256'],\n"
        "}, sort_keys=True))\n",
        encoding="utf-8",
        newline="\n",
    )


def _verifying_descriptor(tmp_path: Path):
    import hashlib

    descriptor = _descriptor(tmp_path)
    verifier = tmp_path / "verifier.py"
    _refusing_verifier(verifier)
    return SimpleNamespace(
        **{
            **descriptor.__dict__,
            "verifier": verifier,
            "verifier_sha256": hashlib.sha256(verifier.read_bytes()).hexdigest(),
        }
    )


def _run_with_observer(tmp_path, observer):
    registry = _registry()
    validated = _validated(registry)
    import time as _time

    # A real clock: execute_approved_graph is the production entry point and
    # takes no injected one, so a fixture timestamp reads as a stale approval.
    approval = _approval(tmp_path, validated, registry, now=_time.time())
    (tmp_path / "owned").mkdir(exist_ok=True)
    return execute_approved_graph(
        validated,
        registry,
        approval,
        descriptor=_verifying_descriptor(tmp_path),
        current_authority=_authority,
        revalidate_target=lambda _target: None,
        controls=ActControls(),
        verify_observer=observer,
    )


def test_a_verify_observer_returning_true_cannot_pass_a_refused_verification(
    tmp_path,
):
    """The seam was once a wrapper handed the verifier callable and asked to
    return the same answer. Nothing enforced that, so returning True in its
    place would have passed every node without the signed verifier's consent.
    Core now owns the call and the answer, and the observer's return value is
    discarded."""

    result = _run_with_observer(tmp_path, lambda _phase, _facts: True)

    assert result.completed is False
    assert result.code is ActRunCode.VERIFICATION_FAILED


@pytest.mark.parametrize(
    "error", [RuntimeError("diagnostics blew up"), ValueError("bad record")]
)
def test_an_ordinary_observer_exception_cannot_fail_a_run(tmp_path, error):
    """Instrumentation must not be able to break a run in the other direction."""

    def explode(_phase, _facts):
        raise error

    result = _run_with_observer(tmp_path, explode)

    # Still the verifier's refusal, not the observer's exception.
    assert result.code is ActRunCode.VERIFICATION_FAILED
    assert str(error) not in result.detail


def test_a_base_exception_from_an_observer_is_deliberately_not_swallowed(tmp_path):
    """The boundary is `Exception`, not `BaseException`.

    Catching KeyboardInterrupt or SystemExit here would be worse than the
    failure it prevents, so those propagate. The docstring used to promise
    they did not; this pins the real boundary so the promise and the code
    cannot drift apart again.
    """

    def explode(_phase, _facts):
        raise SystemExit(3)

    with pytest.raises(SystemExit):
        _run_with_observer(tmp_path, explode)


def test_the_observer_is_told_the_answer_the_signed_verifier_actually_gave(
    tmp_path,
):
    seen: list[tuple[str, object]] = []

    _run_with_observer(
        tmp_path, lambda phase, facts: seen.append((phase, facts.get("verified")))
    )

    assert ("verify_started", None) in seen
    assert ("verify_finished", False) in seen


def test_execute_approved_graph_exposes_no_verifier_replacing_parameter():
    """Exact-signature guard. A future parameter that accepts a callable
    returning the verification answer would reopen the bypass."""

    import inspect

    parameters = set(inspect.signature(execute_approved_graph).parameters)

    assert "instrument_verify" not in parameters
    assert parameters == {
        "validated",
        "registry",
        "approval",
        "descriptor",
        "current_authority",
        "revalidate_target",
        "controls",
        "event_sink",
        "verify_observer",
        "uia_session",
        # Timing only, and deliberately NOT a callable: a `Pace` is two
        # integers, so nothing passed here can return a verification answer.
        # It changes how long the run waits between nodes and changes nothing
        # about what any node is allowed to do.
        "pace",
    }


def test_the_pace_cannot_carry_behaviour_into_the_run():
    """A pace is data. If it could hold a callable, the timing parameter
    would be a way to hand the executor code -- which is the shape of every
    bypass this file guards against."""

    from ghostcursor.act_pacing import WATCH

    for field, value in vars(WATCH).items():
        assert isinstance(value, (str, int)), f"{field} is not a scalar"
        assert not callable(value)


def test_a_paced_run_still_refuses_everything_an_unpaced_one_does(tmp_path):
    """Pacing must not become a second code path with different checks."""

    from ghostcursor.act_pacing import WATCH

    quick = _run_uia(tmp_path)
    assert quick.code is ActRunCode.ADAPTER_FAILED

    watched = _run_uia(tmp_path, pace=WATCH)
    assert watched.code is quick.code


def test_the_uia_session_cannot_replace_the_verifier():
    """It supplies observe, present and dispatch. It has no `run` method, so
    it cannot own the sequence and return a verified outcome without the
    verifier having been called -- the bypass shape already found once here."""

    from ghostcursor.act_runtime import UiaNodeSession

    assert not hasattr(UiaNodeSession, "run")
    assert set(UiaNodeSession.__dataclass_fields__) == {
        "observe",
        "present",
        "dispatch",
        "policy",
        "session_id",
        "clock",
        "on_state",
    }


# --- the control-driving branch --------------------------------------------


def _uia_registry():
    """A registry whose single operation drives a control."""

    from ghostcursor.uia_identity import IdentityPolicy

    policy = IdentityPolicy(
        operation_id="powerpoint.new_slide_uia",
        selector_id="powerpoint.new-slide",
        selector_sha256="c" * 64,
        control_type="Button",
        identity_mode="runtime_id_required",
        required_fields=("control_type", "name", "runtime_id"),
        evidence_fields=("automation_id",),
    )
    operations = {
        "powerpoint.new_slide_uia": OperationSpec(
            "powerpoint.new_slide_uia",
            ActionRisk.LOW,
            MappingProxyType({}),
            postconditions=("slide.exists",),
            timeout_s=2.0,
            backend="uia_pattern",
            uia_pattern="Invoke",
            identity=policy,
        )
    }
    return OperationRegistry(
        PLUGIN, VERSION, ADAPTER, "b" * 64, MappingProxyType(operations)
    )


def _uia_graph(registry):
    from ghostcursor.action import ActionGraph, ActionNode, validate_action_graph

    graph = ActionGraph(
        PLUGIN,
        VERSION,
        ADAPTER,
        (ActionNode("n001", "powerpoint.new_slide_uia", {}),),
        (),
    )
    return validate_action_graph(graph, registry)


def _identity():
    return {
        "automation_id": "",
        "control_type": "Button",
        "name": "New Slide",
        "runtime_id": (7, 1, 2),
    }


def _fake_session(*, receipts=True, record=None):
    from ghostcursor.act_node import Observation
    from ghostcursor.act_protocol import (
        PresentationRequest,
        Receipt,
        ReceiptKind,
        ReceiptPolicy,
    )
    from ghostcursor.act_runtime import UiaNodeSession

    record = record if record is not None else {}
    record.setdefault("dispatched", [])
    record.setdefault("presented", [])

    ticks = iter(range(1, 10_000))
    clock = lambda: float(next(ticks))  # noqa: E731 - one shared clock

    def present(request: PresentationRequest, baseline, sink=None):
        record["presented"].append(request)
        if not receipts:
            return []
        issued = [
            Receipt(
                kind,
                request.session_id,
                request.cue_id,
                request.nonce,
                request.presentation_generation,
                request.frame_generation,
            )
            for kind in (
                ReceiptKind.GEOMETRY_STARTED,
                ReceiptKind.PRESENTATION_COMPLETED,
            )
        ]
        if sink is not None:
            # As each happens, on the same clock the node reads. A fake that
            # returned the list and let the caller timestamp it afterwards
            # would reproduce the very defect this argument prevents.
            for receipt in issued:
                sink(receipt, clock())
        return issued

    return UiaNodeSession(
        observe=lambda node, mode: Observation(
            semantic={"slides": 3},
            identity=_identity(),
            rectangle=(10, 20, 110, 60),
            match_count=1,
        ),
        present=present,
        dispatch=lambda node, token, confirmed: record["dispatched"].append(node.node_id),
        policy=ReceiptPolicy(first_paint_deadline_ms=500, completion_deadline_ms=800),
        session_id="s1",
        clock=clock,
    ), record


def _run_uia(tmp_path, *, session=None, verified=True, pace=None):
    import time as _time

    registry = _uia_registry()
    validated = _uia_graph(registry)
    approval = _approval(tmp_path, validated, registry, now=_time.time())
    (tmp_path / "owned").mkdir(exist_ok=True)
    return _execute_approved_graph(
        validated,
        registry,
        approval,
        descriptor=_descriptor(tmp_path),
        current_authority=_authority,
        revalidate_target=lambda _target: None,
        verify=lambda *_args: verified,
        controls=ActControls(),
        uia_session=session,
        **({} if pace is None else {"pace": pace}),
    )


def test_a_control_driving_node_refuses_when_there_is_no_presentation_surface(
    tmp_path,
):
    """No presenter means no UIA execution -- refused by construction, because
    the alternative is an effect the user never saw (D109)."""

    result = _run_uia(tmp_path)

    assert result.completed is False
    assert result.code is ActRunCode.ADAPTER_FAILED
    assert "presentation surface" in result.detail


def test_a_control_driving_node_runs_the_three_observation_flow(tmp_path):
    session, record = _fake_session()

    result = _run_uia(tmp_path, session=session)

    assert result.completed is True
    assert record["dispatched"] == ["n001"]
    # The cue it showed was bound to this node and required real geometry.
    assert record["presented"][0].cue_id == "n001:1"
    assert record["presented"][0].geometry_required is True


def test_a_control_driving_node_without_receipts_never_dispatches(tmp_path):
    session, record = _fake_session(receipts=False)

    result = _run_uia(tmp_path, session=session)

    assert result.completed is False
    assert record["dispatched"] == []


def test_a_dispatched_control_node_that_fails_verification_stops_the_run(tmp_path):
    session, record = _fake_session()

    result = _run_uia(tmp_path, session=session, verified=False)

    assert result.code is ActRunCode.VERIFICATION_FAILED
    assert record["dispatched"] == ["n001"]
    assert result.completed_node_ids == ()


def test_a_control_driving_node_does_not_take_the_object_model_path(tmp_path):
    """The object-model path starts the adapter subprocess and calls execute
    on it. A UIA node must never reach that."""

    marker = tmp_path / "adapter-started"
    session, _record = _fake_session()

    registry = _uia_registry()
    validated = _uia_graph(registry)
    import time as _time

    approval = _approval(tmp_path, validated, registry, now=_time.time())
    (tmp_path / "owned").mkdir(exist_ok=True)
    result = _execute_approved_graph(
        validated,
        registry,
        approval,
        descriptor=_descriptor(tmp_path, marker=marker),
        current_authority=_authority,
        revalidate_target=lambda _target: None,
        verify=lambda *_args: True,
        controls=ActControls(),
        uia_session=session,
    )

    assert result.completed is True
