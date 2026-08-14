"""A target window whose owner has stopped pumping messages.

This reproduces the failure the whole threading change exists for: an
ordinary "Not Responding" application. A cheap EnumWindows check still sees
the window, but a UIA tree walk against it blocks for ~40 seconds on first
contact and ~10 seconds after — 80x the 0.5s tick ceiling, with no timeout
available to tune.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CHILD = REPO / "tests" / "hung_window.py"


class HungWindow:
    """Runs a child process that shows a window and then stops pumping."""

    HANDSHAKE_TIMEOUT = 5.0  # seconds to wait for "ready" signal

    def __init__(self, title: str = "GhostCursorHungApp") -> None:
        self.title = title
        self.title_re = f".*{title}.*"
        self._child: subprocess.Popen | None = None

    def _kill_and_reap(self) -> None:
        """Kill the child process and wait for it to exit."""
        if self._child:
            try:
                self._child.kill()
            except (OSError, ProcessLookupError):
                pass  # already dead
            try:
                self._child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass  # unkillable, but we tried

    def __enter__(self) -> "HungWindow":
        self._child = subprocess.Popen(
            [sys.executable, "-B", str(CHILD), self.title],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(REPO),
            env=dict(os.environ, PYTHONPATH=str(REPO)),
        )

        try:
            # Read the handshake with a timeout to prevent indefinite blocking
            ready_event = threading.Event()
            handshake_line = [None]  # use list to allow mutation in inner function

            def read_handshake() -> None:
                try:
                    handshake_line[0] = self._child.stdout.readline().strip()
                finally:
                    ready_event.set()

            reader = threading.Thread(target=read_handshake, daemon=True)
            reader.start()

            if not ready_event.wait(timeout=self.HANDSHAKE_TIMEOUT):
                # Timeout: child never sent ready. Do not try to read stderr
                # as it may block if the child is still alive with open pipes.
                raise TimeoutError(
                    f"child did not signal 'ready' within {self.HANDSHAKE_TIMEOUT}s"
                )

            line = handshake_line[0] or ""
            if line != "ready":
                raise AssertionError(f"child did not start: {line!r}")

            time.sleep(0.3)  # let the window settle
            return self
        except BaseException:
            # On any failure (including KeyboardInterrupt), clean up the child
            self._kill_and_reap()
            raise

    def __exit__(self, *exc) -> None:
        self._kill_and_reap()


def test_the_cheap_existence_check_still_sees_a_hung_window():
    """This is why the fast path cannot protect against a hung app."""
    from ghostcursor.perception.uia import windows_matching

    with HungWindow() as hung:
        assert windows_matching(hung.title_re), (
            "the hung window is invisible to EnumWindows, so this fixture "
            "is not reproducing the real failure"
        )


def test_a_uia_walk_against_a_hung_window_blocks_far_past_the_tick_ceiling():
    """The measurement that justifies the whole change."""
    from ghostcursor.perception.uia import iter_elements

    with HungWindow() as hung:
        start = time.perf_counter()
        iter_elements(hung.title_re)
        elapsed = time.perf_counter() - start

    assert elapsed > 2.0, (
        f"the walk took only {elapsed:.2f}s — the fixture is not actually "
        "hanging, so every test built on it proves nothing"
    )


def test_hung_window_cleans_up_child_when_handshake_fails(tmp_path, monkeypatch):
    """Verify no child survives when the handshake fails.

    This ensures that if the child sends wrong handshake or crashes,
    the process is cleaned up and does not poison later test runs.
    """
    # Write a stub child that prints wrong handshake then sleeps (stays alive after error)
    stub_child = tmp_path / "wrong_handshake.py"
    stub_child.write_text(
        'import sys, time; print("error", flush=True); time.sleep(600)'
    )

    # Monkeypatch CHILD to point to the stub
    monkeypatch.setattr("tests.test_hung_window.CHILD", stub_child)

    hung = HungWindow()
    # Call the real __enter__() which should raise AssertionError (wrong handshake)
    with pytest.raises(AssertionError, match="child did not start"):
        hung.__enter__()

    # Verify the child is dead and reaped by the real __enter__
    time.sleep(0.1)
    # Child should be killed and reaped, so poll() returns non-None (the exit code)
    assert hung._child.poll() is not None, "child process should have been cleaned up"


def test_hung_window_times_out_if_child_never_prints_ready(tmp_path, monkeypatch):
    """Verify that handshake timeout raises promptly instead of hanging forever.

    If the child never prints 'ready', the timeout should fire after
    HANDSHAKE_TIMEOUT rather than blocking indefinitely.
    """
    # Write a stub that sleeps well past HANDSHAKE_TIMEOUT without printing
    stub_child = tmp_path / "sleep_forever.py"
    stub_child.write_text("import time; time.sleep(600)")

    # Monkeypatch CHILD to point to the stub
    monkeypatch.setattr("tests.test_hung_window.CHILD", stub_child)

    hung = HungWindow()
    start = time.perf_counter()

    # Call the real __enter__() which should raise TimeoutError
    with pytest.raises(TimeoutError, match="did not signal 'ready'"):
        hung.__enter__()

    elapsed = time.perf_counter() - start

    # Should timeout roughly at HANDSHAKE_TIMEOUT, not hang for minutes
    # Allow generous margin for process startup overhead
    assert (
        HungWindow.HANDSHAKE_TIMEOUT - 0.5 < elapsed < HungWindow.HANDSHAKE_TIMEOUT + 3
    ), f"timeout should be ~{HungWindow.HANDSHAKE_TIMEOUT}s, but took {elapsed:.2f}s"

    # Child should be cleaned up
    assert hung._child.poll() is not None, "child should be cleaned up after timeout"
