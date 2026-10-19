"""The workspace app (D178): the local page's trust boundary and its actions."""

from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

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


def test_act_needs_a_plan_and_unknown_actions_fail(served):
    _, port = served
    status, body = call(port, "/api/act", {"step": 1, "windows": [0]})
    assert status == 400  # no plan / no window: nothing acts
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


def test_the_picture_switch_is_the_users_and_starts_off(served):
    _, port = served
    assert json.loads(call(port, "/api/state")[1])["vision"] is False
    assert call(port, "/api/vision", {"on": True})[0] == 200
    assert json.loads(call(port, "/api/state")[1])["vision"] is True
    assert call(port, "/api/vision", {"on": "yes"})[0] == 200
    assert json.loads(call(port, "/api/state")[1])["vision"] is False


def test_ideate_then_plan_the_chosen_approach(tmp_path):
    from tests.test_workspace_ideate import IdeaGateway

    app = App(
        "trip",
        make_workspace=lambda: Workspace(
            "trip", IdeaGateway(), Brain(tmp_path / "kb.sqlite"), root=tmp_path / "b"
        ),
    )
    app.handle("say", {"text": "Plan a trip deck"})
    app.handle("ideate", {})
    state = app.state()
    assert [i["title"] for i in state["ideas"]] == ["Reuse last deck", "Fresh template"]
    app.handle("plan", {"idea": 2})
    assert app.state()["plan"]["revision"] == 1 and app.state()["plan_memories"] == []
    with pytest.raises(ValueError):
        app.handle("plan", {"idea": 9})
    app.close()


def test_company_brain_review_panel_actions(tmp_path):
    """The GUI Brain actions: list, review/approve/retire, conflicts -- the
    same owner-governed lifecycle as the console, over HTTP."""

    from ghostcursor.workspace.knowledge import Knowledge

    kb = Knowledge(tmp_path / "know.sqlite")
    app = App(
        "trip",
        make_workspace=lambda: Workspace(
            "trip",
            Gateway(),
            Brain(tmp_path / "kb.sqlite"),
            root=tmp_path / "briefs",
            knowledge=kb,
            kb_scope="default",
        ),
    )
    server = make_server(app, "secret-token")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_port
        a = kb.add_candidate("DB is encrypted at rest.", source="s", scope="default")
        b = kb.add_candidate(
            "DB is not encrypted at rest.", source="t", scope="default"
        )

        facts = json.loads(call(port, "/api/know_list")[1])["facts"]
        assert {f["status"] for f in facts} == {"candidate"}  # nothing usable yet

        status, body = call(port, "/api/know_review", {"fid": a.fid})
        assert status == 200 and json.loads(body)["status"] == "reviewed"
        call(port, "/api/know_review", {"fid": b.fid})
        call(port, "/api/know_approve", {"fid": a.fid})

        conflicts = json.loads(call(port, "/api/know_conflicts")[1])["conflicts"]
        assert len(conflicts) == 1
        assert {conflicts[0]["a"]["fid"], conflicts[0]["b"]["fid"]} == {a.fid, b.fid}

        call(port, "/api/know_retire", {"fid": b.fid})
        states = {
            f["fid"]: f["status"]
            for f in json.loads(call(port, "/api/know_list")[1])["facts"]
        }
        assert states[a.fid] == "approved" and states[b.fid] == "retired"
        # Retiring one side clears the conflict -- the inline Retire loop closes.
        assert json.loads(call(port, "/api/know_conflicts")[1])["conflicts"] == []
        assert call(port, "/api/know_review", {"fid": 999})[0] == 400  # no such fact
    finally:
        server.shutdown()
        app.close()
        kb.close()


def test_company_brain_gui_capture(tmp_path, monkeypatch):
    """GUI capture (D186): a typed note and the clipboard both land as
    candidates over HTTP -- not usable until the owner reviews them."""

    from ghostcursor.workspace.knowledge import Knowledge
    from ghostcursor.harness import act

    monkeypatch.setattr(
        act, "get_clipboard_text", lambda: "captured from the clipboard"
    )
    kb = Knowledge(tmp_path / "know.sqlite")
    app = App(
        "trip",
        make_workspace=lambda: Workspace(
            "trip",
            Gateway(),
            Brain(tmp_path / "kb.sqlite"),
            root=tmp_path / "briefs",
            knowledge=kb,
            kb_scope="default",
        ),
    )
    server = make_server(app, "secret-token")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_port
        status, body = call(
            port, "/api/know_add", {"text": "Launch is in Q3", "source": "note"}
        )
        assert status == 200 and json.loads(body)["status"] == "candidate"
        assert call(port, "/api/know_add", {"text": "   "})[0] == 400  # empty refused

        status, body = call(port, "/api/know_clip", {})
        assert status == 200 and "candidate" in json.loads(body)["result"]

        facts = json.loads(call(port, "/api/know_list")[1])["facts"]
        assert len(facts) == 2 and {f["status"] for f in facts} == {"candidate"}
    finally:
        server.shutdown()
        app.close()
        kb.close()


def test_doctor_action_reports_every_capability(served):
    """Readiness over HTTP (D186): a list of named checks, each with a bool and
    a hint, so the GUI card can show what is on and how to turn on the rest."""

    _, port = served
    status, body = call(port, "/api/doctor", {})
    assert status == 200
    checks = json.loads(body)["checks"]
    assert checks and all(
        set(c) == {"name", "ready", "hint"} and isinstance(c["ready"], bool)
        for c in checks
    )
    assert any("models" in c["name"] for c in checks)


def test_know_aging_and_verify_over_http(tmp_path):
    """Aging surfacing in the GUI (D186): the panel lists usable facts nobody
    re-verified within the window, and the Verify button clears one."""
    from ghostcursor.workspace.knowledge import Knowledge, STALE_AFTER_S

    kb = Knowledge(tmp_path / "know.sqlite")
    kb.now = 1000.0
    kb.clock = lambda: kb.now
    app = App(
        "trip",
        make_workspace=lambda: Workspace(
            "trip",
            Gateway(),
            Brain(tmp_path / "kb.sqlite"),
            root=tmp_path / "briefs",
            knowledge=kb,
            kb_scope="default",
        ),
    )
    f = kb.add_candidate("Office VPN is 10.0.0.1.", source="net", scope="default")
    kb.approve(f.fid)
    kb.now = 1000.0 + STALE_AFTER_S + 1
    server = make_server(app, "secret-token")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_port
        aging = json.loads(call(port, "/api/know_aging", {})[1])["aging"]
        assert [a["fid"] for a in aging] == [f.fid]
        assert call(port, "/api/know_verify", {"fid": f.fid})[0] == 200
        assert json.loads(call(port, "/api/know_aging", {})[1])["aging"] == []
    finally:
        server.shutdown()
        app.close()
        kb.close()


def test_know_export_writes_markdown(tmp_path):
    """GUI Brain export (D186): writes a readable Markdown file and returns its
    path, mirroring the console /know export-md."""
    from ghostcursor.workspace.knowledge import Knowledge

    kb = Knowledge(tmp_path / "know.sqlite")
    app = App(
        "trip",
        make_workspace=lambda: Workspace(
            "trip",
            Gateway(),
            Brain(tmp_path / "kb.sqlite"),
            root=tmp_path / "briefs",
            knowledge=kb,
            kb_scope="default",
        ),
    )
    app.downloads = tmp_path / "dl"
    f = kb.add_candidate("Launch is in Q3.", source="plan", scope="default")
    kb.approve(f.fid)
    server = make_server(app, "secret-token")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, body = call(server.server_port, "/api/know_export", {})
        assert status == 200
        out = Path(json.loads(body)["path"])
        assert out.exists() and "Launch is in Q3." in out.read_text(encoding="utf-8")
    finally:
        server.shutdown()
        app.close()
        kb.close()


def test_know_expire_over_http(tmp_path):
    """GUI Expire button (D186): posting know_expire ends a usable fact now, so
    it drops from recall but survives as history -- the temporal counterpart to
    Retire, driven from the panel."""
    from ghostcursor.workspace.knowledge import Knowledge

    kb = Knowledge(tmp_path / "know.sqlite")
    kb.now = 1000.0
    kb.clock = lambda: kb.now
    app = App(
        "trip",
        make_workspace=lambda: Workspace(
            "trip",
            Gateway(),
            Brain(tmp_path / "kb.sqlite"),
            root=tmp_path / "briefs",
            knowledge=kb,
            kb_scope="default",
        ),
    )
    f = kb.add_candidate("Office VPN is 10.0.0.1.", source="net", scope="default")
    kb.approve(f.fid)
    server = make_server(app, "secret-token")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_port
        assert [h.fid for h in kb.recall("vpn", "default")] == [f.fid]
        assert call(port, "/api/know_expire", {"fid": f.fid})[0] == 200
        assert kb.recall("vpn", "default") == []  # expired, not recalled
        assert kb.get(f.fid) is not None  # kept as history
        listed = json.loads(call(port, "/api/know_list", {})[1])["facts"]
        assert [x["expired"] for x in listed if x["fid"] == f.fid] == [True]  # tagged
    finally:
        server.shutdown()
        app.close()
        kb.close()


def test_know_edges_review_and_expire_over_http(tmp_path):
    """GUI relationships panel (D186): know_edges lists every edge; a candidate
    can be reviewed and a reviewed one expired, from the panel."""
    from ghostcursor.workspace.knowledge import Knowledge

    kb = Knowledge(tmp_path / "know.sqlite")
    kb.now = 1000.0
    kb.clock = lambda: kb.now
    app = App(
        "trip",
        make_workspace=lambda: Workspace(
            "trip",
            Gateway(),
            Brain(tmp_path / "kb.sqlite"),
            root=tmp_path / "briefs",
            knowledge=kb,
            kb_scope="default",
        ),
    )
    e = kb.relate("Acme", "uses", "PG", source="doc", scope="default")  # candidate
    server = make_server(app, "secret-token")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_port
        edges = json.loads(call(port, "/api/know_edges", {})[1])["edges"]
        assert [x["status"] for x in edges] == ["candidate"]
        assert call(port, "/api/know_review_edge", {"eid": e.eid})[0] == 200
        assert kb.edge(e.eid).status == "reviewed"
        assert call(port, "/api/know_expire_edge", {"eid": e.eid})[0] == 200
        assert kb.related("Acme", "default") == []  # expired, not traversed
        edges = json.loads(call(port, "/api/know_edges", {})[1])["edges"]
        assert [x["expired"] for x in edges] == [True]
        assert call(port, "/api/know_review_edge", {"eid": 99})[0] >= 400  # no edge
    finally:
        server.shutdown()
        app.close()
        kb.close()


def test_know_relate_adds_a_candidate_edge_over_http(tmp_path):
    """GUI add-relationship form (D186): know_relate creates a candidate edge;
    missing a part is rejected."""
    from ghostcursor.workspace.knowledge import Knowledge

    kb = Knowledge(tmp_path / "know.sqlite")
    app = App(
        "trip",
        make_workspace=lambda: Workspace(
            "trip",
            Gateway(),
            Brain(tmp_path / "kb.sqlite"),
            root=tmp_path / "briefs",
            knowledge=kb,
            kb_scope="default",
        ),
    )
    server = make_server(app, "secret-token")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_port
        body = json.loads(
            call(
                port,
                "/api/know_relate",
                {"subject": "Acme", "predicate": "uses", "object": "PG"},
            )[1]
        )
        assert body["status"] == "candidate"
        e = kb.edge(body["eid"])
        assert (e.subject, e.predicate, e.object) == ("Acme", "uses", "PG")
        assert call(port, "/api/know_relate", {"subject": "A", "object": "B"})[0] >= 400
    finally:
        server.shutdown()
        app.close()
        kb.close()


def test_know_classify_marks_a_fact_and_edge_sensitive_over_http(tmp_path):
    """GUI Private/Unmark button (D186): know_classify[_edge] flips the
    sensitivity flag; sensitive rows leave the model path, unmark restores."""
    from ghostcursor.workspace.knowledge import Knowledge

    kb = Knowledge(tmp_path / "know.sqlite")
    app = App(
        "trip",
        make_workspace=lambda: Workspace(
            "trip",
            Gateway(),
            Brain(tmp_path / "kb.sqlite"),
            root=tmp_path / "briefs",
            knowledge=kb,
            kb_scope="default",
        ),
    )
    f = kb.add_candidate("wifi password is hunter2", source="s", scope="default")
    kb.approve(f.fid)
    e = kb.relate("Acme", "uses", "PG", source="doc", scope="default")
    kb.review_edge(e.eid)
    server = make_server(app, "secret-token")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_port
        body = json.loads(
            call(port, "/api/know_classify", {"fid": f.fid, "sensitive": True})[1]
        )
        assert body["sensitive"] is True
        assert kb.recall("password", "default") == []  # off the model path now
        call(port, "/api/know_classify_edge", {"eid": e.eid, "sensitive": True})
        assert kb.related("Acme", "default") == []
        facts = json.loads(call(port, "/api/know_list", {})[1])["facts"]
        assert facts[0]["sensitive"] is True  # panel shows the flag
        call(port, "/api/know_classify", {"fid": f.fid, "sensitive": False})  # unmark
        assert kb.recall("password", "default")  # back on the path
        assert (
            call(port, "/api/know_classify", {"fid": 99, "sensitive": True})[0] >= 400
        )
    finally:
        server.shutdown()
        app.close()
        kb.close()
