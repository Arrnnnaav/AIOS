"""The workspace app (D178): the local page's trust boundary and its actions."""

from __future__ import annotations

import http.client
import json
import threading
import time
from concurrent.futures import CancelledError
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


def test_frozen_ollama_launch_does_not_export_bundle_dll_path(monkeypatch):
    import ctypes

    events = []
    monkeypatch.setattr(appmod.socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(appmod.shutil, "which", lambda name: r"C:\ollama.exe")
    monkeypatch.setattr(appmod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(appmod.sys, "_MEIPASS", r"C:\bundle\_internal", raising=False)
    monkeypatch.setattr(ctypes.windll.kernel32, "SetDllDirectoryW", lambda path: events.append(path))
    monkeypatch.setattr(appmod.subprocess, "Popen", lambda *a, **kw: events.append("spawn"))

    appmod._ensure_ollama()
    assert events == [None, "spawn", r"C:\bundle\_internal"]


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

    monkeypatch.setattr(appmod, "_edge_app_windows", lambda: {5} if not launches or len(launches) == 2 else {5, 8, 9})
    appmod.open_window("http://127.0.0.1:1/?t=test")
    assert len(moves) == 2  # two concurrent new windows: move neither


def test_second_default_launch_keeps_existing_island_instead_of_opening_full_window(monkeypatch):
    import win32gui
    from ghostcursor.workspace.island import SHOW_MESSAGE

    opened = []
    monkeypatch.setattr(appmod, "_live_instance_url", lambda: "http://127.0.0.1:1234/?t=local")
    monkeypatch.setattr(win32gui, "FindWindow", lambda name, title: 42)
    revealed = []
    monkeypatch.setattr(win32gui, "PostMessage", lambda *args: revealed.append(args))
    monkeypatch.setattr(appmod, "open_window", lambda url, **kw: opened.append((url, kw)))
    assert appmod.main([]) == 0
    assert opened == []
    assert revealed == [(42, SHOW_MESSAGE, 0, 0)]
    assert appmod.main(["--window"]) == 0
    assert opened == [("http://127.0.0.1:1234/?t=local", {"docked": False})]


def _wait_for_job(app, state):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if app.state()["jobs"][0]["state"] == state:
            return app.state()["jobs"][0]
        time.sleep(0.01)
    pytest.fail(f"background job did not reach {state}")


def test_background_research_finishes_and_keeps_a_local_result(served):
    app, port = served
    started, release = threading.Event(), threading.Event()

    def research(question, *, cancelled, record):
        assert record is False
        started.set()
        assert release.wait(2)
        assert not cancelled()
        return "Cited result [1]"

    app.ws.research = research
    status, payload = call(port, "/api/job_start", {"question": "Find a source"})
    assert status == 200 and len(json.loads(payload)["id"]) == 16
    assert started.wait(1)
    assert app.state()["jobs"][0]["state"] == "running"
    assert call(port, "/api/job_start", {"question": "Another task"})[0] == 400
    assert len(app.state()["jobs"]) == 1
    release.set()
    job = _wait_for_job(app, "finished")
    assert job["answer"] == "Cited result [1]"
    assert "Find a source" in app.job_path.read_text(encoding="utf-8")
    assert call(port, "/api/job_delete", {"id": job["id"]})[0] == 200
    assert app.state()["jobs"] == []


def test_kept_research_result_survives_inbox_trim_and_restart(tmp_path):
    from ghostcursor.brief import brief_path

    root = tmp_path / "briefs"
    path = brief_path(root, "trip").with_suffix(".jobs.json")
    path.parent.mkdir(parents=True)
    old = {"id": "0000000000000000", "question": "Keep this", "answer": "Cited result",
           "state": "finished", "created": 1, "ended": 2, "routine": ""}
    path.write_text(json.dumps([old]), encoding="utf-8")  # pre-pin inbox schema
    make = lambda: Workspace("trip", Gateway(), Brain(tmp_path / "kb.sqlite"), root=root)
    app = App("trip", make_workspace=make)
    server = make_server(app, "secret-token")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert app.state()["jobs"][0]["pinned"] is False
        assert app.state()["jobs"][0]["archived"] is False
        assert call(server.server_port, "/api/job_pin", {"id": old["id"], "pinned": True})[0] == 200
        assert call(server.server_port, "/api/job_archive", {"id": old["id"], "archived": True})[0] == 200
        with app._job_lock:
            for i in range(1, 20):
                app.background_jobs.append({**old, "id": f"{i:016x}", "question": f"Question {i}", "pinned": False, "archived": False})
            app._save_background_jobs()
        app.ws.research = lambda *_args, **_kw: "New result"
        new_id = app.start_research_job("New question")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if any(row["id"] == new_id and row["state"] == "finished" for row in app.state()["jobs"]):
                break
            time.sleep(.01)
        jobs = app.state()["jobs"]
        assert len(jobs) == 20 and jobs[0]["id"] == old["id"] and jobs[0]["pinned"]
        assert "0000000000000001" not in {row["id"] for row in jobs}
        assert new_id in {row["id"] for row in jobs}
    finally:
        server.shutdown()
        app.close()
    reopened = App("trip", make_workspace=make)
    try:
        assert reopened.state()["jobs"][0]["id"] == old["id"]
        assert reopened.state()["jobs"][0]["pinned"] is True
        assert reopened.state()["jobs"][0]["archived"] is True
        reopened.handle("job_archive", {"id": old["id"], "archived": False})
        assert reopened.state()["jobs"][0]["archived"] is False
    finally:
        reopened.close()


def test_keep_result_is_bounded_and_rejects_invalid_or_unsaved_changes(served, monkeypatch):
    app, port = served
    with app._job_lock:
        for i in range(6):
            app.background_jobs.append({
                "id": f"{i:016x}", "question": f"Question {i}", "answer": "Result",
                "state": "finished", "created": i, "ended": i + 1, "routine": "", "pinned": False, "archived": False,
            })
        app._save_background_jobs()
    for i in range(5):
        assert call(port, "/api/job_pin", {"id": f"{i:016x}", "pinned": True})[0] == 200
    assert call(port, "/api/job_pin", {"id": "0000000000000005", "pinned": True})[0] == 400
    assert call(port, "/api/job_pin", {"id": "0000000000000005", "pinned": "yes"})[0] == 400
    assert sum(job["pinned"] for job in app.state()["jobs"]) == 5

    def failed_save():
        app.job_path = None

    monkeypatch.setattr(app, "_save_background_jobs", failed_save)
    assert call(port, "/api/job_pin", {"id": "0000000000000000", "pinned": False})[0] == 400
    assert next(job for job in app.state()["jobs"] if job["id"] == "0000000000000000")["pinned"] is True


def test_archive_requires_finished_result_and_rolls_back_failed_save(served, monkeypatch):
    app, port = served
    with app._job_lock:
        app.background_jobs.extend([
            {"id": f"{i:016x}", "question": f"Question {i}", "answer": "Result" if i == 0 else "",
             "state": "finished" if i == 0 else "running", "created": i, "ended": i + 1,
             "routine": "", "pinned": False, "archived": False}
            for i in range(2)
        ])
        app._save_background_jobs()
    assert call(port, "/api/job_archive", {"id": "0000000000000000", "archived": "yes"})[0] == 400
    assert call(port, "/api/job_archive", {"id": "0000000000000001", "archived": True})[0] == 400
    assert call(port, "/api/job_archive", {"id": "0000000000000000", "archived": True})[0] == 200
    assert next(job for job in app.state()["jobs"] if job["id"] == "0000000000000000")["archived"] is True

    def failed_save():
        app.job_path = None

    monkeypatch.setattr(app, "_save_background_jobs", failed_save)
    assert call(port, "/api/job_archive", {"id": "0000000000000000", "archived": False})[0] == 400
    assert next(job for job in app.state()["jobs"] if job["id"] == "0000000000000000")["archived"] is True


def test_background_stop_and_secret_scrub_before_research(served):
    app, port = served
    started, release = threading.Event(), threading.Event()
    seen = []

    def research(question, *, cancelled, record):
        assert record is False
        seen.append(question)
        started.set()
        assert release.wait(2)
        if cancelled():
            raise CancelledError()
        return "should not be kept"

    app.ws.research = research
    secret = "sk-abcdefghijklmnop"
    status, payload = call(port, "/api/job_start", {"question": "Check " + secret})
    assert status == 200 and started.wait(1)
    jid = json.loads(payload)["id"]
    assert secret not in seen[0]
    assert secret not in app.job_path.read_text(encoding="utf-8")
    assert call(port, "/api/job_cancel", {"id": "wrong"})[0] == 400
    assert call(port, "/api/job_cancel", {"id": jid})[0] == 200
    release.set()
    job = _wait_for_job(app, "stopped")
    assert job["answer"] == ""
    assert secret not in app.job_path.read_text(encoding="utf-8")


def test_background_answer_is_scrubbed_and_never_enters_brief(served, monkeypatch):
    from types import SimpleNamespace
    from ghostcursor.brief import brief_path
    from ghostcursor.workspace import session

    app, port = served
    secret = "sk-abcdefghijklmnop"
    seen = []

    def fake_research(question, gateway, **kw):
        seen.append(kw)
        return object(), SimpleNamespace(privacy="local test")

    monkeypatch.setattr(session, "research", fake_research)
    monkeypatch.setattr(session, "render", lambda graph: "Result " + secret)
    status, _ = call(port, "/api/job_start", {"question": "Safe question"})
    assert status == 200
    job = _wait_for_job(app, "finished")
    assert secret not in job["answer"]
    assert secret not in app.job_path.read_text(encoding="utf-8")
    assert not brief_path(app.ws.root, app.ws.topic).exists()
    assert app.ws.research_graphs == []
    assert seen[0]["save_trace"] is False


def test_stale_background_job_becomes_interrupted(tmp_path):
    root = tmp_path / "briefs"
    make = lambda: Workspace("trip", Gateway(), Brain(tmp_path / "kb.sqlite"), root=root)
    app = App("trip", make_workspace=make, clock=lambda: 100)
    path = app.job_path
    app.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{
        "id": "0123456789abcdef", "question": "Old question", "answer": "",
        "state": "running", "created": 10, "ended": None, "routine": "",
    }]), encoding="utf-8")
    reopened = App("trip", make_workspace=make, clock=lambda: 100)
    try:
        assert reopened.state()["jobs"][0]["state"] == "interrupted"
        assert reopened.state()["jobs"][0]["ended"] == 100
        assert json.loads(path.read_text(encoding="utf-8"))[0]["state"] == "interrupted"
    finally:
        reopened.close()


def test_malformed_job_inbox_stays_untouched(tmp_path):
    root = tmp_path / "briefs"
    make = lambda: Workspace("trip", Gateway(), Brain(tmp_path / "kb.sqlite"), root=root)
    first = App("trip", make_workspace=make)
    path = first.job_path
    first.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[{"id":"bad","question":"x"}]', encoding="utf-8")
    reopened = App("trip", make_workspace=make)
    try:
        assert reopened.state()["jobs"] == []
        assert reopened.job_path is None
        assert path.read_text(encoding="utf-8") == '[{"id":"bad","question":"x"}]'
    finally:
        reopened.close()


def test_routine_runs_once_after_sleep_and_can_pause_resume_delete(served):
    app, port = served
    now = [100.0]
    app.clock = lambda: now[0]
    seen = []
    app.ws.research = lambda question, *, cancelled, record: seen.append(question) or "Cited answer [1]"
    secret = "sk-abcdefghijklmnop"
    status, payload = call(port, "/api/routine_create", {"question": "Check " + secret, "cadence": "hourly"})
    assert status == 200
    rid = json.loads(payload)["id"]
    assert app.has_enabled_routines()
    assert secret not in app.routine_path.read_text(encoding="utf-8")
    app.tick_routines()
    assert not seen
    now[0] += 3600 * 10  # missed intervals coalesce into one due run
    app.tick_routines()
    _wait_for_job(app, "finished")
    assert len(seen) == 1 and secret not in seen[0]
    app.tick_routines()
    assert len(seen) == 1
    assert app.state()["routines"][0]["next_due"] == now[0] + 3600
    assert call(port, "/api/routine_pause", {"id": rid})[0] == 200
    assert not app.has_enabled_routines()
    now[0] += 3600 * 10
    app.tick_routines()
    assert len(seen) == 1
    assert call(port, "/api/routine_resume", {"id": rid})[0] == 200
    assert app.state()["routines"][0]["next_due"] == now[0] + 3600
    assert call(port, "/api/routine_delete", {"id": rid})[0] == 200
    assert not app.has_enabled_routines()
    assert app.state()["routines"] == []


def test_routine_reruns_report_only_new_claims(served):
    assert appmod.new_claims(
        "- Price fell [s2]\n- Office opens (partial) [s1][s3]\nSources:\n  [s1] x",
        "- price fell [s1]\nSources:",
    ) == ["Office opens (partial)"]
    assert appmod.new_claims("- Revenue grows", "") == ["Revenue grows"]  # trailing s kept
    # Seen live on 28 Oct: the model reworded an unchanged fact between runs.
    assert appmod.new_claims(
        "- As of October 2026, the latest stable Python 3 release is Python 3.15.0, released on October 9, 2026. [s1]",
        "- The latest stable Python 3 release is Python 3.15.0, released on October 9, 2026, "
        "according to the provided passages covering October 2026. [s1][s5]",
    ) == []
    assert appmod.new_claims("- Price fell to 12 dollars", "- Price fell to 10 dollars") == ["Price fell to 12 dollars"]
    app, port = served
    now = [100.0]
    app.clock = lambda: now[0]
    answers = iter(["- Old fact [s1]", "- Old fact [s2]\n- New fact [s1]"])
    app.ws.research = lambda question, *, cancelled, record: next(answers)
    call(port, "/api/routine_create", {"question": "Watch", "cadence": "hourly"})
    for _ in range(2):
        now[0] += 3600
        app.tick_routines()
        _wait_for_job(app, "finished")
        while app.busy:
            time.sleep(0.01)
    first, second = sorted(app.state()["jobs"], key=lambda j: j["ended"])
    assert "new_claims" not in first  # nothing to compare against
    assert second["new_claims"] == ["New fact"]
    assert "new_claims" not in json.loads(app.job_path.read_text(encoding="utf-8"))[1]


def test_routines_survive_restart_and_malformed_file_is_preserved(tmp_path):
    root = tmp_path / "briefs"
    make = lambda: Workspace("trip", Gateway(), Brain(tmp_path / "kb.sqlite"), root=root)
    first = App("trip", make_workspace=make, clock=lambda: 100)
    first.handle("routine_create", {"question": "Find updates", "cadence": "daily"})
    path = first.routine_path
    first.close()
    second = App("trip", make_workspace=make, clock=lambda: 200)
    try:
        assert second.has_enabled_routines()
        assert second.state()["routines"][0]["next_due"] == 100 + 86400
    finally:
        second.close()
    path.write_text('{"invalid":true}', encoding="utf-8")
    third = App("trip", make_workspace=make)
    try:
        assert third.routine_path is None
        assert third.state()["routines"] == []
        assert path.read_text(encoding="utf-8") == '{"invalid":true}'
    finally:
        third.close()


def test_quit_during_due_tick_cannot_start_research(served):
    app, port = served
    now = [100.0]
    app.clock = lambda: now[0]
    rid = app.handle("routine_create", {"question": "Find updates", "cadence": "hourly"})["id"]
    assert rid
    now[0] = 3700.0
    entered, release = threading.Event(), threading.Event()

    def blocked_clock():
        entered.set()
        assert release.wait(2)
        return now[0]

    app.clock = blocked_clock
    called = []
    app.ws.research = lambda *a, **kw: called.append(a)
    tick = threading.Thread(target=app.tick_routines)
    tick.start()
    assert entered.wait(1)  # after the outer quit check
    assert call(port, "/api/quit")[0] == 200
    release.set()
    tick.join(2)
    assert not tick.is_alive()
    assert called == []
    assert app.quit_requested.is_set()


def test_due_time_is_durable_before_scheduled_job_starts(tmp_path):
    root = tmp_path / "briefs"
    make = lambda: Workspace("trip", Gateway(), Brain(tmp_path / "kb.sqlite"), root=root)
    now = [100.0]
    app = App("trip", make_workspace=make, clock=lambda: now[0])
    app.handle("routine_create", {"question": "Find updates", "cadence": "hourly"})
    now[0] = 3700.0

    def crash_window(*args, **kwargs):
        assert json.loads(app.routine_path.read_text(encoding="utf-8"))[0]["next_due"] == 7300.0
        raise RuntimeError("simulated process death before work starts")

    app.start_research_job = crash_window
    try:
        with pytest.raises(RuntimeError, match="simulated process death"):
            app.tick_routines()
    finally:
        app.close()
    reopened = App("trip", make_workspace=make, clock=lambda: now[0])
    try:
        calls = []
        reopened.start_research_job = lambda *a, **kw: calls.append(a)
        reopened.tick_routines()
        assert calls == []  # no automatic retry of the same occurrence
    finally:
        reopened.close()


def test_missed_routine_after_downtime_replays_once(tmp_path):
    root = tmp_path / "briefs"
    make = lambda: Workspace("trip", Gateway(), Brain(tmp_path / "kb.sqlite"), root=root)
    now = [100.0]
    first = App("trip", make_workspace=make, clock=lambda: now[0])
    first.handle("routine_create", {"question": "Find updates", "cadence": "hourly"})
    first.close()

    now[0] += 10 * 3600  # PC was unavailable across ten due times
    resumed = App("trip", make_workspace=make, clock=lambda: now[0])
    calls = []
    resumed.ws.research = lambda question, *, cancelled, record: calls.append(question) or "Cited answer [1]"
    try:
        resumed.tick_routines()
        assert _wait_for_job(resumed, "finished")["routine"] == resumed.routines[0]["id"]
        assert calls == ["Find updates"]
        assert resumed.routines[0]["next_due"] == now[0] + 3600
    finally:
        resumed.close()

    reopened = App("trip", make_workspace=make, clock=lambda: now[0])
    try:
        reopened.ws.research = lambda *a, **kw: calls.append("unexpected")
        reopened.tick_routines()
        assert calls == ["Find updates"]
        assert reopened.state()["jobs"][0]["state"] == "finished"
    finally:
        reopened.close()


def test_failed_schedule_save_prevents_unattended_run(served, monkeypatch):
    app, _ = served
    now = [100.0]
    app.clock = lambda: now[0]
    app.handle("routine_create", {"question": "Find updates", "cadence": "hourly"})
    now[0] = 3700.0
    monkeypatch.setattr(app, "_save_routines", lambda: False)
    called = []
    app.start_research_job = lambda *a, **kw: called.append(a)
    app.tick_routines()
    assert called == []
    assert not app.has_enabled_routines()


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
    assert json.loads(payload) == {"answer": "Sure.", "sent": "Private file: east"}
    assert app.ws.turns == ()
    saved = app.activity_path.read_text(encoding="utf-8")
    assert "Private file" not in saved and "Where?" not in saved
    assert json.loads(saved)[-1] == {"label": "Asking file", "state": "finished"}

    for material in (["wrong type"], "x" * 100_001, "\0binary"):
        status, _ = call(port, "/api/ask_file", {"text": "Where?", "material": material})
        assert status == 400
    status, _ = call(port, "/api/ask_file", {"text": ["wrong type"], "material": "text"})
    assert status == 400


def test_saved_result_follow_up_uses_server_selected_bounded_answer(served):
    app, port = served
    jid = "0000000000000000"
    with app._job_lock:
        app.background_jobs.append({
            "id": jid, "question": "Original question", "answer": "A" * 8000 + "TRAILING",
            "state": "finished", "created": 1, "ended": 2, "routine": "", "pinned": False, "archived": False,
        })
        app.background_jobs.append({
            "id": "0000000000000001", "question": "Running", "answer": "Premature answer",
            "state": "running", "created": 3, "ended": None, "routine": "", "pinned": False, "archived": False,
        })
        app._save_background_jobs()
    seen = []
    app.ws.ask = lambda question, material, *, cancelled: (seen.append((question, material, cancelled())), "Grounded reply")[1]
    status, payload = call(port, "/api/job_ask", {"id": jid, "text": "What?", "material": "injected"})
    assert status == 200 and json.loads(payload) == {"answer": "Grounded reply", "sent": ""}
    assert seen == [("What?", "A" * 8000 + "TRAILING", False)]  # ws.ask bounds what is sent
    assert app.ws.turns == ()
    saved = app.job_path.read_text(encoding="utf-8")
    assert "What?" not in saved and "Grounded reply" not in saved
    assert call(port, "/api/job_ask", {"id": "ffffffffffffffff", "text": "What?"})[0] == 400
    assert call(port, "/api/job_ask", {"id": "0000000000000001", "text": "What?"})[0] == 400
    assert call(port, "/api/job_ask", {"id": jid, "text": ""})[0] == 400
    assert call(port, "/api/job_ask", {"id": jid, "text": "x" * 501})[0] == 400
    assert call(port, "/api/job_ask", {"id": jid, "text": "x\0y"})[0] == 400


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
            "answer": "Sure.", "sent": "a file"
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


@pytest.mark.interactive
def test_chat_plan_and_brain_views_keep_a_clear_next_action(served):
    playwright = pytest.importorskip("playwright.sync_api")
    app, port = served
    assert app.state()["company_brain_available"] is False
    with playwright.sync_playwright() as browser:
        edge = browser.chromium.launch(executable_path=str(appmod.EDGE), headless=True)
        try:
            page = edge.new_page(viewport={"width": 500, "height": 800})
            page.goto(f"http://127.0.0.1:{port}/?t=secret-token#chat")
            page.get_by_role("heading", name="Start with what you want to do.").wait_for()
            page.get_by_role("tab", name="Plan").click()
            page.get_by_role("button", name="Describe a goal").click()
            assert page.get_by_role("tab", name="Chat").get_attribute("aria-selected") == "true"
            assert page.evaluate("document.activeElement.getAttribute('aria-label')") == "Message"
            page.get_by_role("tab", name="Brain").click()
            sections = page.get_by_role("group", name="Brain sections")
            assert sections.get_by_role("button", name="Personal").get_attribute("aria-pressed") == "true"
            sections.get_by_role("button", name="Company").click()
            page.get_by_text("Company Brain is not set up in this workspace.").wait_for()
            assert page.evaluate("document.activeElement.textContent") == "Company"
            sections.get_by_role("button", name="Setup").click()
            page.get_by_text("Let Jev see a picture", exact=False).wait_for()
            assert page.locator("#tab-brain").get_by_text("[object Object]").count() == 0
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        finally:
            edge.close()


@pytest.mark.interactive
def test_first_run_guide_uses_existing_setup_and_remembers_dismissal(served):
    playwright = pytest.importorskip("playwright.sync_api")
    _, port = served
    with playwright.sync_playwright() as browser:
        edge = browser.chromium.launch(executable_path=str(appmod.EDGE), headless=True)
        try:
            page = edge.new_page(viewport={"width": 500, "height": 800})
            page.goto(f"http://127.0.0.1:{port}/?t=secret-token#chat")
            guide = page.get_by_role("region", name="Getting started")
            guide.get_by_role("button", name="Check setup").click()
            assert page.get_by_role("tab", name="Brain").get_attribute("aria-selected") == "true"
            assert page.get_by_role("button", name="Setup").get_attribute("aria-pressed") == "true"
            assert page.evaluate("document.activeElement.textContent") == "Setup"
            page.reload()
            page.get_by_role("tab", name="Chat").click()
            assert page.get_by_role("region", name="Getting started").count() == 0
            assert page.evaluate("localStorage.getItem('orbyn-welcome-v1')") == "seen"

            fresh = edge.new_page(viewport={"width": 500, "height": 800})
            fresh.goto(f"http://127.0.0.1:{port}/?t=secret-token#chat")
            fresh.get_by_role("region", name="Getting started").get_by_role("button", name="Start typing").click()
            assert fresh.evaluate("document.activeElement.getAttribute('aria-label')") == "Message"
            assert fresh.get_by_role("region", name="Getting started").count() == 0
        finally:
            edge.close()


@pytest.mark.interactive
def test_saved_research_card_downloads_markdown(served, tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    app, port = served
    question = "What changed?"
    answer = "Use **two** steps.\n<script>alert(1)</script>"
    with app._job_lock:
        app.background_jobs.append({
            "id": "0123456789abcdef", "question": question, "answer": answer,
            "state": "finished", "created": 1.0, "ended": 2.0, "routine": "", "pinned": False, "archived": False,
        })
    with playwright.sync_playwright() as browser:
        edge = browser.chromium.launch(executable_path=str(appmod.EDGE), headless=True)
        try:
            page = edge.new_page(accept_downloads=True, viewport={"width": 500, "height": 800})
            page.goto(f"http://127.0.0.1:{port}/?t=secret-token#work")
            stage = page.get_by_role("region", name="Current work cards")
            stage.get_by_role("heading", name=question).wait_for()
            stage.get_by_role("button", name="Read result").click()
            page.get_by_role("dialog", name="Research result").wait_for()
            page.get_by_role("button", name="Close", exact=True).click()
            page.get_by_role("button", name="Keep", exact=True).click()
            page.get_by_role("button", name="Unkeep").wait_for()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.get_by_role("button", name="Archive", exact=True).click()
            page.get_by_role("button", name="Show archived (1)").wait_for()
            assert page.get_by_role("button", name="View result").count() == 0
            assert stage.get_by_role("button", name="Read result").count() == 0
            page.get_by_role("button", name="Show archived (1)").click()
            page.get_by_role("button", name="Restore").wait_for()
            page.get_by_role("button", name="Restore").click()
            page.get_by_role("button", name="Archive", exact=True).wait_for()
            page.get_by_role("button", name="Archive", exact=True).click()
            page.get_by_role("button", name="Show archived (1)").wait_for()
            assert page.get_by_role("button", name="View result").count() == 0
            page.get_by_role("button", name="Show archived (1)").click()
            page.get_by_role("button", name="Download Markdown").focus()
            page.evaluate("renderWork()")
            assert page.evaluate("document.activeElement.textContent") == "Download Markdown"
            page.get_by_role("button", name="View result").click()
            page.get_by_role("textbox", name="Question about this result").fill("What are the steps?")
            page.get_by_role("button", name="Ask about result").click()
            reply = page.get_by_role("status").filter(has_text="Sure.")
            reply.wait_for()
            assert reply.text_content() == "Sure."
            assert page.locator("#jobAskStop").is_hidden()  # shown only while asking
            page.get_by_role("button", name="Close", exact=True).click()
            with page.expect_download() as pending:
                page.get_by_role("button", name="Download Markdown").click()
            download = pending.value
            assert download.suggested_filename == "orbyn-research.md"
            path = tmp_path / download.suggested_filename
            download.save_as(path)
            assert path.read_text(encoding="utf-8") == f"# {question}\n\n{answer}\n"
        finally:
            edge.close()


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
        assert app.state()["company_brain_available"] is True
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


def test_heard_goes_to_the_island_when_it_is_shown(served):
    app, _ = served
    heard = []
    app.voice_to = heard.append
    app.heard("plan my week")
    assert heard == ["plan my week"] and app.status[-1] == "Heard: plan my week"


def test_stats_answer_while_the_worker_is_busy(served, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    app, port = served
    app.busy = "Thinking"  # a long run holds the worker
    code, payload = call(port, "/api/stats", {})
    assert code == 200 and json.loads(payload)["research_answers"] == 0
    app.busy = ""


def test_a_weekdays_routine_skips_the_weekend():
    import time

    from ghostcursor.workspace.app import next_due

    friday = time.mktime((2026, 10, 30, 9, 0, 0, 0, 0, -1))  # Fri 30 Oct 2026, 09:00 local
    monday = time.localtime(next_due("weekdays", friday))
    assert (monday.tm_wday, monday.tm_mday, monday.tm_hour) == (0, 2, 9)
    tuesday = time.localtime(next_due("weekdays", time.mktime((2026, 11, 2, 9, 0, 0, 0, 0, -1))))
    assert (tuesday.tm_wday, tuesday.tm_mday) == (1, 3)
    saturday = time.localtime(next_due("daily", friday))
    assert saturday.tm_wday == 5  # daily still runs at the weekend


def test_a_right_clicked_text_file_is_read_with_ask_a_files_limits(tmp_path):
    from ghostcursor.workspace.app import read_text_file

    good = tmp_path / "notes.md"
    good.write_text("The launch is on Friday.", encoding="utf-8")
    assert read_text_file(str(good)) == ("notes.md", "The launch is on Friday.")
    for name, data in [("bin.dat", b"\x00\x01\x02"), ("latin.txt", "caf\xe9".encode("latin-1")),
                       ("big.txt", b"a" * (400 * 1024 + 1)), ("empty.txt", b"  ")]:
        (tmp_path / name).write_bytes(data)
        with pytest.raises(ValueError):
            read_text_file(str(tmp_path / name))
    with pytest.raises(ValueError):
        read_text_file(str(tmp_path / "missing.txt"))
    with pytest.raises(ValueError):
        read_text_file(str(tmp_path))  # a folder


def test_an_offered_file_is_shown_once_and_needs_the_token(served):
    app, port = served
    status, _ = call(port, "/api/offer_file", {"name": "notes.md", "material": "hello"}, token="wrong")
    assert status != 200 and app.offered_file is None
    status, _ = call(port, "/api/offer_file", {"name": "notes.md", "material": "hello"})
    assert status == 200
    assert json.loads(call(port, "/api/state")[1])["offered_file"] == "notes.md"  # the name, never the text
    assert b"hello" not in call(port, "/api/state")[1]
    assert json.loads(call(port, "/api/take_offered_file")[1]) == {"name": "notes.md", "material": "hello"}
    assert json.loads(call(port, "/api/take_offered_file")[1]) == {}
    assert json.loads(call(port, "/api/state")[1])["offered_file"] == ""
    for bad in ({"name": "x", "material": "a\0b"}, {"name": "x", "material": " "},
                {"name": 3, "material": "a"}, {"name": "x", "material": "a" * 100_001}):
        assert call(port, "/api/offer_file", bad)[0] != 200
    assert app.offered_file is None
