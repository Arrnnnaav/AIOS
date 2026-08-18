"""Regression tests for the three properties left unguarded by c6115a1.

That commit's own message says it plainly: "the regression tests for the
laundering sequence, the churning-page case, and the promotion guard are not
written." These three tests close that gap. Written independently of the
commit that produced the fixes, per this project's rule that whoever wrote a
fix is not the only one who validates it.

Idioms reused rather than reinvented, per file:
  - FakeClock, UiaBlindService, _fake_overlay, _recipe_file:
    tests/test_tier2_timeline.py and tests/test_run_threaded.py.
  - The GuidedTour + RecordingOverlay drive: tests/test_loop.py and
    tests/test_first_paint.py.
  - GHOSTCURSOR_KB_PATH as the scratch-store override: tests/test_store.py
    and tests/test_persistence_e2e.py.
"""

import numpy as np
import pytest

from ghostcursor.overlay import dpi  # noqa: F401  DPI awareness before any window
from ghostcursor.perception.ocr import OcrRead, ocr_available
from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.grounding import GroundedTarget
from ghostcursor.reasoning.loop import DEFAULT_GROUNDING_GRACE_S, GuidedTour
from ghostcursor.reasoning.renderer import OverlayRenderer
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor,
    Recipe,
    Risk,
    Step,
    TargetDescriptor,
    UserAction,
    VerificationKind,
    VerificationRule,
)
from ghostcursor.reasoning.staleness import Freshness
from ghostcursor.reasoning.verification import Snapshot
from tests.test_run_threaded import _fake_overlay, _recipe_file


class FakeClock:
    """Same shape as tests/test_tier2_timeline.py's — an injected clock and
    the sleeper that advances it, so nothing here depends on real time."""

    START = 1000.0

    def __init__(self):
        self.t = self.START

    def __call__(self):
        return self.t

    def sleeper(self, seconds):
        self.t += seconds


class UiaBlindService:
    """A worker that sees the window but never the control the step names.

    Identical in shape to test_tier2_timeline.py's fixture of the same name:
    UIA is permanently blind to "Export", so any grounding of that target can
    only have come from tier 2 (OCR).
    """

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
        from ghostcursor.perception.service import Observation

        now = self._clock()
        furniture = (Element("Minimise", "Button", "view_1", (0, 0, 20, 20)),)
        return Observation(
            snapshot=Snapshot(title="app", elements=furniture, observed_at=now),
            elements=furniture,
            observed_at=now,
            ok=True,
        )


# ---------------------------------------------------------------------------
# TEST 1 — provenance must not launder across the DECIDING tick
# ---------------------------------------------------------------------------


def test_settle_never_repaints_the_ocr_centre_as_a_confirmed_control():
    """The property: a repaint reproduces the state ITS hint was created with,
    never the wider system's current grounding source.

    Drives the real sequence that caused the bug: a step grounds via OCR and
    is drawn (amber, INFERRED, at the OCR centre); the world changes and the
    loop walks AWAITING_USER_ACTION -> OBSERVING -> DECIDING; in that DECIDING
    tick the grounder now returns a UIA-sourced target (source flips to
    "uia") but RENDERING_HINT has not run yet this tick, so nothing calls
    `renderer.show()`. `tick()` still calls `settle()` to close the tick.

    Before the fix, `settle()`'s repaint read the CURRENT grounding source at
    paint time, so it drew the OLD OCR centre in FRESH cyan for that whole
    tick -- a pixel guess wearing the confirmed-control ring, at a coordinate
    the UIA rect may not even agree with. The fix binds centre and provenance
    into one frozen `_Hint` at `show()` time, so a repaint with nothing new to
    show can only reproduce ITS bound source, never a source that arrived
    later, no matter what the wider system now believes.
    """
    OCR_TARGET = GroundedTarget((80, 80, 120, 120), 4, "", "", "Export", "ocr")
    UIA_TARGET = GroundedTarget((10, 10, 110, 40), 2, "1001", "Button", "Export", "uia")
    OCR_CENTRE = (100, 100)

    step = Step(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor(name="Export")),
        instruction_text="Click Export.",
        verification_rule=VerificationRule(
            kind=VerificationKind.ELEMENT_APPEARS,
            args={"target_descriptor": {"name": "Save"}},
        ),
        risk=Risk.NORMAL,
    )
    recipe = Recipe(app_id="test", intent="t", steps=[step])

    # Call 1 -> the OCR-grounded target; call 2 -> the UIA one that supersedes
    # it, reproducing the real "OCR first, UIA catches up a tick later" order.
    targets = iter([OCR_TARGET, UIA_TARGET])

    def grounder(_step, _i, elements=None):
        return next(targets)

    STILL = Snapshot("App", (), observed_at=1.0)
    CHANGED = Snapshot(
        "App", (Element("Dialog", "Window", "9001", (0, 0, 50, 50)),), observed_at=2.0
    )
    snaps = iter([STILL, CHANGED])

    def snapshotter():
        return next(snaps, CHANGED)

    calls = []

    class RecordingOverlay:
        def set_hint(self, hwnd, x, y, radius=24, freshness=None):
            calls.append(("set_hint", x, y, freshness))

        def clear_hint(self, hwnd):
            calls.append(("clear_hint", None))

    renderer = OverlayRenderer(
        hwnd=1, overlay=RecordingOverlay(), freshness_source=lambda: Freshness.FRESH
    )

    tour = GuidedTour(
        recipe=recipe,
        grounder=grounder,
        snapshotter=snapshotter,
        # Never satisfied -> AWAITING_USER_ACTION falls through to the
        # "world changed unexpectedly" branch and re-observes, which is the
        # real path that leaves DECIDING's new source with no paint of its
        # own that tick.
        verifier=lambda rule, before, after: False,
        renderer=renderer,
        clock=lambda: 0.0,
    )

    # tick1 IDLE->OBSERVING, tick2 OBSERVING->DECIDING (baseline=STILL),
    # tick3 DECIDING->RENDERING_HINT (grounds OCR), tick4 RENDERING_HINT->
    # AWAITING (paints OCR centre INFERRED), tick5 AWAITING->OBSERVING (world
    # changed), tick6 OBSERVING->DECIDING (baseline=CHANGED), tick7 DECIDING->
    # RENDERING_HINT (grounds UIA, source flips, NO paint this tick -- only
    # settle()'s repaint), tick8 RENDERING_HINT->AWAITING (paints UIA centre).
    for _ in range(8):
        tour.tick()

    assert ("set_hint", 100, 100, Freshness.INFERRED) in calls, (
        "the OCR hint was never actually drawn INFERRED, so this test proves "
        f"nothing about laundering: {calls}"
    )

    laundered = [
        c
        for c in calls
        if c[0] == "set_hint" and (c[1], c[2]) == OCR_CENTRE and c[3] is Freshness.FRESH
    ]
    assert not laundered, (
        "a repaint drew the OCR centre in FRESH cyan after the grounding "
        "source had already flipped to 'uia' in DECIDING but before "
        "RENDERING_HINT had painted the new target -- provenance laundered "
        f"across the tick boundary: {calls}"
    )


# ---------------------------------------------------------------------------
# TEST 2 — a churning page must not kill a working tour
# ---------------------------------------------------------------------------


class ChurningButWorkingController:
    """Reports its run cap already spent, while OCR keeps reading the target
    successfully every tick.

    The real `Tier2Controller` cannot actually produce this combination --
    `elements_for` short-circuits to `[]` the moment `exhausted()` is true, so
    an exhausted-but-still-succeeding tick is not reachable through it. That
    is exactly why a fake is needed: the OLD bug was in run.py's own tick
    loop, which used to check `tier2_controller.exhausted(...)` UNCONDITIONALLY
    every tick and `break` the instant it was true -- decoupled from whether
    THIS tick's read had actually succeeded. This fake reproduces precisely
    that decoupled state so the loop's own decision is what gets exercised.
    """

    max_runs_per_step = 20

    def elements_for(self, step_index, title_re):
        return [Element("Export", "", "", (10, 20, 110, 44), (), "ocr")]

    def exhausted(self, step_index):
        return True

    def engaged(self, step_index):
        return True

    def grounded(self, step_index):
        pass


def test_a_churning_but_successfully_grounding_page_does_not_end_the_tour(
    tmp_path, monkeypatch
):
    """The case: OCR keeps reading 'Export' correctly, tick after tick, on a
    page whose UIA elements keep changing underneath it. Old behaviour ended
    the tour with 'could not read Export on screen' the instant the run cap
    was reported spent, even while the amber ring sat correctly on Export and
    OCR was working perfectly. The fix removed that unconditional break; an
    exhausted-but-grounding step is not a failure at all.
    """
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
    monkeypatch.setattr(
        tier2, "build_controller", lambda _clock: ChurningButWorkingController()
    )

    printed = []
    monkeypatch.setattr(
        "builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a)))
    )

    # Well past both the old cap-triggered abort and DEFAULT_GROUNDING_GRACE_S
    # -- if either the old break or a spurious grace expiry killed the tour,
    # it would end well before this deadline is reached.
    seconds = 3 * DEFAULT_GROUNDING_GRACE_S
    run_module.run_tour(
        _recipe_file(tmp_path),
        ".*app.*",
        seconds=seconds,
        clock=clock,
        sleeper=clock.sleeper,
    )

    elapsed = clock.t - FakeClock.START
    assert elapsed >= seconds - 1e-6, (
        f"the tour ended after {elapsed:.1f}s of {seconds:.0f}s while OCR was "
        f"grounding the target on every tick: {printed}"
    )
    assert any("Time limit reached" in line for line in printed), (
        f"the tour did not run to completion: {printed}"
    )

    stopped = [line for line in printed if line.startswith("Stopped:")]
    assert not stopped, (
        "a churning page whose target OCR kept grounding successfully ended "
        f"the tour anyway: {stopped}"
    )

    inferred_writes = [
        c for c in calls if c[0] == "set_hint" and c[3] is Freshness.INFERRED
    ]
    assert len(inferred_writes) > 1, (
        f"the OCR-grounded hint was never actually painted repeatedly, so "
        f"this test proves nothing: {calls}"
    )


# ---------------------------------------------------------------------------
# TEST 3 — an OCR-grounded target can never be persisted
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not ocr_available(), reason="no OCR language pack")
def test_ocr_grounded_target_writes_nothing_to_the_knowledge_base(
    tmp_path, monkeypatch
):
    """The knowledge base is UIA-only. An OCR element carries no
    AutomationId, and a persisted pixel coordinate is a lie the moment the
    window moves -- there is no representation for it that would be honest.

    Asserted on the store's actual CONTENTS (every row in the table, not
    filtered to one step/app key), because the property under test is
    "nothing durable exists", not "we took the branch we expected" -- the
    empty-string automation_id happening to match no stored row was exactly
    the coincidence this guard replaced.
    """
    import ghostcursor.run as run_module
    from ghostcursor.memory.store import ObservationStore
    from ghostcursor.perception import appinfo, service as service_module, tier2
    from ghostcursor.perception.appinfo import AppInfo

    clock = FakeClock()
    _fake_overlay(monkeypatch)
    monkeypatch.setattr(
        service_module, "PerceptionService", lambda *a, **k: UiaBlindService(clock)
    )
    app_info = AppInfo(
        app_id="app.exe", exe_path=r"C:\app.exe", version="1.0.0", kind="win32"
    )
    monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: app_info)
    monkeypatch.setattr(run_module, "escape_pressed", lambda: False)
    monkeypatch.setattr(run_module, "key_was_pressed", lambda vk: False)

    db_path = tmp_path / "kb.sqlite"
    monkeypatch.setenv("GHOSTCURSOR_KB_PATH", str(db_path))

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

    assert db_path.exists(), (
        "no database was ever created, so this test cannot tell an empty "
        f"store from a guard that worked: {printed}"
    )
    with ObservationStore(db_path) as store:
        rows = store._conn.execute("SELECT * FROM observations").fetchall()

    assert rows == [], (
        "an OCR-grounded target was written to the UIA-only knowledge base: "
        f"{[dict(r) for r in rows]} (log: {printed})"
    )
