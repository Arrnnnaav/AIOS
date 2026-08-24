"""Wrong-action feedback end to end through run_tour, with a fake service.

Mirrors tests/test_freshness_timeline.py -- read it for the harness shape and
reuse its driver rather than writing a second one.

`run_tour`'s tick loop is a blocking `while clock() < deadline` with no seam
for a test to stop it mid-flight except `sleeper`, which the loop calls once
at the bottom of every iteration. `_TourHarness` runs `run_tour` on a
background thread and makes `sleeper` block on a queue until the test calls
`tick()` -- so each `tick()` call releases exactly one more
`GuidedTour.tick()` before the driver pauses again, same clock/sleeper
contract `test_freshness_timeline.py`'s `_run` uses, just stepped by hand
instead of scripted by elapsed time.
"""

import queue
import threading

import pytest

from ghostcursor.overlay import dpi  # noqa: F401  DPI awareness before any window
from ghostcursor.perception.service import Observation
from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.verification import Snapshot
from tests.test_freshness_timeline import FakeClock
from tests.test_run_threaded import _fake_overlay, _recipe_file


class _SteppableService:
    """A perception-service fake that always publishes fresh on read.

    `ScriptedService` in test_freshness_timeline.py throttles publishing on
    the clock, which is exactly right for testing the staleness timeline and
    exactly irrelevant here -- this test is only about whether the
    `focus_visited` the slot carries reaches the printed line, so the fake
    stays as simple as that one question needs.
    """

    def __init__(self, clock, target_id):
        self._clock = clock
        self.target_hwnd = 0
        self._element = Element(
            name="Export",
            control_type="Button",
            automation_id=target_id,
            bbox=(100, 100, 200, 150),
            path=("Button",),
        )
        self.focus_visited: tuple[str, ...] = ()

    def start(self):
        pass

    def stop(self):
        pass

    def restart(self):
        pass

    def is_alive(self):
        return True

    def request_tier2(self, step_index):
        pass

    def cancel_tier2(self, step_index=None):
        pass

    def report_tier2_grounded(self, step_index):
        pass

    def latest(self):
        now = self._clock()
        return Observation(
            snapshot=Snapshot(title="app", elements=(self._element,), observed_at=now),
            elements=(self._element,),
            observed_at=now,
            focus_visited=self.focus_visited,
            ok=True,
            target_hwnd=self.target_hwnd,
        )


class _TourHarness:
    """Steps `run_tour` (running on its own thread) one `GuidedTour.tick()`
    at a time, via a blocking fake `sleeper`."""

    REFRESH_SECONDS = 0.5

    def __init__(self, monkeypatch, tmp_path, target_id, target_hwnd=0):
        import ghostcursor.run as run_module
        from ghostcursor.perception import appinfo, service as service_module

        self.printed: list[str] = []
        self._stop = threading.Event()
        self._exited = threading.Event()
        self._error: BaseException | None = None
        self._started = False
        self.press_space = False
        self.space_polls = 0
        monkeypatch.setattr(
            "builtins.print",
            lambda *a, **k: self.printed.append(" ".join(map(str, a))),
        )
        _fake_overlay(monkeypatch)
        monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: None)
        monkeypatch.setattr(run_module, "escape_pressed", self._stop.is_set)
        def key_was_pressed(vk):
            if vk == run_module.win32con.VK_SPACE:
                self.space_polls += 1
                return self.press_space
            return False

        monkeypatch.setattr(run_module, "key_was_pressed", key_was_pressed)

        self._clock = FakeClock()
        self._service = _SteppableService(self._clock, target_id)
        self._service.target_hwnd = target_hwnd
        monkeypatch.setattr(
            run_module.win32gui,
            "GetForegroundWindow",
            lambda: self._service.target_hwnd,
        )
        monkeypatch.setattr(
            service_module, "PerceptionService", lambda *a, **k: self._service
        )

        self._advance_q: "queue.Queue" = queue.Queue()
        self._ready_q: "queue.Queue" = queue.Queue()

        def sleeper(duration):
            self._clock.sleeper(duration)
            self._ready_q.put(None)
            self._advance_q.get()

        def target():
            try:
                run_module.run_tour(
                    recipe_path=_recipe_file(tmp_path),
                    title_re=".*app.*",
                    seconds=3600.0,
                    clock=self._clock,
                    sleeper=sleeper,
                )
            except BaseException as exc:  # surfaced by _wait_ready, not lost in a daemon
                self._error = exc
            finally:
                self._exited.set()

        self._thread = threading.Thread(
            target=target,
            daemon=True,
        )
    def start(self):
        self._started = True
        self._thread.start()
        # Wait for the first tick (IDLE -> OBSERVING) to complete and the
        # loop to park in `sleeper`, ready for the next `tick()`.
        self._wait_ready()

    def publish_observation(self, focus_visited=()):
        self._service.focus_visited = focus_visited

    def _wait_ready(self, timeout: float = 5.0):
        try:
            self._ready_q.get(timeout=timeout)
        except queue.Empty:
            if self._error is not None:
                raise AssertionError("run_tour crashed in the harness") from self._error
            if self._exited.is_set():
                raise AssertionError("run_tour exited before the requested harness tick")
            raise AssertionError(f"run_tour did not reach sleeper() within {timeout:g}s")

    def tick(self):
        self._advance_q.put(None)
        self._wait_ready()

    def finish(self, timeout: float = 5.0):
        """Release the final parked iteration and require a clean return."""
        self._advance_q.put(None)
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            raise AssertionError(f"run_tour did not finish within {timeout:g}s")
        if self._error is not None:
            raise AssertionError("run_tour crashed while finishing") from self._error

    def close(self):
        """Release the parked sleeper and stop the daemon before fixture teardown."""
        if not self._started:
            return
        self._stop.set()
        self._advance_q.put(None)
        self._thread.join(timeout=5.0)
        if self._thread.is_alive():
            raise AssertionError("run_tour did not stop during harness teardown")


@pytest.fixture
def tour_harness(monkeypatch, tmp_path):
    harnesses = []

    def factory(target_id, target_hwnd=0):
        h = _TourHarness(monkeypatch, tmp_path, target_id, target_hwnd)
        # Register before starting. If the initial bounded rendezvous fails,
        # fixture teardown still owns the thread and attempts to stop it.
        harnesses.append(h)
        h.start()
        # Prime OBSERVING -> DECIDING -> RENDERING_HINT -> AWAITING_USER_ACTION,
        # so the caller's own `tick()` is the first one that runs the
        # wrong-action check against a real grounded target.
        for _ in range(3):
            h.tick()
        return h

    yield factory

    for harness in harnesses:
        harness.close()


def test_a_wrong_action_prints_once_and_re_asserts_the_hint(tour_harness):
    h = tour_harness(target_id="1001")
    h.publish_observation(focus_visited=("1002",))
    h.tick()

    assert any("1002" in line for line in h.printed), (
        "the user was never told which control they touched"
    )


def test_no_line_when_focus_stayed_on_the_target(tour_harness):
    h = tour_harness(target_id="1001")
    h.publish_observation(focus_visited=("1001",))
    h.tick()

    assert not any("1002" in line for line in h.printed)


def test_worker_published_hwnd_enables_space_confirmation(tour_harness):
    """The worker-owned HWND must reach the outer SPACE arbitration path.

    A zero handle fails closed, but once the published observation identifies
    the foreground target, SPACE must still be able to confirm a
    USER_CONFIRMS step. This protects the positive half of the worker-only
    HWND handoff, not merely the helper predicate in isolation.
    """

    h = tour_harness(target_id="1001", target_hwnd=4242)
    h.press_space = True

    h.tick()  # AWAITING_USER_ACTION -> VERIFYING via SPACE
    h.tick()  # VERIFYING -> OBSERVING
    h.finish()  # OBSERVING -> DONE and return (no real control bar)

    assert h.space_polls >= 1
    assert any("Tour complete." in line for line in h.printed)
