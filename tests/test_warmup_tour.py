"""Warm-up, driven through run_tour on an injected clock.

Mirrors tests/test_freshness_timeline.py -- read that first for the harness
shape. These assert an ORDERED SEQUENCE of tier-2 requests, not an end state
(D026): 'tier 2 is eventually requested' is true even with warm-up disabled.

The harness below reuses `_fake_overlay` and `_recipe_file` from
`tests/test_run_threaded.py`, exactly as `test_freshness_timeline.py` does --
no second driver is invented. What is new here is the ability to step the
real `run_tour` tick loop ONE OUTER ITERATION AT A TIME under external
control (`tick()`), and to move the clock by an arbitrary amount between
ticks (`advance(dt)`) rather than the fixed REFRESH_SECONDS a real
`sleeper` would apply. That is done by making `sleeper` a rendezvous point
between the test thread and a background thread running `run_tour`: each
`tick()` releases the background thread past its last `sleeper` call and
blocks until it reaches the next one.

`tick()` does not correspond 1:1 with a call into the grounder -- the state
machine takes two outer iterations (IDLE -> OBSERVING -> DECIDING) before it
ever calls the grounder for a step, and every grounding failure bounces back
to OBSERVING for another. So `tick()` pumps the background thread through
outer iterations until `grounding.ground` has been called one additional
time, then stops -- which is what lets the docstring-level comments in the
tests below ("t=0.0 grounding fails, warm-up opens") hold literally.
"""

import queue
import threading

import ghostcursor.run as run_module
import pytest
from ghostcursor.overlay import dpi  # noqa: F401  DPI awareness before any window
from ghostcursor.perception.service import Observation
from ghostcursor.perception.warmup import DEFAULT_WARMUP_BUDGET_S
from ghostcursor.reasoning.verification import Snapshot
from ghostcursor.perception.uia import Element
from tests.test_run_threaded import _fake_overlay, _recipe_file

#: Matches the recipe's claimed target name, so grounding succeeds at rung 2.
EXPORT = Element(
    name="Export",
    control_type="Button",
    automation_id="1001",
    bbox=(100, 100, 200, 150),
    path=("Button",),
)


class _FakeClock:
    """One clock, mutated only by the harness's `advance()`. Handed to
    `run_tour` as its `clock`, so `WarmUp` (constructed inside `run_tour`
    with that same `clock`) never drifts from what the test controls."""

    #: Not 0.0 -- see FakeClock.START in test_freshness_timeline.py for why:
    #: observed_at == 0.0 is the sentinel for "untimestamped".
    START = 1000.0

    def __init__(self):
        self.t = self.START

    def __call__(self) -> float:
        return self.t


class _ScriptedService:
    """A perception worker whose grounding elements and target hwnd the test
    controls directly, and which records every `request_tier2` call."""

    def __init__(self, clock, hwnd, tier2_requests):
        self._clock = clock
        self.hwnd = hwnd
        self.grounding_enabled = False
        self.heartbeat = 1
        self.restarts = 0
        self._tier2_requests = tier2_requests

    def start(self):
        pass

    def stop(self):
        pass

    def restart(self):
        self.restarts += 1

    def is_alive(self):
        return True

    def request_tier2(self, step_index):
        self._tier2_requests.append(step_index)

    def cancel_tier2(self, step_index=None):
        pass

    def report_tier2_grounded(self, step_index):
        pass

    def latest(self):
        elements = (EXPORT,) if self.grounding_enabled else ()
        now = self._clock()
        return Observation(
            snapshot=Snapshot(title="app", elements=elements, observed_at=now),
            elements=elements,
            observed_at=now,
            ok=True,
            target_hwnd=self.hwnd,
        )


class _WarmupHarness:
    def __init__(self, budget_s, hwnd, monkeypatch, tmp_path):
        self.tier2_requests: list[int] = []
        self.clock = _FakeClock()
        self.service = _ScriptedService(self.clock, hwnd, self.tier2_requests)

        self._go: "queue.Queue[bool]" = queue.Queue(maxsize=1)
        self._done: "queue.Queue[bool]" = queue.Queue(maxsize=1)
        self._ground_calls = 0
        self._thread_exc: BaseException | None = None
        self._started = False

        # Spy on grounding.ground rather than replacing it: real grounding
        # logic decides success/failure from `self.service.grounding_enabled`
        # via which elements are in the observation, and the spy is only
        # the synchronization signal `tick()` needs to know a DECIDING
        # state has actually run this pump.
        from ghostcursor.reasoning import grounding as grounding_module

        real_ground = grounding_module.ground

        def spy_ground(*args, **kwargs):
            self._ground_calls += 1
            return real_ground(*args, **kwargs)

        monkeypatch.setattr(grounding_module, "ground", spy_ground)

        _fake_overlay(monkeypatch)
        from ghostcursor.perception import appinfo
        from ghostcursor.perception import service as service_module

        monkeypatch.setattr(
            service_module, "PerceptionService", lambda *a, **k: self.service
        )
        monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: None)
        monkeypatch.setattr(run_module, "escape_pressed", lambda: False)
        monkeypatch.setattr(run_module, "key_was_pressed", lambda vk: False)
        monkeypatch.setattr("builtins.print", lambda *a, **k: None)
        monkeypatch.setattr(
            "ghostcursor.perception.health.print", lambda *a, **k: None, raising=False
        )

        recipe_path = _recipe_file(tmp_path)

        def sleeper(_duration):
            # The barrier: report this outer iteration finished, then wait
            # for the test to allow the next one. Deliberately does NOT
            # advance the clock -- only `advance()` does that.
            self._done.put(True)
            self._go.get()

        def target():
            try:
                run_module.run_tour(
                    recipe_path,
                    ".*app.*",
                    seconds=1_000_000.0,
                    clock=self.clock,
                    sleeper=sleeper,
                    warmup_budget_s=budget_s,
                )
            except BaseException as exc:  # surfaced by the next tick()
                self._thread_exc = exc
                try:
                    self._done.put_nowait(True)
                except queue.Full:
                    pass

        self._thread = threading.Thread(target=target, daemon=True)

    def set_hwnd(self, h: int) -> None:
        self.service.hwnd = h

    def ground_from_now_on(self) -> None:
        self.service.grounding_enabled = True

    def stop_grounding(self) -> None:
        self.service.grounding_enabled = False

    def advance(self, dt: float) -> None:
        self.clock.t += dt

    def tick(self) -> None:
        """Pump the background `run_tour` thread through outer iterations
        until `grounding.ground` has been called one more time than before,
        then leave it paused right after that iteration.

        On every call after the first, the background thread is already
        parked at the barrier from the PREVIOUS `tick()` -- it must be
        released before this call can wait for the next one, or the two
        threads deadlock each waiting on the other's queue.
        """
        start_calls = self._ground_calls
        if not self._started:
            self._started = True
            self._thread.start()
        else:
            self._go.put(True)
        while True:
            self._done.get()
            if self._thread_exc is not None:
                raise self._thread_exc
            if self._ground_calls > start_calls:
                return
            self._go.put(True)


@pytest.fixture
def warmup_harness(monkeypatch, tmp_path):
    def factory(budget_s: float, hwnd: int) -> _WarmupHarness:
        return _WarmupHarness(budget_s, hwnd, monkeypatch, tmp_path)

    return factory


def test_default_budget_flows_through_to_run_tour():
    import inspect

    default = (
        inspect.signature(run_module.run_tour).parameters["warmup_budget_s"].default
    )
    assert default == DEFAULT_WARMUP_BUDGET_S


def test_a_cold_window_that_grounds_inside_the_budget_never_asks_for_tier2(
    warmup_harness,
):
    """The whole point. VS Code grounded 0.57s after its window appeared and
    Discord 0.92s; both are inside a 2.0s budget, so neither should ever have
    reached OCR."""
    h = warmup_harness(budget_s=2.0, hwnd=1638728)

    h.tick()  # t=0.0  grounding fails, warm-up opens
    h.advance(0.5)
    h.tick()  # t=0.5  still failing, still inside the budget
    h.ground_from_now_on()
    h.advance(0.4)
    h.tick()  # t=0.9  UIA answers, as measured

    assert h.tier2_requests == [], "escalated to OCR while UIA was still coming"


def test_a_window_that_never_grounds_asks_once_the_budget_expires(warmup_harness):
    h = warmup_harness(budget_s=2.0, hwnd=1638728)

    h.tick()  # t=0.0
    h.advance(1.9)
    h.tick()  # t=1.9  inside
    inside = list(h.tier2_requests)
    h.advance(0.2)
    h.tick()  # t=2.1  expired
    after = list(h.tier2_requests)

    assert inside == [], "asked before the budget expired"
    assert after, "never asked after the budget expired -- tier 2 is dead"


def test_warm_up_does_not_reopen_after_a_successful_grounding(warmup_harness):
    """Closes permanently on first success: a LATER step that fails to ground
    must escalate immediately, with no second allowance."""
    h = warmup_harness(budget_s=2.0, hwnd=1638728)

    h.tick()
    h.ground_from_now_on()
    h.advance(0.3)
    h.tick()  # grounds -> warm-up closes
    h.stop_grounding()
    h.advance(0.1)
    h.tick()  # fails again, 0.1s later

    assert h.tier2_requests, "a second allowance was granted after the tree was proven"


def test_a_splash_window_does_not_spend_the_real_windows_budget(warmup_harness):
    """The measured Discord case, end to end: 'Discord Updater' (hwnd 329088)
    for ~5s, then the real window (hwnd 1638728) whose tree is ready in 0.92s."""
    h = warmup_harness(budget_s=2.0, hwnd=329088)

    h.tick()  # t=0.0  splash seen
    h.advance(5.0)
    h.tick()  # t=5.0  splash budget long expired
    h.set_hwnd(1638728)  # the real window replaces it
    h.tier2_requests.clear()
    h.tick()  # t=5.0  real window, first sight
    h.advance(0.9)
    h.ground_from_now_on()
    h.tick()  # t=5.9  grounds, as measured

    assert h.tier2_requests == [], (
        "the splash's expired budget was reused for the real window"
    )
