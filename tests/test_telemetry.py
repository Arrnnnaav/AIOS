"""Local telemetry (D141): off by default, events-not-content, and -- the point
-- NOTHING leaves the device. The no-network-import scan is the real guard: it
fails if anyone ever adds an egress path to this module.
"""

from __future__ import annotations

import ast
from pathlib import Path


from ghostcursor import telemetry


def test_off_by_default_is_a_noop(tmp_path):
    p = tmp_path / "t.json"
    assert telemetry.record("teach_run", path=p, enabled=False) is False
    assert not p.exists()
    assert telemetry.counts(p) == {}


def test_counts_only_allowlisted_event_names(tmp_path):
    p = tmp_path / "t.json"
    assert telemetry.record("teach_run", path=p, enabled=True) is True
    assert telemetry.record("teach_run", path=p, enabled=True) is True
    assert telemetry.record("act_run", path=p, enabled=True) is True
    # a non-allowlisted name (or smuggled content) is refused -> no record
    assert telemetry.record("not_an_event", path=p, enabled=True) is False
    assert (
        telemetry.record("note: the password is hunter2", path=p, enabled=True) is False
    )
    assert telemetry.counts(p) == {"act_run": 1, "teach_run": 2}


def test_telemetry_has_no_network_import():
    """The no-egress invariant: telemetry.py must import nothing that could send
    data off the device. If someone adds egress, this fails."""

    src = (Path("ghostcursor") / "telemetry.py").read_text(encoding="utf-8")
    banned = {
        "socket",
        "http",
        "httpx",
        "urllib",
        "urllib.request",
        "requests",
        "ftplib",
        "smtplib",
        "asyncio",
        "websocket",
        "websockets",
        "ssl",
    }
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    leaked = names & banned
    assert not leaked, f"telemetry.py must not import network modules: {leaked}"


def test_policy_gate_defaults_off(monkeypatch):
    # with no registry policy value, telemetry is off (opt-in)
    from ghostcursor import policy

    monkeypatch.setattr(policy, "_value", lambda name: None)
    assert policy.telemetry_enabled() is False
    monkeypatch.setattr(policy, "_value", lambda name: "unreadable")
    assert policy.telemetry_enabled() is False  # unreadable -> off (not a guard)
    monkeypatch.setattr(policy, "_value", lambda name: 1)
    assert policy.telemetry_enabled() is True
