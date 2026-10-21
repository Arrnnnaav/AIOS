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


def test_every_allowlisted_event_has_exactly_one_emitter_set():
    """No dangling allowlist name, and no record() of an unlisted name: the set
    of names passed to telemetry.record(...) across the package must equal
    EVENTS. Keeps the allowlist honest as emitters are added/removed."""

    import ast

    emitted = set()
    for path in Path("ghostcursor").rglob("*.py"):
        if path.name == "telemetry.py":
            continue  # its __main__ self-check uses throwaway names on purpose
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "record"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "telemetry"
                and node.args
            ):
                # The arg is a string literal or a ternary of them
                # (record("act_run" if ... else "teach_run")) -- take the
                # branches, never the ternary's condition.
                arg = node.args[0]
                branches = (
                    [arg.body, arg.orelse] if isinstance(arg, ast.IfExp) else [arg]
                )
                for b in branches:
                    if isinstance(b, ast.Constant) and isinstance(b.value, str):
                        emitted.add(b.value)
    assert emitted == set(telemetry.EVENTS), {
        "unlisted_but_emitted": emitted - set(telemetry.EVENTS),
        "listed_but_never_emitted": set(telemetry.EVENTS) - emitted,
    }


def test_policy_gate_defaults_off(monkeypatch):
    # with no registry policy value, telemetry is off (opt-in)
    from ghostcursor import policy

    monkeypatch.setattr(policy, "_value", lambda name: None)
    assert policy.telemetry_enabled() is False
    monkeypatch.setattr(policy, "_value", lambda name: "unreadable")
    assert policy.telemetry_enabled() is False  # unreadable -> off (not a guard)
    monkeypatch.setattr(policy, "_value", lambda name: 1)
    assert policy.telemetry_enabled() is True
