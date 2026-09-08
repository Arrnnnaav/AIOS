"""Manager Act worker wiring that does not require a live Win32 window."""

from __future__ import annotations

import time
import threading
from types import SimpleNamespace

import pytest

from ghostcursor.manager import (
    _ActWorker,
    _create_manager_act_presentation,
    _issue_act_execution_request,
)


def _take(worker: _ActWorker):
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        result = worker.take_result()
        if result is not None:
            return result
        time.sleep(0.01)
    raise AssertionError("Act worker did not finish")


def test_pointer_plan_receives_the_ui_thread_surface_and_no_fictional_output_root(
    monkeypatch,
):
    import ghostcursor.act_cli as act_cli

    captured = []
    expected = object()
    monkeypatch.setattr(act_cli, "plan_draws_a_pointer", lambda _proposal: True)
    monkeypatch.setattr(
        act_cli,
        "execute_act_proposal",
        lambda proposal, **kwargs: captured.append((proposal, kwargs)) or expected,
    )
    proposal = SimpleNamespace(output_path=None)
    presentation = object()
    worker = _ActWorker()

    request = _issue_act_execution_request("add a slide", proposal)
    worker.start(request, presentation=presentation)
    result = _take(worker)

    assert result is expected
    assert captured[0][1]["presentation"] is presentation
    assert captured[0][1]["owned_output_root"] is None


def test_pointer_plan_without_a_ui_thread_surface_refuses_before_execution(
    monkeypatch,
):
    import ghostcursor.act_cli as act_cli

    called = []
    monkeypatch.setattr(act_cli, "plan_draws_a_pointer", lambda _proposal: True)
    monkeypatch.setattr(
        act_cli,
        "execute_act_proposal",
        lambda *_args, **_kwargs: called.append(True),
    )
    worker = _ActWorker()

    request = _issue_act_execution_request(
        "add a slide", SimpleNamespace(output_path=None)
    )
    worker.start(request)
    result = _take(worker)

    assert isinstance(result, RuntimeError)
    assert "no UI-thread presentation surface" in str(result)
    assert called == []


def test_worker_refuses_a_bare_proposal_before_starting_a_thread():
    worker = _ActWorker()

    with pytest.raises(TypeError, match="manager-issued execution request"):
        worker.start(SimpleNamespace(output_path=None))

    assert not worker.running


def test_manager_execution_request_is_one_use(monkeypatch):
    import ghostcursor.act_cli as act_cli

    executed = []
    monkeypatch.setattr(act_cli, "plan_draws_a_pointer", lambda _proposal: False)
    monkeypatch.setattr(
        act_cli,
        "execute_act_proposal",
        lambda proposal, **_kwargs: executed.append(proposal) or object(),
    )
    proposal = SimpleNamespace(output_path=None)
    request = _issue_act_execution_request("build it", proposal)
    first = _ActWorker()

    first.start(request)
    assert _take(first) is not None

    with pytest.raises(RuntimeError, match="already consumed"):
        _ActWorker().start(request)

    assert executed == [proposal]


def test_manager_factory_binds_the_real_overlay_bridge_and_releases_it(monkeypatch):
    """Exercise the production factory, not a lookalike assembled in a test."""

    import ghostcursor.act_overlay as act_overlay
    import ghostcursor.act_runtime as act_runtime
    from ghostcursor.overlay import window as overlay_window

    released = []
    destroyed = []
    captured = []
    real_presenter = act_overlay.overlay_presenter
    monkeypatch.setattr(overlay_window, "create_overlay_window", lambda: 4242)
    monkeypatch.setattr(
        overlay_window,
        "clear_cue",
        lambda hwnd: released.append(hwnd),
    )
    monkeypatch.setattr(
        overlay_window,
        "destroy_overlay_window",
        lambda hwnd: destroyed.append(hwnd),
    )
    monkeypatch.setattr(
        act_overlay,
        "overlay_presenter",
        lambda hwnd, **kwargs: captured.append((hwnd, kwargs))
        or real_presenter(
            hwnd,
            bounds=(0, 0, 1920, 1080),
            pump=lambda: None,
            geometry_check=lambda *_args: (),
            **kwargs,
        ),
    )
    controls = SimpleNamespace(stop_event=threading.Event())

    presentation = _create_manager_act_presentation(controls)

    assert presentation.hwnd == 4242
    assert presentation.surface.overlay is presentation.bridge
    assert act_runtime._trusted_presentation_surface(presentation.surface)
    assert captured[0][0] == 4242
    assert captured[0][1]["keep_running"]() is True

    controls.stop_event.set()
    assert captured[0][1]["keep_running"]() is False
    presentation.close()
    assert released == [4242]
    assert destroyed == [4242]
