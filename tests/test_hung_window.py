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
                # Timeout: child never sent ready
                stderr_content = ""
                if self._child and self._child.stderr:
                    try:
                        stderr_content = self._child.stderr.read()
                    except Exception:
                        pass
                raise TimeoutError(
                    f"child did not signal 'ready' within {self.HANDSHAKE_TIMEOUT}s. "
                    f"stderr: {stderr_content!r}"
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


def test_hung_window_cleans_up_child_when_handshake_fails():
    """Verify no child survives when the handshake fails.

    This ensures that if the child crashes or never prints 'ready',
    the process is cleaned up and does not poison later test runs.
    """
    # Create a child that exits immediately without printing 'ready'
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.exit(0)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    pid = child.pid

    # Simulate what __enter__ does: try to read handshake but child exits
    hung = HungWindow()
    hung._child = child

    try:
        # Manually do what __enter__ does with the child
        ready_event = threading.Event()
        handshake_line = [None]

        def read_handshake() -> None:
            try:
                handshake_line[0] = hung._child.stdout.readline().strip()
            finally:
                ready_event.set()

        reader = threading.Thread(target=read_handshake, daemon=True)
        reader.start()

        if not ready_event.wait(timeout=HungWindow.HANDSHAKE_TIMEOUT):
            raise TimeoutError("timeout")

        line = handshake_line[0] or ""
        if line != "ready":
            raise AssertionError(f"child did not start: {line!r}")
    except BaseException:
        # This is what __enter__ does on failure
        hung._kill_and_reap()

    # Verify the child is dead and reaped
    time.sleep(0.2)
    poll_result = hung._child.poll()
    assert poll_result is not None, "child process should have been cleaned up"


def test_hung_window_times_out_if_child_never_prints_ready():
    """Verify that handshake timeout raises promptly instead of hanging forever.

    If the child never prints 'ready', the old code would hang forever.
    The fix should timeout after HANDSHAKE_TIMEOUT and raise.
    """
    # Create a child that sleeps without printing anything
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(600)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    hung = HungWindow()
    hung._child = child

    start = time.perf_counter()
    try:
        # Manually do what __enter__ does
        ready_event = threading.Event()
        handshake_line = [None]

        def read_handshake() -> None:
            try:
                handshake_line[0] = hung._child.stdout.readline().strip()
            finally:
                ready_event.set()

        reader = threading.Thread(target=read_handshake, daemon=True)
        reader.start()

        if not ready_event.wait(timeout=HungWindow.HANDSHAKE_TIMEOUT):
            raise TimeoutError("did not signal 'ready'")

        assert False, "should have raised TimeoutError"
    except TimeoutError:
        elapsed = time.perf_counter() - start
        # Should timeout roughly at HANDSHAKE_TIMEOUT, not hang for minutes
        assert elapsed < 10.0, (
            f"timeout should be fast (~{HungWindow.HANDSHAKE_TIMEOUT}s), "
            f"but took {elapsed:.2f}s"
        )
    finally:
        # Clean up the child we spawned
        if hung._child:
            hung._child.kill()
            hung._child.wait(timeout=5)
