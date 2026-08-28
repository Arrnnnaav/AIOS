"""D035 warm-up through the compiled observation source."""
import inspect

from ghostcursor.perception.compiled import build_compiled_perception
from ghostcursor.perception.warmup import DEFAULT_WARMUP_BUDGET_S
from ghostcursor.run import run_tour_for_workflow
from tests.test_compiled_workflow import _workflow


class _Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t


class _Service:
    def __init__(self): self.requests=[]; self.cancels=0; self.grounded=[]
    def request_tier2(self, step): self.requests.append(step)
    def cancel_tier2(self): self.cancels += 1
    def report_tier2_grounded(self, step): self.grounded.append(step)
    def is_alive(self): return True
    def latest(self): return None
    def start(self): pass
    def stop(self): pass


def _source(budget=DEFAULT_WARMUP_BUDGET_S):
    clock = _Clock(); service = _Service(); workflow, _ = _workflow()
    perception = build_compiled_perception(
        workflow, clock, service=service, warmup_budget_s=budget
    )
    return perception.source, service, clock


def test_default_budget_flows_through_to_run_tour():
    assert inspect.signature(run_tour_for_workflow).parameters["warmup_budget_s"].default == DEFAULT_WARMUP_BUDGET_S


def test_a_cold_window_that_grounds_inside_the_budget_never_asks_for_tier2():
    source, service, clock = _source()
    source.note_grounding(0, False, "open_folder")
    clock.t = 1.0
    source.note_grounding(0, True, "open_folder")
    assert service.requests == []
    assert service.grounded == [0]


def test_a_window_that_never_grounds_asks_once_the_budget_expires():
    source, service, clock = _source()
    source.note_grounding(0, False, "open_folder")
    clock.t = DEFAULT_WARMUP_BUDGET_S
    source.note_grounding(0, False, "open_folder")
    assert service.requests == [0]


def test_warm_up_does_not_reopen_after_a_successful_grounding():
    source, service, clock = _source()
    source.note_grounding(0, True, "open_folder")
    source.note_grounding(1, False, "open_folder")
    assert service.requests == [1]


def test_the_budget_parameter_is_what_warm_up_actually_uses():
    source, service, clock = _source(7.0)
    source.note_grounding(0, False, "open_folder")
    clock.t = 6.9
    source.note_grounding(0, False, "open_folder")
    assert service.requests == []
    clock.t = 7.0
    source.note_grounding(0, False, "open_folder")
    assert service.requests == [0]


def test_a_new_compiled_target_gets_its_own_budget():
    first, first_service, first_clock = _source(2.0)
    first.note_grounding(0, False, "open_folder")
    first_clock.t = 3.0
    first.note_grounding(0, False, "open_folder")
    second, second_service, _ = _source(2.0)
    second.note_grounding(0, False, "open_folder")
    assert first_service.requests == [0]
    assert second_service.requests == []
