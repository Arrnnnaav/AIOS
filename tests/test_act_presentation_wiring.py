"""The acceptance harness's cue surface, and the manager's refusal.

D032 review, round 2. Two mutations survived the whole suite here, and both
were verbatim reverts of what the commit under review claimed to fix:
`presentation=None` (the harness could no longer run a control-driving node
at all) and `keep_running=lambda: True` (the precise hardwiring that change
removed). The only coverage was a symtable scan that catches a dropped import
and no logic.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ghostcursor.act_runtime import ActControls


def _args(first=2000, completion=8000):
    return SimpleNamespace(
        first_paint_deadline_ms=first, completion_deadline_ms=completion
    )


def _stub_window(monkeypatch):
    created, destroyed = [], []
    from ghostcursor.overlay import window as overlay_window

    monkeypatch.setattr(
        overlay_window,
        "create_overlay_window",
        lambda: created.append(1) or 4242,
    )
    monkeypatch.setattr(
        overlay_window, "destroy_overlay_window", lambda hwnd: destroyed.append(hwnd)
    )
    return created, destroyed


def test_the_harness_builds_one_surface_on_one_window(monkeypatch):
    from ghostcursor.devtools.act_acceptance import presentation_for

    created, _destroyed = _stub_window(monkeypatch)
    hwnd, surface = presentation_for(_args(), ActControls())

    assert hwnd == 4242
    assert created == [1]
    assert surface.policy.first_paint_deadline_ms == 2000
    assert surface.overlay is not None


def test_the_harness_reuses_the_region_window(monkeypatch):
    """A second topmost full-screen window would fight the first for the same
    pixels."""

    from ghostcursor.devtools.act_acceptance import presentation_for

    created, _destroyed = _stub_window(monkeypatch)
    hwnd, _surface = presentation_for(_args(), ActControls(), overlay_hwnd=99)

    assert hwnd == 99
    assert created == [], "a second overlay window was created"


def test_stop_reaches_the_harness_cue(monkeypatch):
    """`keep_running=lambda: True` survived the whole suite, which is exactly
    the hardwiring the change under review removed."""

    from ghostcursor.devtools import act_acceptance
    from ghostcursor.act_overlay import overlay_presenter as real_presenter

    _stub_window(monkeypatch)
    captured = {}

    def presenter(hwnd, **kwargs):
        captured.update(kwargs)
        return real_presenter(
            hwnd,
            bounds=(0, 0, 1920, 1080),
            pump=lambda: None,
            geometry_check=lambda *_args: (),
            **kwargs,
        )

    monkeypatch.setattr("ghostcursor.act_overlay.overlay_presenter", presenter)

    controls = ActControls()
    act_acceptance.presentation_for(_args(), controls)

    keep_running = captured["keep_running"]
    assert keep_running() is True
    controls.stop()
    assert keep_running() is False, "Stop cannot reach the cue"


@pytest.mark.parametrize("first, completion", [(0, 8000), (2000, 0), (-1, 8000)])
def test_a_bad_deadline_never_creates_a_window(monkeypatch, first, completion):
    """`ReceiptPolicy` refuses a non-positive deadline. Building the window
    first meant `--first-paint-deadline-ms 0` created a topmost click-through
    window covering the screen and then raised past every cleanup, leaving it
    up with no way to close it."""

    from ghostcursor.act_protocol import ProtocolError
    from ghostcursor.devtools.act_acceptance import presentation_for

    created, destroyed = _stub_window(monkeypatch)
    with pytest.raises(ProtocolError):
        presentation_for(_args(first, completion), ActControls())

    assert created == [], "a topmost overlay leaked on a refused deadline"
    assert destroyed == []


def test_the_harness_forwards_the_surface_to_the_run():
    """`presentation=None` survived the suite -- a silent revert of the whole
    change, since the runtime then refuses every control-driving node."""

    import inspect

    from ghostcursor.devtools import act_acceptance

    source = inspect.getsource(act_acceptance.run)
    assert "presentation=presentation" in source
    assert "presentation_for(" in source


# --- the manager refuses, and says why ------------------------------------


def test_the_manager_refuses_a_control_driving_plan(monkeypatch):
    """Act runs on a worker thread and a Win32 overlay must be created on the
    thread that pumps for it, so the manager growing a surface is a design
    change rather than a bug fix. Refusing is right; refusing SILENTLY is
    not, and the refusal had no test at all."""

    from ghostcursor import manager as manager_module

    monkeypatch.setattr(
        "ghostcursor.act_cli.plan_draws_a_pointer", lambda proposal: True
    )
    ran = []
    monkeypatch.setattr(
        "ghostcursor.act_cli.execute_act_proposal",
        lambda *a, **k: ran.append(1),
    )

    worker = manager_module._ActWorker()
    worker.start(SimpleNamespace(output_path=SimpleNamespace(parent="root")))
    worker._thread.join(timeout=5.0)

    results = []
    while True:
        try:
            results.append(worker._results.get_nowait())
        except Exception:
            break

    assert ran == [], "a control-driving plan ran with no presentation surface"
    assert results and isinstance(results[0], Exception)
    assert "presentation surface" in str(results[0])
