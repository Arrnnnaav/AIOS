"""ESC stays responsive while the target application is hung.

This is the property the whole change exists for, and it could not be tested
before: with perception on the UI thread, a hung target blocked the tick for
tens of seconds and no amount of polling helped.

The first two tests below check the slot in isolation. The third is the one
that matters: it drives the REAL `run_tour` tick loop against a REAL hung
window and asserts that the loop keeps ticking, keeps polling ESC, and honours
it promptly. Anything that puts a UIA walk back on the UI thread fails it.
"""

import time


from ghostcursor.overlay import dpi  # noqa: F401  DPI awareness before any window
from ghostcursor.perception.service import PerceptionService
from ghostcursor.perception.uia import iter_elements
from tests.test_hung_window import HungWindow

#: Ceiling on the gap between two consecutive ESC polls. D020 caps a tick at
#: 0.5s; this doubles it so ordinary scheduling jitter on a loaded machine
#: cannot flake the test, while still catching any regression that puts real
#: work back on the UI thread. A hung UIA walk costs ~41s, so there is no
#: overlap between "slightly slow" and "blocked".
MAX_TICK_GAP_S = 1.0


def test_reading_the_slot_stays_fast_while_the_target_is_hung():
    with HungWindow() as hung:
        service = PerceptionService(
            hung.title_re, walker=iter_elements, interval_s=0.05
        )
        service.start()
        try:
            time.sleep(0.5)  # the worker is now blocked inside UIA
            start = time.perf_counter()
            for _ in range(100):
                service.latest()
            elapsed = time.perf_counter() - start
        finally:
            service.stop()

    assert elapsed < 0.5, (
        f"100 slot reads took {elapsed:.2f}s against a hung target — the UI "
        "thread is still coupled to perception"
    )


def test_a_hung_target_never_produces_an_observation_but_does_not_crash():
    with HungWindow() as hung:
        service = PerceptionService(
            hung.title_re, walker=iter_elements, interval_s=0.05
        )
        service.start()
        try:
            time.sleep(1.0)
            observation = service.latest()
            alive = service.is_alive()
        finally:
            service.stop()

    assert observation is None, "a hung window somehow produced an observation"
    assert alive, "the worker died instead of blocking"


# --- the property: the tick loop survives a hung target ---------------------


def _recipe_file(tmp_path):
    import json

    path = tmp_path / "recipe.json"
    path.write_text(
        json.dumps(
            {
                "app_id": "hung",
                "intent": "escapability probe",
                "steps": [
                    {
                        "user_action": "click",
                        "target_descriptor": {"claimed": {"name": "Export"}},
                        "instruction_text": "Click Export.",
                        "verification_rule": {"kind": "user_confirms", "args": {}},
                        "risk": "normal",
                    }
                ],
            }
        )
    )
    return str(path)


def _fake_overlay(monkeypatch):
    """Replace the drawing surface, not the loop. No real window is created:
    this test is about the tick loop's timing, and a real full-screen
    click-through overlay left on screen by a test run is exactly what this
    project refuses to risk.

    Patched on `ghostcursor.overlay.window` itself rather than on run.py's
    reference to it, because OverlayRenderer captured the module as a default
    argument at class-definition time and would otherwise still draw for real.
    """
    from ghostcursor.overlay import window as real_window

    calls = []
    monkeypatch.setattr(real_window, "create_overlay_window", lambda: 4242)
    monkeypatch.setattr(
        real_window,
        "destroy_overlay_window",
        lambda hwnd: calls.append(("destroy", hwnd)),
    )
    monkeypatch.setattr(real_window, "pump_messages_nonblocking", lambda: None)
    monkeypatch.setattr(
        real_window,
        "set_hint",
        lambda hwnd, x, y, radius=None, freshness=None: calls.append(
            ("set_hint", x, y, freshness)
        ),
    )
    monkeypatch.setattr(
        real_window, "clear_hint", lambda hwnd: calls.append(("clear_hint",))
    )
    return calls


def test_esc_stops_the_tour_promptly_while_the_target_is_hung(tmp_path, monkeypatch):
    """The whole milestone, asserted end to end.

    A hung target blocks a UIA walk for ~40s. ESC is polled BETWEEN ticks, so
    if any part of the tick still walks the tree, the loop stalls inside one
    tick and the ESC the user pressed is not seen until the walk returns.

    Measured per-tick, not in total: see the assertion below for why a
    total-elapsed budget cannot express this property.
    """
    import ghostcursor.run as run_module
    from ghostcursor.perception import appinfo

    calls = _fake_overlay(monkeypatch)
    # Identity lookup can shell out to PowerShell for up to 25s; it is not
    # what this test measures, and against a hung window it is its own hazard.
    monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: None)

    polls = {"n": 0}
    # run_tour polls ESC three times before the loop starts (the pre-tour
    # guards, which run while there is no overlay on screen yet), so this
    # leaves five real tick iterations before the user "presses" ESC.
    press_on = 8
    poll_times: list[float] = []

    def fake_escape():
        poll_times.append(time.perf_counter())
        polls["n"] += 1
        return polls["n"] >= press_on

    monkeypatch.setattr(run_module, "escape_pressed", fake_escape)

    recipe = _recipe_file(tmp_path)

    with HungWindow() as hung:
        start = time.perf_counter()
        rc = run_module.run_tour(recipe, hung.title_re, seconds=60.0)
        elapsed = time.perf_counter() - start

    assert rc == 0
    assert polls["n"] >= press_on, (
        f"ESC was only polled {polls['n']} times before run_tour returned — "
        "the tick loop did not keep running against a hung target"
    )
    # Assert the MAXIMUM GAP between consecutive ESC polls, not total elapsed.
    #
    # The property being guarded is "no single tick blocks" — ESC is polled
    # between ticks, so one slow tick is one window the user cannot escape.
    # A total-elapsed budget answers a different question and lets a partial
    # regression hide inside an average: with a flat +5.0s of slack spread
    # over five tick iterations, every tick could cost ~1.1s and the sum would
    # still pass. That is already DOUBLE D020's 0.5s tick ceiling, and the
    # ceiling test itself cannot cover the gap because it uses an ABSENT
    # window while this failure only appears against a HUNG one.
    #
    # A max-gap assertion is scale-free: it does not care how many ticks run,
    # and fast ticks cannot dilute a slow one.
    gaps = [b - a for a, b in zip(poll_times, poll_times[1:])]
    worst = max(gaps) if gaps else 0.0
    assert worst < MAX_TICK_GAP_S, (
        f"the longest gap between ESC polls was {worst:.2f}s against a hung "
        f"window (ceiling {MAX_TICK_GAP_S}s) — a tick is blocking, so the user "
        "cannot dismiss a window covering their entire screen. All gaps: "
        f"{[f'{g:.2f}' for g in gaps]}"
    )
    assert calls and calls[-1] == ("destroy", 4242), "the overlay was not torn down"


def test_a_hung_target_does_not_end_the_tour_before_the_health_budget(
    tmp_path, monkeypatch
):
    """No observation ever arrives, and that must not be mistaken for a dead
    worker on tick 1.

    `WorkerHealth` reads `ladder.age()`, which is infinite before the first
    observation. Unguarded, that restarts the worker immediately and ends the
    tour on the next tick with "perception stopped working" — while the
    application is merely slow to answer.
    """
    import ghostcursor.run as run_module
    from ghostcursor.perception import appinfo

    _fake_overlay(monkeypatch)
    monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: None)
    monkeypatch.setattr(run_module, "escape_pressed", lambda: False)

    printed = []
    monkeypatch.setattr(
        "builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a)))
    )

    recipe = _recipe_file(tmp_path)

    with HungWindow() as hung:
        run_module.run_tour(recipe, hung.title_re, seconds=3.0)

    assert any("Time limit reached" in line for line in printed), (
        f"the tour ended early instead of running its full 3s: {printed}"
    )
    assert not any("perception stopped working" in line for line in printed), (
        "a target that has simply not answered yet was reported as a dead "
        f"perception worker: {printed}"
    )


def test_a_dead_worker_is_named_as_a_perception_failure(tmp_path, monkeypatch):
    """The element is on screen. Perception is what broke.

    The two clocks race: a dead worker makes grounding fail on every tick, so
    at the stock 10s grounding grace the tour used to give up ~5s BEFORE the
    15s health budget could fire — and told the user "cannot find 'Export' on
    screen" about an element sitting right there. That points them at their
    own application instead of at ours. The grounding grace answers "is the
    target on screen", which is only a meaningful question once perception is
    known to be working, so it must resolve strictly after the health check.
    """
    import ghostcursor.run as run_module
    from ghostcursor.perception import appinfo, service as service_module

    class DeadService:
        """Starts, never observes, and reports itself dead."""

        def __init__(self, *a, **kw):
            self.heartbeat = 0

        def start(self):
            pass

        def stop(self):
            pass

        def restart(self):
            pass

        def latest(self):
            return None

        def is_alive(self):
            return False

    _fake_overlay(monkeypatch)
    monkeypatch.setattr(service_module, "PerceptionService", DeadService)
    monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: None)
    monkeypatch.setattr(run_module, "escape_pressed", lambda: False)

    printed = []
    monkeypatch.setattr(
        "builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a)))
    )

    recipe = _recipe_file(tmp_path)
    run_module.run_tour(recipe, ".*GhostCursorTestApp.*", seconds=20.0)

    # Must assert the tour ENDED naming perception, not merely that the word
    # appeared: health also logs "restarted the perception worker" on its way
    # past, which is non-terminal. Without this, a regression where health
    # restarts once and then never fires again — letting the tour run out to
    # --seconds having guided nobody — would still pass.
    assert any(line.startswith("Stopped: perception") for line in printed), (
        f"a dead perception worker was not named as the reason the tour ended: {printed}"
    )
    assert not any("Time limit reached" in line for line in printed), (
        f"the tour ran to its time limit instead of naming the failure: {printed}"
    )
    assert not any("cannot find" in line.lower() for line in printed), (
        "a dead perception worker was misreported as a missing element, "
        f"pointing the user at their own application: {printed}"
    )


def test_a_target_hung_on_first_contact_is_named_as_a_perception_failure(
    tmp_path, monkeypatch
):
    """The flagship case: nothing is ever observed, because the very first
    walk is the 41s one.

    Health's worst case is TWO budgets, not one. The check is suppressed for
    `dead_after_s` from tour start (the ladder's age is infinite before the
    first observation), and the restart it then fires grants the replacement
    another `dead_after_s` before the stall signal may judge it. At a grace of
    one budget the tour gave up at 25.75s with "cannot find 'Export' on
    screen" — 4.25s before health could name the real cause.
    """
    import ghostcursor.run as run_module
    from ghostcursor.perception import appinfo, service as service_module

    class NeverObservingService:
        """Alive, running, and permanently wedged: publishes nothing, ever."""

        def __init__(self, *a, **kw):
            self.heartbeat = 0

        def start(self):
            pass

        def stop(self):
            pass

        def restart(self):
            pass

        def latest(self):
            return None

        def is_alive(self):
            return True

    _fake_overlay(monkeypatch)
    monkeypatch.setattr(service_module, "PerceptionService", NeverObservingService)
    monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: None)
    monkeypatch.setattr(run_module, "escape_pressed", lambda: False)

    printed = []
    monkeypatch.setattr(
        "builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a)))
    )

    recipe = _recipe_file(tmp_path)
    run_module.run_tour(recipe, ".*GhostCursorTestApp.*", seconds=40.0)

    assert any(line.startswith("Stopped: perception") for line in printed), (
        f"a wedged perception worker was not named as the reason the tour ended: {printed}"
    )
    assert not any("Time limit reached" in line for line in printed), (
        f"the tour ran to its time limit instead of naming the failure: {printed}"
    )
    assert not any("cannot find" in line.lower() for line in printed), (
        "a wedged perception worker was misreported as a missing element, "
        f"pointing the user at their own application: {printed}"
    )


def test_a_genuinely_absent_element_is_still_reported_as_missing(tmp_path, monkeypatch):
    """The other side of the guard, and the one no other test covers.

    The no-observation guard skips ticks until perception answers. A guard
    that was too BROAD — skipping forever, or suppressing the grounding grace
    outright — would pass every other test in this file, because they all
    assert that "cannot find" does NOT appear. This asserts it still does when
    it should: perception is working and answering, and the element genuinely
    is not on screen.
    """
    import time as time_module

    import ghostcursor.run as run_module
    from ghostcursor.perception import appinfo, service as service_module
    from ghostcursor.perception.service import Observation
    from ghostcursor.reasoning.verification import Snapshot

    class HealthyButEmptyService:
        """Answers promptly and successfully — with nothing on screen."""

        def __init__(self, *a, **kw):
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
            self.heartbeat += 1
            now = time_module.monotonic()
            return Observation(
                snapshot=Snapshot(title="empty", elements=(), observed_at=now),
                elements=(),
                observed_at=now,
                ok=True,
            )

    _fake_overlay(monkeypatch)
    monkeypatch.setattr(service_module, "PerceptionService", HealthyButEmptyService)
    monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: None)
    monkeypatch.setattr(run_module, "escape_pressed", lambda: False)

    printed = []
    monkeypatch.setattr(
        "builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a)))
    )

    recipe = _recipe_file(tmp_path)
    run_module.run_tour(recipe, ".*GhostCursorTestApp.*", seconds=20.0)

    assert any("cannot find" in line.lower() for line in printed), (
        "a genuinely missing element was never reported — the no-observation "
        f"guard may be suppressing the grounding grace entirely: {printed}"
    )
    assert not any(line.startswith("Stopped: perception") for line in printed), (
        f"a working perception worker was blamed for a missing element: {printed}"
    )
