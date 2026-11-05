"""Crash reports (D191): content-free events, only when the organisation named
an endpoint AND the person opted in; never the error text, a path outside
the package, a name or a local variable; never raises."""

from __future__ import annotations

import json

import httpx
import pytest

from ghostcursor import crashreport, policy, settings

DSN = "https://publickey@o1.ingest.example.com/42"
SECRET = (
    r"C:\Users\ana.perez\Documents\payroll.xlsx sk-ABCDEF1234567890 ana@example.com"
)


def _boom():
    local_secret = SECRET  # noqa: F841 -- a local variable must never be sent
    try:
        raise KeyError(SECRET)
    except KeyError as inner:
        raise ValueError(SECRET) from inner


def _caught():
    try:
        _boom()
    except ValueError as exc:
        return exc


def _capture():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "x"})

    return httpx.MockTransport(handle), seen


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    from ghostcursor import audit

    monkeypatch.setattr(audit, "record", lambda *a, **k: True)


def test_the_event_carries_types_and_places_never_content():
    body = json.dumps(crashreport.event(_caught()))
    for leak in (
        "ana.perez",
        "payroll",
        "sk-ABCDEF",
        "ana@example.com",
        "Documents",
        "Users",
    ):
        assert leak not in body
    event = crashreport.event(_caught())
    values = event["exception"]["values"]
    assert [v["type"] for v in values] == ["KeyError", "ValueError"]  # cause first
    frames = values[-1]["stacktrace"]["frames"]
    assert {"module": "tests.test_crashreport", "function": "_boom", "in_app": False} in frames
    assert all(not f.get("filename", "").startswith(("C:", "/", "\\")) for f in frames)
    assert set(event) == {
        "event_id",
        "timestamp",
        "platform",
        "level",
        "release",
        "contexts",
        "exception",
    }


def test_a_frame_in_orbyn_keeps_its_package_path_and_line():
    path = str(crashreport.PACKAGE / "harness" / "act.py")
    assert crashreport._frame(path, "perform", 7, "ghostcursor.harness.act") == {
        "filename": "ghostcursor/harness/act.py",
        "function": "perform",
        "lineno": 7,
        "in_app": True,
    }


def test_a_frame_outside_the_package_keeps_only_its_module_name():
    frame = crashreport._frame(
        r"C:\Python312\Lib\json\decoder.py", "decode", 3, "json.decoder"
    )
    assert frame == {"module": "json.decoder", "function": "decode", "in_app": False}


def test_it_sends_a_sentry_envelope_to_the_dsn():
    transport, seen = _capture()
    assert crashreport.send(_caught(), transport=transport, dsn=DSN)
    (request,) = seen
    assert str(request.url) == "https://o1.ingest.example.com/api/42/envelope/"
    assert "sentry_key=publickey" in request.headers["X-Sentry-Auth"]
    header, kind, event = request.content.decode().split("\n")
    assert (
        json.loads(kind) == {"type": "event"}
        and json.loads(header)["event_id"] == json.loads(event)["event_id"]
    )
    assert "ana.perez" not in request.content.decode()


@pytest.mark.parametrize(
    "dsn",
    [
        None,
        "",
        "http://key@host/42",
        "https://host/42",
        "https://key@host/project",
        "https://key@/42",
        "not a url",
    ],
)
def test_a_bad_dsn_sends_nothing(dsn):
    transport, seen = _capture()
    assert not crashreport.send(_caught(), transport=transport, dsn=dsn) and not seen


@pytest.mark.parametrize(
    "opted_in, endpoint, egress",
    [(False, DSN, True), (True, None, True), (True, DSN, False)],
)
def test_nothing_is_sent_without_the_person_the_endpoint_and_egress(
    monkeypatch, tmp_path, opted_in, endpoint, egress
):
    path = tmp_path / "settings.json"
    settings.set_crash_reports(opted_in, path)
    monkeypatch.setattr(
        settings,
        "crash_reports",
        lambda: (
            settings.load(path).get("crash_reports") is True
            and policy.crash_endpoint() is not None
        ),
    )
    monkeypatch.setattr(policy, "crash_endpoint", lambda: endpoint)
    monkeypatch.setattr(policy, "allows", lambda provider, images=0: egress)
    transport, seen = _capture()
    assert not crashreport.send(_caught(), transport=transport) and not seen


def test_with_everything_allowed_it_sends(monkeypatch):
    monkeypatch.setattr(settings, "crash_reports", lambda: True)
    monkeypatch.setattr(policy, "crash_endpoint", lambda: DSN)
    monkeypatch.setattr(
        policy, "allows", lambda provider, images=0: provider == "crash"
    )
    transport, seen = _capture()
    assert crashreport.send(_caught(), transport=transport) and len(seen) == 1


def test_the_setting_needs_the_policy_endpoint(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    settings.set_crash_reports(True, path)
    monkeypatch.setattr(policy, "crash_endpoint", lambda: None)
    assert settings.crash_reports(path) is False
    monkeypatch.setattr(policy, "crash_endpoint", lambda: DSN)
    assert settings.crash_reports(path) is True


@pytest.mark.parametrize(
    "value, expected", [(DSN, DSN), ("http://k@h/1", None), ("", None), (None, None)]
)
def test_the_policy_endpoint_is_https_only(monkeypatch, value, expected):
    monkeypatch.setattr(
        policy, "_text", lambda name: value if name == "CrashEndpoint" else None
    )
    assert policy.crash_endpoint() == expected


def test_sending_never_raises():
    def broken(request):
        raise httpx.ConnectError("down")

    assert (
        crashreport.send(_caught(), transport=httpx.MockTransport(broken), dsn=DSN)
        is False
    )


def test_the_policy_endpoint_alone_turns_nothing_on(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(policy, "crash_endpoint", lambda: DSN)
    assert settings.crash_reports(path) is False  # never set
    settings.set_crash_reports(False, path)
    assert settings.crash_reports(path) is False
