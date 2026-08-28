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
        #: The one currently-standing request, if any -- set by request_tier2,
        #: cleared by cancel_tier2. Unlike `_tier2_requests` (an append-only
        #: log used to see WHEN a request was made), this is the thing a
        #: standing-request bug actually leaves behind: a request nothing
        #: retracted. `request_tier2` was a no-op append and `cancel_tier2`
        #: was a no-op `pass`, so no assertion here could ever have told a
        #: cancelled request apart from one that was simply never cancelled.
        self.standing: int | None = None

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
        self.standing = step_index

    def cancel_tier2(self, step_index=None):
        self.standing = None

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
        self._stop = threading.Event()
        #: Set by `target()`'s `finally`, so a CLEAN `run_tour` return (DONE,
        #: FAILED, health.check() ending the tour, or the deadline falling
        #: through) is visible to `tick()` too -- not just an exception.
        #: Without this, any of those exits leaves `_done` unfilled forever
        #: and `tick()`'s wait blocks with no output (Important finding 1).
        self._exited = False

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
        def worker_only_hwnd_source(_title_re):
            raise AssertionError("the HWND source ran on run_tour's control thread")

        monkeypatch.setattr(
            run_module,
            "perception_hwnd_source_for",
            lambda _app_id: worker_only_hwnd_source,
        )
        monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: None)
        monkeypatch.setattr(run_module, "escape_pressed", self._stop.is_set)
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
            finally:
                # Covers a CLEAN return too (DONE, FAILED, health ending the
                # tour, or the deadline falling through) -- not just an
                # exception. `tick()` treats `_exited` as loud proof the tour
                # ended mid-tick rather than silently hanging.
                self._exited = True
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

    def tick(self, timeout: float = 10.0, max_pumps: int = 50) -> None:
        """Pump the background `run_tour` thread through outer iterations
        until `grounding.ground` has been called one more time than before,
        then leave it paused right after that iteration.

        On every call after the first, the background thread is already
        parked at the barrier from the PREVIOUS `tick()` -- it must be
        released before this call can wait for the next one, or the two
        threads deadlock each waiting on the other's queue.

        Three properties a bare, unbounded version of this used to lack
        (Important finding 1 on this file's first review):

        * every wait is bounded (`timeout`), so a stalled `run_tour` fails
          loudly instead of hanging CI forever with no output;
        * a CLEAN `run_tour` return -- DONE, FAILED, health ending the tour,
          or the deadline falling through -- is caught via `_exited` and
          raises, rather than leaving `_done` unfilled and the wait blocked;
        * the pump loop itself is bounded (`max_pumps`), so a state machine
          that dwells without ever grounding again (AWAITING_USER_ACTION,
          per run.py's own comment, "dwells for many ticks without
          [calling the grounder]") cannot spin the pump forever -- the
          clock is frozen between `tick()` calls, so nothing else would
          ever stop it.
        """
        start_calls = self._ground_calls
        if not self._started:
            self._started = True
            self._thread.start()
        else:
            self._go.put(True, timeout=timeout)
        for _ in range(max_pumps):
            try:
                self._done.get(timeout=timeout)
            except queue.Empty:
                raise AssertionError(
                    f"run_tour stalled: no sleeper() call in {timeout}s "
                    f"(ground calls {self._ground_calls}, started at {start_calls})"
                )
            if self._thread_exc is not None:
                raise self._thread_exc
            if self._exited:
                raise AssertionError(
                    "run_tour exited before grounding ran again -- the tour "
                    "ended (DONE/FAILED/health/deadline) mid-tick; the "
                    "assertions this tick() call was set up for would have "
                    "measured nothing"
                )
            if self._ground_calls > start_calls:
                return
            self._go.put(True, timeout=timeout)
        raise AssertionError(f"grounder not reached in {max_pumps} outer iterations")

    def close(self, timeout: float = 5.0) -> None:
        if not self._started:
            return
        self._stop.set()
        try:
            self._go.put_nowait(True)
        except queue.Full:
            pass
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            raise AssertionError("run_tour did not stop during warm-up harness teardown")


@pytest.fixture
def warmup_harness(monkeypatch, tmp_path):
    harnesses = []

    def factory(budget_s: float, hwnd: int) -> _WarmupHarness:
        harness = _WarmupHarness(budget_s, hwnd, monkeypatch, tmp_path)
        harnesses.append(harness)
        return harness

    yield factory

    for harness in harnesses:
        harness.close()


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


def test_the_budget_parameter_is_what_warm_up_actually_uses(warmup_harness):
    """A non-default budget, so a hardcoded DEFAULT_WARMUP_BUDGET_S (2.0) at
    the `WarmUp(...)` call site in run.py fails here instead of passing
    everything -- every other test in this file happens to pass budget_s=2.0,
    which is indistinguishable from the default, so none of them can tell
    "the parameter was used" apart from "2.0 was baked in" (D031)."""
    h = warmup_harness(budget_s=0.5, hwnd=1638728)

    h.tick()  # t=0.0  warm-up opens
    h.advance(0.4)
    h.tick()  # t=0.4  inside a 0.5s budget
    inside = list(h.tier2_requests)
    h.advance(0.2)
    h.tick()  # t=0.6  expired
    after = list(h.tier2_requests)

    assert inside == [], "asked before the 0.5s budget expired"
    assert after, "0.5s budget never expired -- 2.0s is hardcoded at the call site"


def test_a_splash_window_does_not_spend_the_real_windows_budget(warmup_harness):
    """The measured Discord case, end to end: 'Discord Updater' (hwnd 329088)
    for ~5s, then the real window (hwnd 1638728) whose tree is ready in 0.92s."""
    h = warmup_harness(budget_s=2.0, hwnd=329088)

    h.tick()  # t=0.0  splash seen
    h.advance(5.0)
    h.tick()  # t=5.0  splash budget long expired -- standing request now open
    assert h.service.standing == 0, "splash never got its expected request"
    h.set_hwnd(1638728)  # the real window replaces it
    h.tier2_requests.clear()
    h.tick()  # t=5.0  real window, first sight
    assert h.service.standing is None, (
        "the splash's standing request was never retracted -- it outlives "
        "the real window's own warm-up and keeps costing capture+OCR"
    )
    h.advance(0.9)
    h.ground_from_now_on()
    h.tick()  # t=5.9  grounds, as measured

    assert h.tier2_requests == [], (
        "the splash's expired budget was reused for the real window"
    )
    assert h.service.standing is None, "grounding succeeded but a request stood"
