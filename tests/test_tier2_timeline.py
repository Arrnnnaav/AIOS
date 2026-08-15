"""Tier 2 end to end, as an ordered sequence on an injected clock.

Every component below is unit-tested already. This asserts they compose --
which is the class of bug that has bitten this project three times.
"""

import numpy as np

from ghostcursor.overlay import dpi  # noqa: F401
from ghostcursor.perception.ocr import OcrRead
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
