"""D035 tier-2 lifecycle through compiled selectors and executor."""
import pytest

from ghostcursor.perception.compiled import CompiledObservationSource, merge_ocr
from ghostcursor.perception.uia import Element, SelectorAmbiguityFault
from ghostcursor.reasoning.compiled_tour import GroundingProvenance, RunOutcome, TickInput, execute_compiled_workflow
from ghostcursor.reasoning.staleness import StalenessLadder
from tests.test_compiled_workflow import _workflow


class _Clock:
    def __init__(self): self.t=0.0
    def __call__(self): return self.t
    def sleep(self, s): self.t += s


class _Renderer:
    def __init__(self): self.sources=[]
    def show(self, grounded, text): self.sources.append(grounded.source)
    def clear(self): pass
    def settle(self): pass


class _Service:
    def __init__(self): self.requests=[]; self.cancels=0; self.grounded=[]
    def request_tier2(self, step): self.requests.append(step)
    def cancel_tier2(self): self.cancels += 1
    def report_tier2_grounded(self, step): self.grounded.append(step)
    def latest(self): return None


def _ocr(name="Open Folder..."):
    return Element(name, "Button", "", (10,20,110,60), source="ocr")


def test_ocr_recovers_a_target_uia_cannot_see_and_it_renders_as_inferred():
    workflow, _ = _workflow(); clock=_Clock(); renderer=_Renderer(); element=_ocr()
    reads=[0]
    def observe():
        reads[0] += 1
        title = "Demo - Visual Studio Code" if reads[0] >= 4 else "Welcome - Visual Studio Code"
        return TickInput(title, {"open_folder":(element,)}, (element,))
    result=execute_compiled_workflow(
        workflow,
        observe=observe,
        renderer=renderer, clock=clock, sleeper=clock.sleep, seconds=3.0,
    )
    assert result.outcome is RunOutcome.PASSED
    assert result.provenance == (GroundingProvenance.OCR,)
    assert renderer.sources[0] == "ocr"


def test_cap_exhaustion_is_a_selector_fault_not_clean_absence():
    workflow, _ = _workflow()
    with pytest.raises(SelectorAmbiguityFault):
        merge_ocr(
            workflow.recipe.plan, {"open_folder": ()},
            (_ocr(), _ocr()), "open_folder",
        )


def test_the_worker_stops_reading_for_a_step_the_tour_has_left():
    workflow, _ = _workflow(); service=_Service(); clock=_Clock()
    source=CompiledObservationSource(service, StalenessLadder(clock=clock), plan=workflow.recipe.plan, clock=clock)
    source.note_grounding(0, False, "open_folder")
    source.note_grounding(1, False, "open_folder")
    assert service.requests == [0, 1]
    assert service.cancels >= 1


def test_a_step_that_grounds_through_uia_stops_reading_the_screen():
    workflow, _ = _workflow(); service=_Service(); clock=_Clock()
    source=CompiledObservationSource(service, StalenessLadder(clock=clock), plan=workflow.recipe.plan, clock=clock)
    source.note_grounding(0, False, "open_folder")
    source.note_grounding(0, True, "open_folder")
    assert service.requests == [0]
    assert service.grounded == [0]
    assert service.cancels >= 1
