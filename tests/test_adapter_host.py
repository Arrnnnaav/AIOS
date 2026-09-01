from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from ghostcursor.adapter_host import AdapterHost, AdapterProtocolError, VerifierHost


SCRIPT = r"""
import json
import sys

hello = json.loads(sys.stdin.readline())
print(json.dumps({
    "adapter_sha256": hello["adapter_sha256"],
    "plugin_id": hello["plugin_id"],
    "plugin_version": hello["plugin_version"],
    "protocol_version": hello["protocol_version"],
    "session_nonce": hello["session_nonce"],
    "session_context": hello["session_context"],
    "type": "ready",
}, sort_keys=True, separators=(",", ":")), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request["type"] == "stop":
        break
    if request["type"] == "preflight":
        print(json.dumps({
            "detail": "valid",
            "outcome": "accepted",
            "request_id": request["request_id"],
            "session_nonce": request["session_nonce"],
            "type": "preflight_result",
            "validation_sha256": request["validation_sha256"],
        }, sort_keys=True, separators=(",", ":")), flush=True)
        continue
    print(json.dumps({
        "data": {"seen": request["operation_id"]},
        "detail": "done",
        "facts": ["slide.created"],
        "outcome": "completed",
        "request_id": request["request_id"],
        "session_nonce": request["session_nonce"],
        "type": "result",
    }, sort_keys=True, separators=(",", ":")), flush=True)
"""


def _descriptor(tmp_path: Path, source: str = SCRIPT):
    entrypoint = tmp_path / "adapter.py"
    entrypoint.write_text(textwrap.dedent(source), encoding="utf-8", newline="\n")
    digest = hashlib.sha256(entrypoint.read_bytes()).hexdigest()
    return SimpleNamespace(
        plugin_id="ghostcursor.powerpoint",
        plugin_version="1.0.0",
        payload_root=tmp_path,
        entrypoint=entrypoint,
        adapter_sha256=digest,
    )


def _verifier_descriptor(tmp_path: Path, source: str):
    verifier = tmp_path / "verifier.py"
    verifier.write_text(textwrap.dedent(source), encoding="utf-8", newline="\n")
    return SimpleNamespace(
        plugin_id="ghostcursor.powerpoint",
        plugin_version="1.0.0",
        payload_root=tmp_path,
        verifier=verifier,
        verifier_sha256=hashlib.sha256(verifier.read_bytes()).hexdigest(),
    )


def _node():
    return SimpleNamespace(
        node_id="slide-one",
        operation_id="powerpoint.create_slide",
        parameters={"slide_id": "s1"},
    )


def test_adapter_host_binds_handshake_request_and_response_to_one_nonce(tmp_path):
    descriptor = _descriptor(tmp_path)
    with AdapterHost(descriptor, session_nonce="nonce") as host:
        host.preflight(
            [
                SimpleNamespace(
                    node_id="slide-one",
                    operation_id="powerpoint.create_slide",
                    parameters={"slide_id": "s1"},
                )
            ],
            validation_sha256="v" * 64,
        )
        response = host.execute(
            "powerpoint.create_slide",
            {"slide_id": "s1"},
            node_id="slide-one",
            ordinal=1,
            authorization_sha256="a" * 64,
            validation_sha256="v" * 64,
            timeout_s=2.0,
        )

    assert response.outcome == "completed"
    assert response.facts == ("slide.created",)
    assert response.data == {"seen": "powerpoint.create_slide"}
    assert not host.running


def test_adapter_wrong_handshake_fails_closed_and_is_torn_down(tmp_path):
    source = (
        "import json,sys\njson.loads(sys.stdin.readline())\nprint('{}', flush=True)\n"
    )
    descriptor = _descriptor(tmp_path, source)
    host = AdapterHost(descriptor, session_nonce="nonce")

    with pytest.raises(AdapterProtocolError, match="handshake"):
        host.start(timeout_s=1.0)

    assert not host.running


def test_adapter_timeout_terminates_the_child(tmp_path):
    source = r"""
import json,sys,time
hello=json.loads(sys.stdin.readline())
print(json.dumps({"adapter_sha256":hello["adapter_sha256"],"plugin_id":hello["plugin_id"],"plugin_version":hello["plugin_version"],"protocol_version":1,"session_nonce":hello["session_nonce"],"session_context":hello["session_context"],"type":"ready"},sort_keys=True,separators=(",",":")),flush=True)
json.loads(sys.stdin.readline())
time.sleep(10)
"""
    descriptor = _descriptor(tmp_path, source)
    host = AdapterHost(descriptor, session_nonce="nonce").start()

    with pytest.raises(AdapterProtocolError, match="timed out"):
        host.execute(
            "powerpoint.create_slide",
            {},
            node_id="slide-one",
            ordinal=1,
            authorization_sha256="a" * 64,
            validation_sha256="v" * 64,
            timeout_s=0.1,
        )

    assert not host.running


def test_verifier_response_is_bound_to_the_fresh_nonce_and_node(tmp_path):
    descriptor = _verifier_descriptor(
        tmp_path,
        r"""
import json,sys
request=json.loads(sys.stdin.read())
print(json.dumps({
    "detail":"replayed",
    "node_id":"a-different-node",
    "observed":{},
    "outcome":"verified",
    "session_nonce":request["session_nonce"],
    "type":"verification_result",
    "validation_sha256":request["validation_sha256"],
},sort_keys=True,separators=(",",":")))
""",
    )

    with pytest.raises(AdapterProtocolError, match="invalid or replayed"):
        VerifierHost(descriptor).verify(
            node=_node(),
            validation_sha256="v" * 64,
            output_path=str(tmp_path / "deck.pptx"),
            target={"hwnd": 101},
        )


def test_verifier_timeout_terminates_the_one_shot_process(tmp_path):
    descriptor = _verifier_descriptor(
        tmp_path,
        "import sys,time\nsys.stdin.read()\ntime.sleep(10)\n",
    )

    with pytest.raises(AdapterProtocolError, match="verifier timed out"):
        VerifierHost(descriptor).verify(
            node=_node(),
            validation_sha256="v" * 64,
            output_path=str(tmp_path / "deck.pptx"),
            target={"hwnd": 101},
            timeout_s=0.1,
        )
