"""Tier 2 end to end, as an ordered sequence on an injected clock.

Every component below is unit-tested already. This asserts they compose --
which is the class of bug that has bitten this project three times.
"""

import numpy as np
import pytest

from ghostcursor.overlay import dpi  # noqa: F401
from ghostcursor.perception.ocr import OcrRead, ocr_available
from ghostcursor.perception.service import Observation
from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.staleness import Freshness
from ghostcursor.reasoning.verification import Snapshot
from tests.test_run_threaded import _fake_overlay, _recipe_file


class FakeClock:
    START = 1000.0

    def __init__(self):
        self.t = self.START

    def __call__(self):
        return self.t

    def sleeper(self, seconds):
        self.t += seconds


class UiaBlindService:
    """A worker that sees the window but never the control the step names."""

    def __init__(self, clock):
        self._clock = clock
        self.heartbeat = 0

    def start(self):
        pass

    def stop(self):
        pass

    def restart(self):
        pass

    def is_alive(self):
        return True

    def latest(self):
        now = self._clock()
        furniture = (Element("Minimise", "Button", "view_1", (0, 0, 20, 20)),)
        return Observation(
            snapshot=Snapshot(title="app", elements=furniture, observed_at=now),
            elements=furniture,
            observed_at=now,
            ok=True,
        )


#: `build_controller` consults the real engine, and only the factory and the
#: capture are faked below. A machine with no language pack is a SUPPORTED
#: configuration (the tour runs on UIA alone), so it must skip rather than go
#: red — same guard as tests/test_ocr_engine.py.
@pytest.mark.skipif(not ocr_available(), reason="no OCR language pack")
def test_ocr_recovers_a_target_uia_cannot_see_and_it_renders_as_inferred(
    tmp_path, monkeypatch
):
    import ghostcursor.run as run_module
    from ghostcursor.perception import appinfo, service as service_module, tier2

    clock = FakeClock()
    calls = _fake_overlay(monkeypatch)
    monkeypatch.setattr(
        service_module, "PerceptionService", lambda *a, **k: UiaBlindService(clock)
    )
    monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: None)
    monkeypatch.setattr(run_module, "escape_pressed", lambda: False)
    monkeypatch.setattr(run_module, "key_was_pressed", lambda vk: False)

    class FakeOcr:
        def read(self, frame):
            return [OcrRead(text="Export", bbox=(10, 20, 110, 44))]

    monkeypatch.setattr(tier2, "_DEFAULT_OCR_FACTORY", lambda: FakeOcr())
    monkeypatch.setattr(
        tier2,
        "_DEFAULT_CAPTURE",
        lambda _t: (np.zeros((10, 10, 3), dtype=np.uint8), (0, 0, 10, 10)),
    )

    printed = []
    monkeypatch.setattr(
        "builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a)))
    )

    run_module.run_tour(
        _recipe_file(tmp_path),
        ".*app.*",
        seconds=8.0,
        clock=clock,
        sleeper=clock.sleeper,
    )

    states = [c[3] for c in calls if c[0] == "set_hint"]
    assert states, f"no hint was ever drawn: {printed}"
    assert Freshness.INFERRED in states, (
        f"an OCR-grounded hint was not drawn as INFERRED: {states}"
    )
    assert Freshness.FRESH not in states, (
        f"a pixel guess was drawn with the authority of a confirmed control: {states}"
    )
    # The FIRST paint, specifically. "INFERRED appears somewhere in the
    # sequence" passed while the renderer's own opening paint used set_hint's
    # default of FRESH and was corrected only later in the same tick — a
    # bright confident ring around a pixel guess, for however long it took a
    # WM_PAINT to land.
    assert states[0] is Freshness.INFERRED, (
        f"the FIRST paint of an OCR-grounded hint was {states[0]!r}, not "
        f"INFERRED — it was drawn at a confidence nobody chose: {states}"
    )


class ExhaustedController:
    """A tier-2 controller that has already spent its run budget.

    Stands in for the real thing so the terminal path can be driven without
    burning 20 real OCR runs: `exhausted()` is unit-tested in
    tests/test_tier2_controller.py, but what run_tour DOES with it is not
    tested anywhere else.
    """

    max_runs_per_step = 20

    def elements_for(self, step_index, title_re):
        return []

    def exhausted(self, step_index):
        return True

    def engaged(self, step_index):
        return True

    def grounded(self, step_index):
        pass


def test_cap_exhaustion_ends_the_step_naming_the_read_failure(tmp_path, monkeypatch):
    """A screen that never stops changing burns the per-step cap.

    Two properties, and the second is the one that changed. The tour must stop
    and say we could not READ the element — saying "cannot find" tells the user
    their element is missing when in fact we gave up reading the screen,
    pointing them at their own application instead of at ours (D024). And it
    must reach that through the GROUNDING GRACE rather than aborting on the
    exhaustion tick: spec §4 says an exhausted step is treated as ungroundable,
    so the last observation goes on ageing normally and the user keeps those
    seconds to act. The tour used to `break` the instant the budget was spent.
    """
    import ghostcursor.run as run_module
    from ghostcursor.perception import appinfo, service as service_module, tier2

    clock = FakeClock()
    _fake_overlay(monkeypatch)
    monkeypatch.setattr(
        service_module, "PerceptionService", lambda *a, **k: UiaBlindService(clock)
    )
    monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: None)
    monkeypatch.setattr(run_module, "escape_pressed", lambda: False)
    monkeypatch.setattr(run_module, "key_was_pressed", lambda vk: False)
    monkeypatch.setattr(tier2, "build_controller", lambda _clock: ExhaustedController())

    printed = []
    monkeypatch.setattr(
        "builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a)))
    )

    from ghostcursor.reasoning.loop import DEFAULT_GROUNDING_GRACE_S

    # Longer than the old 8s, because the tour no longer dies on the
    # exhaustion tick: it has to outlive the grounding grace to fail at all.
    run_module.run_tour(
        _recipe_file(tmp_path),
        ".*app.*",
        seconds=20.0,
        clock=clock,
        sleeper=clock.sleeper,
    )

    elapsed = clock.t - FakeClock.START
    assert elapsed >= DEFAULT_GROUNDING_GRACE_S, (
        "the tour ended after {:.1f}s, before the {:.0f}s grounding grace could "
        "run — an exhausted step aborted the tour instead of feeding the "
        "grace, so the user lost the seconds the ring was still correct "
        "for".format(elapsed, DEFAULT_GROUNDING_GRACE_S)
    )

    stops = [line for line in printed if line.startswith("Stopped: could not read")]
    assert stops, (
        f"an exhausted read budget did not end the tour with a read failure: {printed}"
    )
    assert "'Export'" in stops[0] and "20 attempts" in stops[0], (
        f"the reason did not name the element and the budget it spent: {stops[0]}"
    )
    assert not any("cannot find" in line.lower() for line in printed), (
        "giving up on reading the screen was reported as a missing element, "
        f"pointing the user at their own application: {printed}"
    )
    assert not any("Time limit reached" in line for line in printed), (
        f"the tour ran on instead of ending the exhausted step: {printed}"
    )
