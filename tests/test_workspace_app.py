"""The workspace app (D178): the local page's trust boundary and its actions."""

from __future__ import annotations

import http.client
import json
import threading

import pytest

from ghostcursor.workspace.app import App, make_server
from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.session import Workspace


class Gateway:
    def complete(self, envelope, system, schema, parse, **kw):
        return parse(json.dumps({"reply": "Sure.", "memories": []}))

    def plan(self, envelope, **kw):
        from ghostcursor.providers.schemas import parse_teach_plan

        return parse_teach_plan(
            json.dumps(
                {
                    "steps": [
                        {
                            "instruction": "Open the Design tab",
                            "expected_change": "chosen_state_changes",
                        }
                    ]
                }
            )
        )


@pytest.fixture
def served(tmp_path):
    app = App(
        "trip",
        make_workspace=lambda: Workspace(
            "trip", Gateway(), Brain(tmp_path / "kb.sqlite"), root=tmp_path / "briefs"
        ),
    )
    server = make_server(app, "secret-token")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield app, server.server_port
    server.shutdown()
    app.close()


def call(
    port,
    path,
    body=None,
    *,
    token="secret-token",
    host=None,
    kind="application/json",
    method="POST",
):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Host": host or f"127.0.0.1:{port}"}
    if method == "POST":
        headers |= {"X-Orbyn-Token": token, "Content-Type": kind}
    data = json.dumps(body or {}).encode() if method == "POST" else None
    conn.request(method, path, body=data, headers=headers)
    resp = conn.getresponse()
    payload = resp.read()
    conn.close()
    return resp.status, payload


def test_page_needs_the_token_and_carries_it(served):
    _, port = served
    assert call(port, "/", method="GET")[0] == 404
    assert call(port, "/?t=wrong", method="GET")[0] == 404
    status, page = call(port, "/?t=secret-token", method="GET")
    assert status == 200 and b'"secret-token"' in page and b"__TOKEN__" not in page


@pytest.mark.parametrize(
    "kw",
    [
        {"token": "wrong"},
        {"token": ""},
        {"host": "evil.example:80"},  # DNS rebinding
        {"host": "localhost:1"},
        {"kind": "text/plain"},  # a cross-site form or simple request
    ],
)
def test_api_refuses_requests_that_are_not_the_page(served, kw):
    _, port = served
    assert call(port, "/api/state", **kw)[0] == 403


def test_discuss_plan_and_edit_reach_the_brief(served):
    app, port = served
    status, body = call(port, "/api/say", {"text": "Make my slides look modern"})
    assert status == 200 and json.loads(body)["reply"] == "Sure."
    assert call(port, "/api/plan")[0] == 200
    assert (
        call(port, "/api/plan_edit", {"verb": "add", "args": ["Pick a theme"]})[0]
        == 200
    )
    state = json.loads(call(port, "/api/state")[1])
    assert state["goal"] == "Make my slides look modern"
    assert state["plan"] == {
        "revision": 2,
        "steps": ["Open the Design tab", "Pick a theme"],
    }
    assert [t["speaker"] for t in state["turns"]][:2] == ["user", "assistant"]


def test_act_is_refused_and_unknown_actions_fail(served):
    _, port = served
    status, body = call(port, "/api/act")
    assert status == 400 and "signed plugin path" in json.loads(body)["error"]
    assert call(port, "/api/nope")[0] == 400


def test_a_busy_workspace_refuses_new_work_but_takes_signals(served):
    app, port = served
    app.busy = "Guiding"
    assert call(port, "/api/say", {"text": "hi"})[0] == 400
    assert call(port, "/api/signal")[0] == 200 and app.signal.is_set()
    assert call(port, "/api/stop")[0] == 200 and app.stop.is_set()
    app.busy = ""


def test_the_page_names_windows_by_number_only(served):
    app, port = served

    class W:
        def __init__(self, hwnd, title):
            self.hwnd, self.executable, self.title = hwnd, "POWERPNT.EXE", title

    app.windows = [W(4242, "Deck"), W(77, "Other")]
    assert app.hwnds([1]) == [77]
    with pytest.raises(ValueError):
        app.hwnds([5, -1, "0"])


def test_brain_erase_needs_confirmation(served):
    app, port = served
    assert call(port, "/api/brain", {"verb": "erase"})[0] == 400
    assert call(port, "/api/brain", {"verb": "erase", "confirm": "yes"})[0] == 200


def test_a_second_job_is_refused_while_one_holds_the_worker(served):
    app, port = served
    app._claim.acquire()
    try:
        status, body = call(port, "/api/say", {"text": "hi"})
        assert status == 400 and "busy" in json.loads(body)["error"]
    finally:
        app._claim.release()
    assert call(port, "/api/say", {"text": "hi"})[0] == 200


def test_a_malformed_length_is_refused(served):
    _, port = served
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.putrequest("POST", "/api/state", skip_host=True)
    for k, v in {
        "Host": f"127.0.0.1:{port}",
        "X-Orbyn-Token": "secret-token",
        "Content-Type": "application/json",
        "Content-Length": "abc",
    }.items():
        conn.putheader(k, v)
    conn.endheaders()
    assert conn.getresponse().status == 403
    conn.close()
