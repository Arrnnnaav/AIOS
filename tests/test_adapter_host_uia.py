"""The host's two UIA calls: reading a control, and dispatching on one.

They exist separately from `execute` because the generic UIA adapter
validates its request fields EXACTLY, and the object-model execute frame
carries five keys that adapter does not accept. A test that used a permissive
fake would prove nothing about that, so the fakes here reject an unexpected
field set the same way the real adapter does.

The property that matters most is the one about `observe_control`: it has no
pattern to send, so it cannot dispatch even if something asked it to.
"""

from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from ghostcursor.adapter_host import (
    AdapterHost,
    AdapterProtocolError,
    UiaObservation,
)
from ghostcursor.coordinate_space import observe_bracketed

#: A fake that mirrors the real adapter's exact-field discipline, and records
#: every frame it was sent so a test can assert what was NOT in it.
SCRIPT = r"""
import json
import sys
from ghostcursor.coordinate_space import observe_bracketed

OBSERVE = {"control_type", "name", "request_id", "session_nonce", "type"}
EXECUTE = {
    "authorization_sha256", "control_type", "expected_identity",
    "expected_coordinate_space", "expected_rectangle", "name", "pattern",
    "request_id", "session_nonce", "type", "value",
}

def emit(value):
    print(json.dumps(value, sort_keys=True, separators=(",", ":")), flush=True)

hello = json.loads(sys.stdin.readline())
emit({**hello, "type": "ready"})
seen = []
for line in sys.stdin:
    request = json.loads(line)
    if request["type"] == "stop":
        break
    seen.append(request)
    try:
        if request["type"] == "observe":
            if set(request) != OBSERVE:
                raise ValueError("observe fields are wrong: " + repr(sorted(request)))
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
        if set(request) != EXECUTE:
            raise ValueError("execute fields are wrong: " + repr(sorted(request)))
        emit({
            "data": {
                "identity": {"name": request["name"]},
                "pattern": request["pattern"],
                "rectangle": [100, 200, 260, 245],
            },
            "detail": "pattern dispatched on the resolved control",
            "facts": [],
            "outcome": "completed",
            "request_id": request["request_id"],
            "session_nonce": request["session_nonce"],
            "type": "result",
        })
    except Exception as exc:
        emit({
            "data": {},
            "detail": "%s: %s" % (type(exc).__name__, exc),
            "facts": [],
            "outcome": "refused",
            "request_id": request.get("request_id", ""),
            "session_nonce": hello["session_nonce"],
            "type": "result",
        })
"""


def _descriptor(tmp_path: Path, source: str = SCRIPT):
    entrypoint = tmp_path / "adapter.py"
    entrypoint.write_text(textwrap.dedent(source), encoding="utf-8", newline="\n")
    return SimpleNamespace(
        plugin_id="ghostcursor.powerpoint",
        plugin_version="1.0.0",
        payload_root=tmp_path,
        entrypoint=entrypoint,
        adapter_sha256=hashlib.sha256(entrypoint.read_bytes()).hexdigest(),
    )


def _host(tmp_path, source: str = SCRIPT):
    return AdapterHost(_descriptor(tmp_path, source), session_nonce="nonce")


def _confirmed():
    geometry = observe_bracketed(lambda: [[100, 200, 260, 245]])
    return {
        "expected_identity": {
            "control_type": "Button",
            "name": "New Slide",
            "runtime_id": [7, 1, 2],
        },
        "expected_rectangle": (100, 200, 260, 245),
        "expected_geometry": geometry,
    }


# --- reading a control ----------------------------------------------------


def test_a_control_can_be_read_without_being_touched(tmp_path):
    with _host(tmp_path) as host:
        observation = host.observe_control("Button", "New Slide", timeout_s=5.0)

    assert isinstance(observation, UiaObservation)
    assert observation.identity["name"] == "New Slide"
    assert observation.rectangle == (100, 200, 260, 245)
    assert observation.geometry.rectangles == ((100, 200, 260, 245),)


def test_the_observe_frame_carries_no_pattern_to_dispatch(tmp_path):
    """The structural claim: this call cannot act, because there is nothing in
    the frame that names an action. A mode flag on `execute` would not have
    that property -- the pattern field would still be there."""

    import inspect

    from ghostcursor.adapter_host import AdapterHost as Host

    source = inspect.getsource(Host.observe_control)

    assert '"pattern"' not in source
    assert '"authorization_sha256"' not in source


def test_an_observe_frame_the_real_adapter_would_refuse_is_not_sent(tmp_path):
    """The fake rejects any field set but the exact one the shipped adapter
    accepts, so this passing means the host builds a frame that adapter
    parses."""

    with _host(tmp_path) as host:
        observation = host.observe_control("Button", "New Slide", timeout_s=5.0)

    assert observation.identity["control_type"] == "Button"


def test_a_refused_observation_names_the_adapter_detail(tmp_path):
    """A field-shape complaint would hide why the adapter said no, and the
    reason is the whole diagnostic value of the refusal."""

    refusing = SCRIPT.replace("if set(request) != OBSERVE:", "if True:").replace(
        '"observe fields are wrong: " + repr(sorted(request))',
        '"no control matched that name"',
    )

    with pytest.raises(AdapterProtocolError, match="no control matched"):
        with _host(tmp_path, refusing) as host:
            host.observe_control("Button", "Nothing", timeout_s=5.0)


@pytest.mark.parametrize(
    "corruption",
    [
        ('"outcome": "observed"', '"outcome": "guessed"'),
        ('"type": "observation"', '"type": "result_like"'),
        ("[100, 200, 260, 245]", "[100, 200, 260]"),
        ("[100, 200, 260, 245]", '["100", 200, 260, 245]'),
        ('"request_id": request["request_id"]', '"request_id": "somethingelse"'),
    ],
)
def test_a_malformed_observation_is_refused_and_tears_the_child_down(
    tmp_path, corruption
):
    """A rectangle the host cannot trust is a pointer position it must not
    draw. Every one of these fails closed rather than reaching the overlay."""

    old, new = corruption
    host = _host(tmp_path, SCRIPT.replace(old, new, 1))
    host.start()
    with pytest.raises(AdapterProtocolError):
        host.observe_control("Button", "New Slide", timeout_s=5.0)

    assert host.running is False


def test_a_boolean_rectangle_coordinate_is_refused(tmp_path):
    """bool is an int subclass, so an isinstance check alone would accept
    True as a screen coordinate."""

    # `True`, not JSON's `true`: the fake is PYTHON source, so a lowercase
    # `true` is a NameError there and the adapter refuses before the host ever
    # sees a rectangle. That version of this test raised for the wrong reason
    # and passed with the bool guard removed.
    host = _host(
        tmp_path, SCRIPT.replace("[100, 200, 260, 245]", "[True, 200, 260, 245]", 1)
    )
    host.start()
    with pytest.raises(AdapterProtocolError, match="must be an integer"):
        host.observe_control("Button", "New Slide", timeout_s=5.0)

    assert host.running is False


def test_a_malformed_coordinate_contract_is_refused(tmp_path):
    source = SCRIPT.replace(
        '"coordinate_space": observe_bracketed(\n'
        '                    lambda: [[100, 200, 260, 245]]\n'
        '                ).as_record(),',
        '"coordinate_space": {"bad": 1},',
        1,
    )
    host = _host(tmp_path, source)
    host.start()

    with pytest.raises(AdapterProtocolError, match="coordinate space is invalid"):
        host.observe_control("Button", "New Slide", timeout_s=5.0)

    assert host.running is False


def test_a_rectangle_outside_its_coordinate_contract_is_refused(tmp_path):
    source = SCRIPT.replace(
        '"rectangle": [100, 200, 260, 245],',
        '"rectangle": [101, 200, 260, 245],',
        1,
    )
    host = _host(tmp_path, source)
    host.start()

    with pytest.raises(AdapterProtocolError, match="disagrees"):
        host.observe_control("Button", "New Slide", timeout_s=5.0)

    assert host.running is False


def test_an_identity_that_is_not_a_mapping_is_refused(tmp_path):
    """Identity is compared field by field by `uia_identity`. A string or a
    list there would compare as something, and what it compared as would not
    be a control."""

    # The VALUE is replaced, not a key added. Adding one changes the field
    # SET, and the shape check fires first -- so that version of this test
    # raised without ever reaching the identity type check.
    identity_block = """                "identity": {
                    "automation_id": "",
                    "control_type": request["control_type"],
                    "name": request["name"],
                    "runtime_id": [7, 1, 2],
                },"""
    assert identity_block in SCRIPT
    host = _host(
        tmp_path,
        SCRIPT.replace(identity_block, '                "identity": "New Slide",', 1),
    )
    host.start()
    with pytest.raises(AdapterProtocolError):
        host.observe_control("Button", "New Slide", timeout_s=5.0)


def test_observing_without_a_running_adapter_is_refused(tmp_path):
    """The guard lives in `_write`, which every request goes through, rather
    than being repeated at each call site where three copies could drift."""

    host = _host(tmp_path)

    with pytest.raises(AdapterProtocolError, match="not running"):
        host.observe_control("Button", "New Slide", timeout_s=5.0)


# --- dispatching on one ---------------------------------------------------


def test_a_pattern_is_dispatched_on_the_named_control(tmp_path):
    with _host(tmp_path) as host:
        response = host.dispatch_pattern(
            "Button",
            "New Slide",
            "Invoke",
            authorization_sha256="a" * 64,
            **_confirmed(),
            timeout_s=5.0,
        )

    assert response.outcome == "completed"
    assert response.data["pattern"] == "Invoke"


def test_the_authorization_digest_travels_with_the_dispatch(tmp_path):
    """The adapter refuses a frame not minted for this node, so the digest
    has to be in the frame rather than remembered from the handshake."""

    echoing = SCRIPT.replace(
        '"pattern": request["pattern"],',
        '"pattern": request["pattern"], "authorization": request["authorization_sha256"],',
        1,
    )

    with _host(tmp_path, echoing) as host:
        response = host.dispatch_pattern(
            "Button",
            "New Slide",
            "Invoke",
            authorization_sha256="b" * 64,
            **_confirmed(),
            timeout_s=5.0,
        )

    assert response.data["authorization"] == "b" * 64


def test_a_dispatch_frame_the_real_adapter_would_refuse_is_not_sent(tmp_path):
    """`value` is required by the adapter's exact-field check even when it is
    null, so omitting it on a pattern that takes no value would refuse every
    Invoke."""

    with _host(tmp_path) as host:
        response = host.dispatch_pattern(
            "Button",
            "New Slide",
            "Invoke",
            authorization_sha256="c" * 64,
            **_confirmed(),
            timeout_s=5.0,
        )

    assert response.outcome == "completed"


def test_a_dispatch_refusal_is_reported_rather_than_raised(tmp_path):
    """A refusal is a run outcome the record has to show. Only a malformed
    frame is a protocol error."""

    refusing = SCRIPT.replace("if set(request) != EXECUTE:", "if True:", 1)

    with _host(tmp_path, refusing) as host:
        response = host.dispatch_pattern(
            "Button",
            "New Slide",
            "Invoke",
            authorization_sha256="d" * 64,
            **_confirmed(),
            timeout_s=5.0,
        )

    assert response.outcome == "refused"


def test_dispatching_without_a_running_adapter_is_refused(tmp_path):
    host = _host(tmp_path)

    with pytest.raises(AdapterProtocolError, match="not running"):
        host.dispatch_pattern(
            "Button",
            "New Slide",
            "Invoke",
            authorization_sha256="e" * 64,
            **_confirmed(),
            timeout_s=5.0,
        )


def test_a_replayed_dispatch_result_is_refused(tmp_path):
    # Every frame, not the first: the first occurrence is the OBSERVATION
    # reply, and replacing only that left the dispatch result correctly
    # bound -- so the test passed while asserting nothing about dispatch.
    host = _host(
        tmp_path,
        SCRIPT.replace('"request_id": request["request_id"],', '"request_id": "stale",'),
    )
    host.start()
    with pytest.raises(AdapterProtocolError, match="invalid or replayed"):
        host.dispatch_pattern(
            "Button",
            "New Slide",
            "Invoke",
            authorization_sha256="f" * 64,
            **_confirmed(),
            timeout_s=5.0,
        )

    assert host.running is False


# --- the shipped adapter agrees with the frames the host builds -----------


def test_the_shipped_adapter_accepts_exactly_the_fields_the_host_sends():
    """Read from the canonical adapter source rather than restated here. If
    the adapter's field set changes, this fails instead of the mismatch
    surfacing only on a live desktop."""

    import inspect

    from ghostcursor.adapter_host import AdapterHost as Host

    adapter = (
        Path(__file__).resolve().parents[1] / "plugins/shared/uia_adapter.py"
    ).read_text(encoding="utf-8")

    observe_block = adapter.split('{"control_type", "name", "request_id"')[1]
    assert observe_block.startswith(', "session_nonce", "type"}')

    sent = inspect.getsource(Host.observe_control)
    for field in ("control_type", "name", "request_id", "session_nonce", "type"):
        assert f'"{field}"' in sent

    dispatched = inspect.getsource(Host.dispatch_pattern)
    for field in (
        "authorization_sha256",
        "control_type",
        "expected_identity",
        "expected_coordinate_space",
        "expected_rectangle",
        "name",
        "pattern",
        "request_id",
        "session_nonce",
        "type",
        "value",
    ):
        assert f'"{field}"' in dispatched
