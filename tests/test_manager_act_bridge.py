"""Manager Act worker wiring that does not require a live Win32 window."""

from __future__ import annotations

import time
from types import SimpleNamespace

from ghostcursor.manager import _ActWorker


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

    worker.start(proposal, presentation=presentation)
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

    worker.start(SimpleNamespace(output_path=None))
    result = _take(worker)

    assert isinstance(result, RuntimeError)
    assert "no UI-thread presentation surface" in str(result)
    assert called == []
