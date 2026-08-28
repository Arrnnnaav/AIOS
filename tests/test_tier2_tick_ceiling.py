"""D020: tier-2 work cannot consume the compiled UI tick."""
import threading
import time

from ghostcursor.perception.compiled import CompiledObservationSource
from ghostcursor.perception.service import Observation
from ghostcursor.reasoning.staleness import StalenessLadder
from ghostcursor.reasoning.verification import Snapshot
from tests.test_compiled_workflow import _workflow

MAX_TICK_GAP_S = 0.5


class _SlowTier2Service:
    def __init__(self):
        self.started=threading.Event(); self.finished=threading.Event()
        self.observation=Observation(Snapshot("Welcome", (), selector_results=(("open_folder", ()),)), (), time.monotonic(), True)
    def latest(self): return self.observation
    def request_tier2(self, step):
        def read():
            self.started.set(); time.sleep(1.0); self.finished.set()
        threading.Thread(target=read, daemon=True).start()
    def cancel_tier2(self): pass
    def report_tier2_grounded(self, step): pass


def test_no_tick_exceeds_the_ceiling_while_tier_2_is_running():
    workflow, _ = _workflow(); service=_SlowTier2Service()
    source=CompiledObservationSource(
        service, StalenessLadder(clock=time.monotonic),
        plan=workflow.recipe.plan, clock=time.monotonic,
    )
    source.note_grounding(0, False, "open_folder")
    assert service.started.wait(0.5)
    started=time.perf_counter()
    for _ in range(100): source()
    elapsed=time.perf_counter()-started
    assert not service.finished.is_set(), "the measurement missed the slow read"
    assert elapsed < MAX_TICK_GAP_S
