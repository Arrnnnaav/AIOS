"""D026/D027 staleness through the compiled observation/renderer path."""
from ghostcursor.perception.compiled import CompiledObservationSource
from ghostcursor.perception.service import Observation
from ghostcursor.reasoning.compiled_tour import execute_compiled_workflow
from ghostcursor.reasoning.renderer import OverlayRenderer
from ghostcursor.reasoning.staleness import Freshness, StalenessLadder
from ghostcursor.reasoning.verification import Snapshot
from ghostcursor.perception.uia import Element
from tests.test_compiled_workflow import _workflow


class _Clock:
    def __init__(self): self.t=0.0
    def __call__(self): return self.t
    def sleep(self, s): self.t += s


class _Overlay:
    def __init__(self): self.states=[]
    def set_hint(self, hwnd, x, y, radius=None, freshness=None): self.states.append(freshness)
    def clear_hint(self, hwnd): self.states.append(Freshness.HIDDEN)


class _Service:
    def __init__(self, observation=None): self.observation=observation
    def latest(self): return self.observation


def _observation(at=0.0):
    element=Element("Open Folder...", "Button", "open", (10,20,110,60))
    snapshot=Snapshot(
        "Welcome - Visual Studio Code", (element,),
        selector_results=(("open_folder", (element,)),),
    )
    return Observation(snapshot, (element,), at, True)


def _assembled():
    clock=_Clock(); service=_Service(_observation()); ladder=StalenessLadder(clock=clock)
    workflow, _ = _workflow()
    source=CompiledObservationSource(service, ladder, plan=workflow.recipe.plan, clock=clock)
    overlay=_Overlay(); renderer=OverlayRenderer(1, freshness_source=ladder.freshness, overlay=overlay)
    return workflow, source, renderer, overlay, clock, service


def test_a_hang_dims_then_hides_then_restores_the_hint():
    workflow, source, renderer, overlay, clock, service=_assembled()
    def sleep(seconds):
        clock.sleep(seconds)
        if clock.t >= 5.5:
            service.observation = _observation(clock.t)
    result=execute_compiled_workflow(
        workflow, observe=source, renderer=renderer, clock=clock,
        sleeper=sleep, seconds=6.5,
    )
    assert Freshness.FRESH in overlay.states
    assert Freshness.DIMMED in overlay.states
    assert Freshness.HIDDEN in overlay.states
    hidden = overlay.states.index(Freshness.HIDDEN)
    assert Freshness.FRESH in overlay.states[hidden + 1:]
    assert result.timing["ended_s"] >= 6.5


def test_regression_feeding_the_ladder_on_every_read_never_dims():
    workflow, source, renderer, overlay, clock, _service=_assembled()
    execute_compiled_workflow(
        workflow, observe=source, renderer=renderer, clock=clock,
        sleeper=clock.sleep, seconds=3.0,
    )
    assert Freshness.DIMMED in overlay.states


def test_regression_health_does_not_end_the_tour_before_the_first_observation():
    clock=_Clock(); ladder=StalenessLadder(clock=clock); service=_Service(None)
    source=CompiledObservationSource(service, ladder, health=None, clock=clock)
    source.arm()
    assert source() is None
    clock.t=1.0
    assert source() is None
