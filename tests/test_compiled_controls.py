"""Progress reporting on the compiled control rail, without a desktop.

`CompiledTourControls` takes its bar API by injection, so its status logic is
pure and belongs in the fast lane. `test_bar.py` is desktop-bound as a whole
module (see `tests/conftest.py`), and lane ownership is central there rather
than scattered through per-test decorators -- so these live here instead of
being marked out of that module one at a time.
"""

from __future__ import annotations

from types import SimpleNamespace

from ghostcursor.run import CompiledTourControls


class _BarApi:
    """Records what the rail was told to display, and nothing else."""

    def __init__(self):
        self.requests = SimpleNamespace(
            stop_requested=False, pause_requested=False, ask_requested=False
        )
        self.statuses = []
        self.destroyed = []

    def bar_state(self, hwnd):
        return self.requests

    def clear_requests(self, hwnd):
        self.requests = SimpleNamespace(
            stop_requested=False, pause_requested=False, ask_requested=False
        )

    def set_status(self, hwnd, text):
        self.statuses.append(text)

    def destroy_bar_window(self, hwnd):
        self.destroyed.append(hwnd)


def _controls(api):
    return CompiledTourControls(
        42, bar_api=api, pump_messages=lambda: None, escape_source=lambda: False
    )

def test_the_rail_names_the_step_it_was_told_about():
    api = _BarApi()
    controls = _controls(api)

    controls.report_step(0, 3)
    assert api.statuses[-1] == "Step 1 of 3"
    controls.report_step(2, 3)
    assert api.statuses[-1] == "Step 3 of 3"


def test_resuming_restores_the_step_not_the_word_running():
    """The executor reports on CHANGE, so nothing re-announces after a resume.

    Writing "Running" here would leave the rail silent about progress until
    the next step started -- and on the last step, until the tour ended.
    """
    api = _BarApi()
    controls = _controls(api)
    controls.report_step(1, 4)

    api.requests.pause_requested = True
    controls.poll()
    assert controls.should_pause() is True
    assert api.statuses[-1] == "Paused"

    api.requests.pause_requested = True
    controls.poll()
    assert controls.should_pause() is False
    assert api.statuses[-1] == "Step 2 of 4"


def test_a_step_reported_while_paused_waits_for_the_resume():
    """ "Paused" is the true state; the step number is what comes back after."""
    api = _BarApi()
    controls = _controls(api)
    api.requests.pause_requested = True
    controls.poll()

    controls.report_step(2, 5)
    assert api.statuses[-1] == "Paused", "the pause state was overwritten"

    api.requests.pause_requested = True
    controls.poll()
    assert api.statuses[-1] == "Step 3 of 5"


def test_a_requested_stop_keeps_its_own_message():
    """ "Stopping…" is the more urgent fact, and the rail must not look deaf."""
    api = _BarApi()
    controls = _controls(api)
    api.requests.stop_requested = True
    controls.poll()
    assert api.statuses[-1] == "Stopping…"

    controls.report_step(1, 2)
    assert api.statuses[-1] == "Stopping…"
