"""Tier 2 end to end, as an ordered sequence on an injected clock.

Every component below is unit-tested already. This asserts they compose --
which is the class of bug that has bitten this project three times.
"""

import numpy as np
import pytest

from ghostcursor.overlay import dpi  # noqa: F401
from ghostcursor.perception.ocr import OcrRead, ocr_available
from ghostcursor.perception.service import Observation, PerceptionService
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


class UiaBlindService(PerceptionService):
    """A worker that sees the window but never the control the step names.

    Subclasses the real service rather than reimplementing it, because tier 2
    now runs on the WORKER side: the request slot, the `grounded` one-shot and
    `_tier2_payload` are the real ones, and only the UIA walk and the thread
    are replaced. `latest()` synthesises one worker iteration per clock
    instant -- the payload is computed once per tick and cached, exactly as a
    real worker publishes once per loop -- so a tour driven on a fake clock
    still exercises the real request/publish plumbing.
    """

    def __init__(self, clock, tier2=None):
        super().__init__(".*app.*", walker=lambda _t: [], clock=clock, tier2=tier2)
        self._clock_fn = clock
        self._cached_at = None
        self._cached = ((), -1, False, False, 0)

    def start(self):
        pass

    def stop(self, timeout=2.0):
        pass

    def restart(self):
        pass

    def is_alive(self):
        return True

    def latest(self):
        now = self._clock_fn()
        if self._cached_at != now:
            self._cached_at = now
            self._cached = self._tier2_payload()
        ocr = self._cached
        furniture = (Element("Minimise", "Button", "view_1", (0, 0, 20, 20)),)
        return Observation(
            snapshot=Snapshot(title="app", elements=furniture, observed_at=now),
            elements=furniture,
            observed_at=now,
            ok=True,
            ocr_elements=ocr[0],
            tier2_step=ocr[1],
            tier2_engaged=ocr[2],
            tier2_exhausted=ocr[3],
            tier2_max_runs=ocr[4],
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
        service_module,
        "PerceptionService",
        lambda *a, **k: UiaBlindService(clock, k.get("tier2")),
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
        service_module,
        "PerceptionService",
        lambda *a, **k: UiaBlindService(clock, k.get("tier2")),
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
# ---------------------------------------------------------------------------
# A tier-2 request is a STANDING COST, and only the UI thread can end it.
# ---------------------------------------------------------------------------


class RecordingController:
    """A tier-2 controller that records when it was asked to read, and for
    which step, on the tour's own clock."""

    max_runs_per_step = 20

    def __init__(self, clock, elements):
        self.clock = clock
        self.elements = list(elements)
        self.reads: list[tuple[int, float]] = []

    def elements_for(self, step_index, title_re):
        self.reads.append((step_index, self.clock()))
        return self.elements if step_index == 0 else []

    def exhausted(self, step_index):
        return False

    def engaged(self, step_index):
        return any(step == step_index for step, _ in self.reads)

    def grounded(self, step_index):
        pass


def _two_step_recipe_file(tmp_path):
    """Step 1 is invisible to UIA and must be read; step 2 is a plain UIA
    control. Step 2 never verifies, so the tour dwells on it -- which is the
    situation that exposes the leak: AWAITING_USER_ACTION calls no grounder
    for many ticks, so nothing overwrites a stale request.
    """
    import json

    path = tmp_path / "two_step_recipe.json"
    path.write_text(
        json.dumps(
            {
                "app_id": "leaky",
                "intent": "tier 2 cancellation",
                "steps": [
                    {
                        "user_action": "click",
                        "target_descriptor": {"claimed": {"name": "Export"}},
                        "instruction_text": "Click Export.",
                        "verification_rule": {"kind": "user_confirms", "args": {}},
                        "risk": "normal",
                    },
                    {
                        "user_action": "click",
                        "target_descriptor": {"claimed": {"name": "Next"}},
                        "instruction_text": "Click Next.",
                        "verification_rule": {
                            "kind": "element_appears",
                            "args": {
                                "target_descriptor": {
                                    "name": "NothingWillEverAppearHere"
                                }
                            },
                        },
                        "risk": "normal",
                    },
                ],
            }
        )
    )
    return str(path)


class HalfBlindService(UiaBlindService):
    """UIA sees the second step's control and never the first step's."""

    NEXT = Element("Next", "Button", "next_1", (200, 200, 260, 220))

    def latest(self):
        observation = super().latest()
        return Observation(
            snapshot=Snapshot(
                title="app",
                elements=(self.NEXT,),
                observed_at=observation.observed_at,
            ),
            elements=(self.NEXT,),
            observed_at=observation.observed_at,
            ok=True,
            ocr_elements=observation.ocr_elements,
            tier2_step=observation.tier2_step,
            tier2_engaged=observation.tier2_engaged,
            tier2_exhausted=observation.tier2_exhausted,
            tier2_max_runs=observation.tier2_max_runs,
        )


def test_the_worker_stops_reading_for_a_step_the_tour_has_left(tmp_path, monkeypatch):
    """The blocker: a request outlives the step that made it.

    Step 1 fails UIA grounding and is recovered by OCR. Step 2 grounds through
    UIA alone and needs no reading at all -- yet nothing ended step 1's
    request, so the worker went on paying capture plus OCR (0.14-0.23s, as
    often as the 1.0s floor allows) for a step the user had already left,
    delaying the UIA observations of the step they are actually on and pushing
    the staleness ladder toward DIMMED. The 20-run cap is not a backstop: a
    `grounded` report consumed after the advance resets even that.
    """
    import ghostcursor.run as run_module
    from ghostcursor.overlay import window as real_window
    from ghostcursor.perception import appinfo, service as service_module, tier2

    clock = FakeClock()
    _fake_overlay(monkeypatch)
    hints: list[tuple[int, float]] = []
    monkeypatch.setattr(
        real_window,
        "set_hint",
        lambda hwnd, x, y, radius=None, freshness=None: hints.append((x, clock.t)),
    )
    monkeypatch.setattr(
        service_module,
        "PerceptionService",
        lambda *a, **k: HalfBlindService(clock, k.get("tier2")),
    )
    monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: None)
    monkeypatch.setattr(run_module, "escape_pressed", lambda: False)
    # Space is polled only while a step is actually awaiting a confirmation
    # (`should_poll_space`), so this advances step 1 and nothing else.
    monkeypatch.setattr(run_module, "key_was_pressed", lambda vk: True)

    ocr_element = Element(
        name="Export",
        control_type="",
        automation_id="",
        bbox=(10, 20, 110, 44),
        path=(),
        source="ocr",
    )
    controller = RecordingController(clock, [ocr_element])
    monkeypatch.setattr(tier2, "build_controller", lambda _clock: controller)

    printed = []
    monkeypatch.setattr(
        "builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a)))
    )

    run_module.run_tour(
        _two_step_recipe_file(tmp_path),
        ".*app.*",
        seconds=20.0,
        clock=clock,
        sleeper=clock.sleeper,
    )

    assert any(step == 0 for step, _ in controller.reads), (
        f"tier 2 never read for the first step at all: {controller.reads} {printed}"
    )
    next_centre = (HalfBlindService.NEXT.bbox[0] + HalfBlindService.NEXT.bbox[2]) // 2
    advanced_at = next((t for x, t in hints if x == next_centre), None)
    assert advanced_at is not None, (
        f"the tour never reached the second step, so nothing was asserted: {printed}"
    )

    leaked = [(step, t) for step, t in controller.reads if t >= advanced_at]
    assert leaked == [], (
        f"the worker was still reading the screen for step {leaked[0][0] + 1} "
        f"after the tour moved on ({len(leaked)} reads from t={advanced_at:.2f}): "
        "a standing request outlived its step, so every one of those is "
        "capture + OCR delaying the current step's UIA observations"
    )


def test_a_step_that_grounds_through_uia_stops_reading_the_screen(
    tmp_path, monkeypatch
):
    """The other half of the same blocker, within ONE step.

    The window is blind at first, so the step falls to tier 2; then the
    control appears in the UIA tree and grounding succeeds without reading.
    A request that is not cancelled on success keeps the worker capturing and
    OCRing for a step that no longer needs it.
    """
    import ghostcursor.run as run_module
    from ghostcursor.overlay import window as real_window
    from ghostcursor.perception import appinfo, service as service_module, tier2

    clock = FakeClock()
    _fake_overlay(monkeypatch)
    appears_at = FakeClock.START + 3.0
    export = Element("Export", "Button", "export_1", (300, 300, 360, 320))

    class LateService(UiaBlindService):
        def latest(self):
            observation = super().latest()
            elements = (export,) if clock.t >= appears_at else ()
            return Observation(
                snapshot=Snapshot(
                    title="app", elements=elements, observed_at=observation.observed_at
                ),
                elements=elements,
                observed_at=observation.observed_at,
                ok=True,
                ocr_elements=observation.ocr_elements,
                tier2_step=observation.tier2_step,
                tier2_engaged=observation.tier2_engaged,
                tier2_exhausted=observation.tier2_exhausted,
                tier2_max_runs=observation.tier2_max_runs,
            )

    monkeypatch.setattr(real_window, "set_hint", lambda *a, **k: None)
    monkeypatch.setattr(
        service_module,
        "PerceptionService",
        lambda *a, **k: LateService(clock, k.get("tier2")),
    )
    monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: None)
    monkeypatch.setattr(run_module, "escape_pressed", lambda: False)
    monkeypatch.setattr(run_module, "key_was_pressed", lambda vk: False)

    controller = RecordingController(clock, [])
    monkeypatch.setattr(tier2, "build_controller", lambda _clock: controller)

    monkeypatch.setattr("builtins.print", lambda *a, **k: None)

    run_module.run_tour(
        _recipe_file(tmp_path),
        ".*app.*",
        seconds=12.0,
        clock=clock,
        sleeper=clock.sleeper,
    )

    assert controller.reads, "tier 2 never read while the control was invisible"
    late = [t for _step, t in controller.reads if t > appears_at + 1.0]
    assert late == [], (
        f"{len(late)} reads happened after UIA could ground the step on its "
        "own — a successful grounding never cancelled the request, so the "
        "worker kept paying capture + OCR for nothing"
    )
