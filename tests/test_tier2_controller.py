"""Cadence, caps, and what happens when the cap runs out.

Everything is driven by an injected clock. No sleeping (D026).
"""

import numpy as np

from ghostcursor.perception.ocr import OcrRead
from ghostcursor.perception.tier2 import Tier2Controller


class FakeClock:
    def __init__(self):
        self.t = 1000.0  # never 0.0: that is the untimestamped sentinel (D023)

    def __call__(self):
        return self.t


class FakeOcr:
    def __init__(self):
        self.calls = 0

    def read(self, frame):
        self.calls += 1
        return [OcrRead(text="BG Remover", bbox=(10, 20, 110, 44))]


def _controller(clock, ocr, frames=None):
    frames = frames or [np.zeros((10, 10, 3), dtype=np.uint8)]
    state = {"i": 0}

    def capture(_title_re):
        frame = frames[min(state["i"], len(frames) - 1)]
        state["i"] += 1
        return frame, (0, 0, 10, 10)

    return Tier2Controller(ocr=ocr, capture=capture, clock=clock)


def test_it_reads_on_first_use():
    clock, ocr = FakeClock(), FakeOcr()
    elements = _controller(clock, ocr).elements_for(0, ".*")
    assert ocr.calls == 1
    assert elements and elements[0].source == "ocr"
    assert elements[0].name == "BG Remover"


def test_an_unchanged_region_is_not_re_read():
    clock, ocr = FakeClock(), FakeOcr()
    controller = _controller(clock, ocr)
    controller.elements_for(0, ".*")
    clock.t += 10.0
    controller.elements_for(0, ".*")
    assert ocr.calls == 1, "an unchanged region was re-read"


def test_the_minimum_interval_holds_even_when_the_region_changes():
    """A loading spinner must not turn 're-run on change' into every tick."""
    clock, ocr = FakeClock(), FakeOcr()
    frames = [np.full((10, 10, 3), v, dtype=np.uint8) for v in (0, 255, 0, 255)]
    controller = _controller(clock, ocr, frames)
    for _ in range(4):
        clock.t += 0.1
        controller.elements_for(0, ".*")
    assert ocr.calls == 1, f"re-read {ocr.calls}x inside the 1.0s floor"


def test_a_changed_region_is_re_read_after_the_interval():
    clock, ocr = FakeClock(), FakeOcr()
    frames = [np.full((10, 10, 3), v, dtype=np.uint8) for v in (0, 255)]
    controller = _controller(clock, ocr, frames)
    controller.elements_for(0, ".*")
    clock.t += 1.5
    controller.elements_for(0, ".*")
    assert ocr.calls == 2


def test_the_run_cap_stops_a_continuously_animating_region():
    clock, ocr = FakeClock(), FakeOcr()
    frames = [np.full((10, 10, 3), (i * 40) % 256, dtype=np.uint8) for i in range(60)]
    controller = _controller(clock, ocr, frames)
    for _ in range(60):
        clock.t += 2.0
        controller.elements_for(0, ".*")
    assert ocr.calls == 20, f"cap breached: {ocr.calls} runs"
    assert controller.exhausted(0) is True


def test_exhaustion_is_terminal_and_stops_reading():
    clock, ocr = FakeClock(), FakeOcr()
    frames = [np.full((10, 10, 3), (i * 40) % 256, dtype=np.uint8) for i in range(60)]
    controller = _controller(clock, ocr, frames)
    for _ in range(40):
        clock.t += 2.0
        controller.elements_for(0, ".*")
    before = ocr.calls
    clock.t += 100.0
    controller.elements_for(0, ".*")
    assert ocr.calls == before, "kept reading after exhaustion"


def test_stickiness_resets_at_the_step_boundary():
    """Otherwise this silently becomes app-wide always-on OCR."""
    clock, ocr = FakeClock(), FakeOcr()
    frames = [np.full((10, 10, 3), (i * 40) % 256, dtype=np.uint8) for i in range(60)]
    controller = _controller(clock, ocr, frames)
    for _ in range(40):
        clock.t += 2.0
        controller.elements_for(0, ".*")
    assert controller.exhausted(0) is True

    clock.t += 2.0
    controller.elements_for(1, ".*")
    assert controller.exhausted(1) is False, "step 1 inherited step 0's exhaustion"


def test_an_absent_window_yields_no_elements_and_costs_no_read():
    clock, ocr = FakeClock(), FakeOcr()
    controller = Tier2Controller(ocr=ocr, capture=lambda _t: None, clock=clock)
    assert controller.elements_for(0, ".*") == []
    assert ocr.calls == 0
