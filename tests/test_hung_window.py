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
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHILD = REPO / "tests" / "hung_window.py"


class HungWindow:
    """Runs a child process that shows a window and then stops pumping."""

    def __init__(self, title: str = "GhostCursorHungApp") -> None:
        self.title = title
        self.title_re = f".*{title}.*"
        self._child: subprocess.Popen | None = None

    def __enter__(self) -> "HungWindow":
        self._child = subprocess.Popen(
            [sys.executable, "-B", str(CHILD), self.title],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(REPO),
            env=dict(os.environ, PYTHONPATH=str(REPO)),
        )
        line = self._child.stdout.readline().strip()
        assert line == "ready", f"child did not start: {line!r}"
        time.sleep(0.3)  # let the window settle
        return self

    def __exit__(self, *exc) -> None:
        if self._child:
            self._child.kill()
            self._child.wait(timeout=30)


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
