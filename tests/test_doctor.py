"""The readiness self-check (agent-reach's `doctor` idea): it reports every
capability's state and never raises, so a broken probe can't hide the rest."""

from __future__ import annotations

from ghostcursor import doctor


def test_checks_cover_every_capability_and_never_raise():
    cs = doctor.checks()
    names = {c.name for c in cs}
    assert "models (BYOK)" in names
    assert any("wake word" in n for n in names)
    assert any("Act" in n for n in names)
    for c in cs:
        assert isinstance(c.ready, bool) and c.name and c.hint  # fully formed


def test_report_lists_each_capability_with_a_state_marker():
    text = doctor.report()
    assert "readiness" in text
    for c in doctor.checks():
        assert c.name in text
    assert "[ok " in text or "[off" in text  # a state marker per line


def test_dep_says_ready_when_present_else_the_fix():
    assert doctor._dep("x", True, "pip install x").hint == "ready"
    assert doctor._dep("x", False, "pip install x").hint == "pip install x"


def test_has_is_false_for_a_missing_module_and_never_raises():
    assert doctor._has("definitely_not_a_real_module_zzz") is False
    assert isinstance(doctor._has("os"), bool)


def test_each_probe_swallows_its_own_failure(monkeypatch):
    """A broken dependency check reports off, not a crash: the models and REA
    probes wrap their own errors so the report always renders."""
    import ghostcursor.providers.keys as keys

    monkeypatch.setattr(keys, "status", lambda: (_ for _ in ()).throw(OSError("x")))
    m = doctor._models()
    assert m.ready is False and "could not check" in m.hint


def test_json_flag_emits_machine_readable_checks(capsys):
    """`doctor --json` for the GUI card and tooling: one object per check with
    the same fields, parseable, never a crash."""
    import json

    assert doctor.main(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data and all(set(c) == {"name", "ready", "hint"} for c in data)
