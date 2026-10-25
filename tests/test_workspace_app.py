"""The workspace app (D178): the local page's trust boundary and its actions."""

from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

import pytest

from ghostcursor.workspace import app as appmod
from ghostcursor.workspace.app import App, make_server

_ = appmod  # used by the single-instance guard test below
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


def test_ensure_ollama_starts_it_only_when_installed_and_down(monkeypatch):
    import socket

    calls = []
    monkeypatch.setattr(appmod.subprocess, "Popen", lambda *a, **k: calls.append(a[0]))

    # already serving -> never spawn
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    monkeypatch.setattr(
        appmod.socket,
        "create_connection",
        lambda *a, **k: srv,  # pretend 11434 is up
    )
    appmod._ensure_ollama()
    assert calls == []
    srv.close()

    # down, and not installed -> never spawn
    def _refuse(*a, **k):
        raise OSError

    monkeypatch.setattr(appmod.socket, "create_connection", _refuse)
    monkeypatch.setattr(appmod.shutil, "which", lambda name: None)
    appmod._ensure_ollama()
    assert calls == []

    # down, and installed -> spawn `ollama serve`
    monkeypatch.setattr(appmod.shutil, "which", lambda name: r"C:\ollama.exe")
    appmod._ensure_ollama()
    assert calls and calls[-1][0].endswith("ollama.exe") and calls[-1][1] == "serve"


def test_version_and_help_flags_do_not_start_a_server(capsys):
    import ghostcursor

    assert appmod.main(["--version"]) == 0
    assert ghostcursor.__version__ in capsys.readouterr().out
    assert appmod.main(["-h"]) == 0  # help prints, no server


def test_window_launch_supports_floating_and_docked_geometry(tmp_path, monkeypatch):
    import win32api
    import win32gui

    edge = tmp_path / "msedge.exe"
    edge.touch()
    launches = []
    moves = []
    monkeypatch.setattr(appmod, "EDGE", edge)
    monkeypatch.setattr(win32api, "GetSystemMetrics", lambda axis: (1920, 1080)[axis])
    monkeypatch.setattr(appmod.subprocess, "Popen", lambda args: launches.append(args))
    windows = iter(({5}, {5, 6}, {5, 6}, {5, 6, 7}))
    monkeypatch.setattr(appmod, "_edge_app_windows", lambda: next(windows))
    monkeypatch.setattr(win32gui, "MoveWindow", lambda *args: moves.append(args))

    appmod.open_window("http://127.0.0.1:1/?t=test")
    assert "--window-size=640,720" in launches[-1]
    assert "--window-position=640,90" in launches[-1]
    assert moves[-1] == (6, 640, 90, 640, 720, True)

    appmod.open_window("http://127.0.0.1:1/?t=test", docked=True)
    assert "--window-size=460,860" in launches[-1]
    assert "--window-position=1444,24" in launches[-1]
    assert moves[-1] == (7, 1444, 24, 460, 860, True)


def test_single_instance_guard_detects_a_live_instance_only(tmp_path, monkeypatch):
    """Double-clicking Orbyn while it runs must re-open its window, not start a
    second server behind a locked Edge profile (which showed nothing). The guard
    reports a live instance only when its port actually accepts a connection."""

    import socket

    lock = tmp_path / "app.lock"
    monkeypatch.setattr(appmod, "_lock_path", lambda: lock)

    assert appmod._live_instance_url() is None  # no lock yet
    lock.write_text("http://127.0.0.1:1/?t=x", encoding="utf-8")  # nobody on port 1
    assert appmod._live_instance_url() is None  # stale lock -> fresh start

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        url = f"http://127.0.0.1:{port}/?t=tok"
        lock.write_text(url, encoding="utf-8")
        assert appmod._live_instance_url() == url  # live -> re-open this one
    finally:
        srv.close()

    appmod._write_lock("http://127.0.0.1:9/?t=z")
    assert lock.read_text(encoding="utf-8").startswith("http://127.0.0.1:")
    appmod._clear_lock()
    assert not lock.exists()


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


def test_recent_work_persists_only_generic_labels_and_recovers_interrupted(tmp_path):
    root = tmp_path / "briefs"

    def make_workspace():
        return Workspace("trip", Gateway(), Brain(tmp_path / "kb.sqlite"), root=root)

    app = App("trip", make_workspace=make_workspace)
    try:
        assert app.run("Researching", lambda: "answer") == "answer"
        assert app.run("private goal text", lambda: None) is None

        def fail():
            raise ValueError("private error text")

        with pytest.raises(ValueError):
            app.run("Planning", fail)
        assert [(r["label"], r["state"]) for r in app.state()["activity"]] == [
            ("Planning", "failed"), ("Work", "finished"), ("Researching", "finished")
        ]
    finally:
        app.close()

    path = root / "trip.activity.json"
    assert "private" not in path.read_text(encoding="utf-8")
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows.append({"label": "Guiding", "state": "running"})
    path.write_text(json.dumps(rows), encoding="utf-8")
    reopened = App("trip", make_workspace=make_workspace)
    try:
        assert reopened.state()["activity"][0] == {
            "label": "Guiding", "state": "interrupted"
        }
    finally:
        reopened.close()


def test_file_question_is_one_off_and_keeps_material_out_of_history(served):
    app, port = served
    status, payload = call(
        port, "/api/ask_file", {"text": "Where?", "material": "Private file: east"}
    )
    assert status == 200
    assert json.loads(payload) == {"answer": "Sure."}
    assert app.ws.turns == ()
    saved = app.activity_path.read_text(encoding="utf-8")
    assert "Private file" not in saved and "Where?" not in saved
    assert json.loads(saved)[-1] == {"label": "Asking file", "state": "finished"}

    for material in (["wrong type"], "x" * 8001, "\0binary"):
        status, _ = call(port, "/api/ask_file", {"text": "Where?", "material": material})
        assert status == 400
    status, _ = call(port, "/api/ask_file", {"text": ["wrong type"], "material": "text"})
    assert status == 400


def test_stop_reaches_file_question_provider_in_order(tmp_path):
    seen = []

    class StopGateway(Gateway):
        def complete(self, envelope, system, schema, parse, **kw):
            seen.append(kw["cancelled"]())
            app.handle("stop", {})
            seen.append(kw["cancelled"]())
            return super().complete(envelope, system, schema, parse, **kw)

    app = App(
        "trip",
        make_workspace=lambda: Workspace(
            "trip", StopGateway(), Brain(tmp_path / "kb.sqlite"), root=tmp_path / "briefs"
        ),
    )
    try:
        assert app.handle("ask_file", {"text": "Where?", "material": "a file"}) == {
            "answer": "Sure."
        }
        assert seen == [False, True]
        assert app.activity[-1] == {"label": "Asking file", "state": "stopped"}
    finally:
        app.close()


def test_invalid_recent_work_file_is_not_overwritten(tmp_path):
    root = tmp_path / "briefs"
    root.mkdir()
    path = root / "trip.activity.json"
    path.write_text('{"not": "a list"}', encoding="utf-8")
    app = App(
        "trip",
        make_workspace=lambda: Workspace(
            "trip", Gateway(), Brain(tmp_path / "kb.sqlite"), root=root
        ),
    )
    try:
        app.run("Researching", lambda: None)
        assert app.state()["activity"][0]["state"] == "finished"
        assert path.read_text(encoding="utf-8") == '{"not": "a list"}'
    finally:
        app.close()


def test_recent_work_save_does_not_overwrite_neighboring_files(tmp_path):
    root = tmp_path / "briefs"
    root.mkdir()
    neighbors = [root / "trip.tmp", root / "trip.activity.tmp", root / "trip.activity.json.tmp"]
    for path in neighbors:
        path.write_text("keep", encoding="utf-8")
    app = App(
        "trip",
        make_workspace=lambda: Workspace(
            "trip", Gateway(), Brain(tmp_path / "kb.sqlite"), root=root
        ),
    )
    try:
        app.run("Researching", lambda: None)
        assert all(path.read_text(encoding="utf-8") == "keep" for path in neighbors)
    finally:
        app.close()


def test_deeply_nested_recent_work_file_does_not_block_startup(tmp_path):
    root = tmp_path / "briefs"
    root.mkdir()
    path = root / "trip.activity.json"
    text = "[" * 20000 + "]" * 20000
    path.write_text(text, encoding="utf-8")
    app = App(
        "trip",
        make_workspace=lambda: Workspace(
            "trip", Gateway(), Brain(tmp_path / "kb.sqlite"), root=root
        ),
    )
    try:
        assert app.state()["activity"] == []
        assert path.read_text(encoding="utf-8") == text
    finally:
        app.close()


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
        assert e.sensitivity == "normal"  # unticked box -> normal
        sb = json.loads(
            call(
                port,
                "/api/know_relate",
                {
                    "subject": "Root",
                    "predicate": "pw",
                    "object": "x",
                    "sensitive": True,
                },
            )[1]
        )
        assert kb.edge(sb["eid"]).sensitivity == "sensitive"  # private checkbox honored
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


def test_know_private_source_over_http(tmp_path):
    """GUI private-source control (D186 FOLLOWUP #1): registering a source makes
    new knowledge from it sensitive at entry; listing and removal round-trip."""
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
            call(port, "/api/know_private_source", {"pattern": "1Password"})[1]
        )
        assert body["patterns"] == ["1Password"]
        # a fact ingested from a matching source is sensitive without marking
        f = kb.add_candidate("vault unlock", source="1Password app", scope="default")
        assert f.sensitivity == "sensitive"
        # listing (no pattern) just returns the set
        assert json.loads(call(port, "/api/know_private_source", {})[1])[
            "patterns"
        ] == ["1Password"]
        # removal round-trips
        gone = json.loads(
            call(
                port,
                "/api/know_private_source",
                {"pattern": "1Password", "remove": True},
            )[1]
        )
        assert gone["patterns"] == []
    finally:
        server.shutdown()
        app.close()
        kb.close()
