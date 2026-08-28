"""D021 through the compiled production composition.

Every test keeps UIA on the perception worker. The executor thread remains
responsible for ESC, health policy and overlay teardown even when the target
window never answers.
"""
import time

from ghostcursor.perception.compiled import build_compiled_perception
from ghostcursor.perception.health import WorkerHealth
from ghostcursor.reasoning.compiled_tour import RunOutcome, TickInput, execute_compiled_workflow
from ghostcursor.reasoning.staleness import StalenessLadder
from tests.test_compiled_workflow import _target, _window, _workflow
from tests.test_hung_window import HungWindow

MAX_TICK_GAP_S = 0.75
MAX_TOTAL_S = 10.0


class _Renderer:
    def show(self, *args): pass
    def clear(self): pass
    def settle(self): pass


class _Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds


def _bound_workflow(hwnd, title="GhostCursorTestApp"):
    workflow, _catalog = _workflow(
        target=_target(_window(hwnd=hwnd, title=title))
    )
    return workflow


def _hung_hwnd(hung):
    from ghostcursor.perception.uia import windows_matching
    matches = windows_matching(hung.title_re)
    assert len(matches) == 1
    return matches[0]


def test_reading_the_slot_stays_fast_while_the_target_is_hung():
    with HungWindow() as hung:
        perception = build_compiled_perception(_bound_workflow(_hung_hwnd(hung)), time.monotonic)
        source, _grounding, stop = perception.start()
        try:
            time.sleep(0.5)
            started = time.perf_counter()
            for _ in range(100): source()
            elapsed = time.perf_counter() - started
        finally:
            stop()
    assert elapsed < 0.5


def test_a_hung_target_never_produces_an_observation_but_does_not_crash():
    with HungWindow() as hung:
        perception = build_compiled_perception(_bound_workflow(_hung_hwnd(hung)), time.monotonic)
        source, _grounding, stop = perception.start()
        try:
            time.sleep(1.0)
            assert source() is None
            assert perception.service.is_alive()
        finally:
            stop()


def test_esc_stops_the_tour_promptly_while_the_target_is_hung(monkeypatch):
    import ghostcursor.run as run_module

    polls = []
    def escape():
        polls.append(time.perf_counter())
        return len(polls) >= 5
    monkeypatch.setattr(run_module, "escape_pressed", escape)

    with HungWindow() as hung:
        started = time.perf_counter()
        rc = run_module._run_compiled_tour(
            _bound_workflow(_hung_hwnd(hung)), seconds=60.0,
            clock=time.monotonic, sleeper=time.sleep, warmup_budget_s=0.0,
            create_overlay=lambda: 0, renderer=_Renderer(),
        )
        elapsed = time.perf_counter() - started

    gaps = [b - a for a, b in zip(polls, polls[1:])]
    assert rc == 1
    assert len(polls) >= 5
    assert max(gaps) < MAX_TICK_GAP_S
    assert elapsed < MAX_TOTAL_S


def test_a_hung_target_does_not_end_the_tour_before_the_health_budget(monkeypatch):
    import ghostcursor.run as run_module

    started = time.monotonic()
    monkeypatch.setattr(run_module, "escape_pressed", lambda: time.monotonic() - started >= 3.0)
    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a))))
    with HungWindow() as hung:
        run_module._run_compiled_tour(
            _bound_workflow(_hung_hwnd(hung)), seconds=20.0,
            clock=time.monotonic, sleeper=time.sleep, warmup_budget_s=0.0,
            create_overlay=lambda: 0, renderer=_Renderer(),
        )
    assert time.monotonic() - started >= 3.0
    assert not any("perception stopped working" in line for line in printed)


class _Service:
    heartbeat = 0
    def __init__(self, *, alive, observation=None):
        self.alive = alive; self.observation = observation; self.restarts = 0
    def latest(self): return self.observation
    def is_alive(self): return self.alive
    def restart(self): self.restarts += 1
    def request_tier2(self, step): pass
    def cancel_tier2(self): pass
    def report_tier2_grounded(self, step): pass


def _source_result(service, *, seconds=40.0):
    clock = _Clock()
    ladder = StalenessLadder(clock=clock)
    health = WorkerHealth(service, ladder, dead_after_s=2.0, slow_after_s=1.0, log=lambda _m: None)
    from ghostcursor.perception.compiled import CompiledObservationSource
    workflow = _bound_workflow(101)
    source = CompiledObservationSource(
        service, ladder, health=health, plan=workflow.recipe.plan,
        clock=clock, started_at=clock(), target_hwnd=101,
    )
    result = execute_compiled_workflow(
        workflow, observe=source, renderer=_Renderer(), clock=clock,
        sleeper=clock.sleep, seconds=seconds,
    )
    return result, service


def test_a_dead_worker_is_named_as_a_perception_failure():
    result, service = _source_result(_Service(alive=False))
    assert result.outcome is RunOutcome.FAILED
    assert "perception stopped working" in result.detail
    assert service.restarts == 1


def test_a_target_hung_on_first_contact_is_named_as_a_perception_failure():
    result, service = _source_result(_Service(alive=True))
    assert result.outcome is RunOutcome.FAILED
    assert "stalled" in result.detail or "never produced" in result.detail
    assert service.restarts == 1


def test_a_genuinely_absent_element_is_still_reported_as_missing():
    clock = _Clock()
    workflow = _bound_workflow(101)
    empty = TickInput(
        title="Welcome - Visual Studio Code",
        selectors={"open_folder": ()}, union=(),
    )
    result = execute_compiled_workflow(
        workflow, observe=lambda: empty, renderer=_Renderer(), clock=clock,
        sleeper=clock.sleep, seconds=20.0,
    )
    assert result.outcome is RunOutcome.FAILED
    assert "cannot find" in result.detail.lower()
    assert "perception" not in result.detail.lower()
