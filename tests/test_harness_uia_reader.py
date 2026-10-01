"""The live UIA reader against a real window (interactive lane, D025)."""

from __future__ import annotations

import threading
import time

import pytest

from tests.uia_app import SyntheticApp

pytestmark = pytest.mark.interactive


def test_the_reader_returns_real_controls_with_identity_off_the_ui_thread():
    from ghostcursor.harness.uia_reader import is_minimized, read_window

    with SyntheticApp(title="OrbynHarnessReader") as app:
        result: dict = {}

        def worker():
            # UIA is apartment-bound; the read runs on its own thread (D021)
            # while this thread pumps the window it reads.
            import pythoncom

            pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
            try:
                result["value"] = read_window(app.hwnd, budget_s=5.0)
            finally:
                pythoncom.CoUninitialize()

        thread = threading.Thread(target=worker)
        thread.start()
        deadline = time.monotonic() + 10.0
        while thread.is_alive() and time.monotonic() < deadline:
            app.pump()
            time.sleep(0.005)
        thread.join(timeout=1.0)

        rect, controls, timed_out = result["value"]
        assert rect is not None and not timed_out
        assert not is_minimized(app.hwnd)
        buttons = [c for c in controls if c.control_type == "Button"]
        assert buttons, [c.control_type for c in controls]
        assert all(c.runtime_id for c in buttons)


def test_a_vanished_window_reads_as_nothing():
    from ghostcursor.harness.uia_reader import read_window

    rect, controls, timed_out = read_window(0x7FFFFFF0, budget_s=1.0)
    assert (rect, controls, timed_out) == (None, (), False)
