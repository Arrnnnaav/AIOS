"""Guards the one silent-failure mode `WarmUp` has, through the REAL wiring.

`WarmUp.allows_tier2(hwnd)` returns True immediately when `hwnd <= 0` -- a
deliberate bypass, because a handle of 0 means no window was observed and
there is nothing to be patient about (see ghostcursor/perception/warmup.py).

That bypass is also a trapdoor: `Observation.target_hwnd` reaches the UI
thread by way of `PerceptionService`'s default `hwnd_source=first_matching_hwnd`
(ghostcursor/perception/uia.py). If `first_matching_hwnd` ever regresses to
returning 0 for a window that plainly exists, warm-up silently disables
itself for every app, forever -- and nothing in the existing suite would
notice, because every pre-existing test constructs `Observation` with the
default `target_hwnd = 0`, and the one file that exercises a non-zero handle
(tests/test_warmup_tour.py) sets a FAKE one on a scripted service, never on a
real `PerceptionService`. No test anywhere runs the production wiring end to
end -- until this file.

This test starts a REAL `PerceptionService` (with a trivial element walker, and
critically NO `hwnd_source` override, so the production default
`first_matching_hwnd` is what actually runs) against a real Win32 window from
`tests.uia_app.SyntheticApp`, waits for a published `Observation`, confirms
its `target_hwnd` is the window's real handle, and confirms that handle
actually engages a real `WarmUp` (i.e. `allows_tier2` returns False on first
sight, not the `hwnd <= 0` bypass's True). A regression that made
`first_matching_hwnd` return 0 would make this test fail at the
`target_hwnd != 0` assertion while leaving the rest of the suite green.
"""

import time


import ghostcursor.run as run_module
from ghostcursor.perception.service import PerceptionService
from ghostcursor.perception.uia import windows_matching
from ghostcursor.perception.warmup import WarmUp
from tests.uia_app import SyntheticApp


def _wait_until_pumping(app, predicate, timeout=5.0, what="condition"):
    """Poll until predicate() is truthy, pumping `app`'s message queue on
    every spin. Returns the value; fails loudly.

    The synthetic window belongs to this process's main thread, so its message
    queue must be pumped while the perception worker discovers the real HWND.
    Real target applications pump their own queues in separate processes.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.pump()
        value = predicate()
        if value:
            return value
        # Keep the synthetic window responsive while the worker is sampling it.
        time.sleep(0.001)
    raise AssertionError(f"{what} never became true within {timeout}s")


def test_a_real_windows_handle_reaches_warmup_and_is_not_the_zero_bypass():
    """End-to-end: real window -> real PerceptionService (default
    hwnd_source) -> real Observation.target_hwnd -> real WarmUp suppresses.

    The element walker is intentionally trivial here. UIA tree fidelity is
    covered by the desktop/pixel lane; this test's contract is the HWND path,
    and same-process UIA introduces a WM_GETOBJECT round-trip unrelated to it.
    """
    with SyntheticApp(title="GhostCursorWarmupProbe") as app:
        title_re = f".*{app.title}.*"

        # Independently obtained ground truth for what the handle SHOULD be --
        # not through the service under test, so this isn't circular.
        expected_hwnd = windows_matching(title_re)[0]
        assert expected_hwnd == app.hwnd

        service = PerceptionService(
            title_re=title_re,
            walker=lambda _title_re: [],
            interval_s=0.01,
        )
        service.start()
        try:
            observation = _wait_until_pumping(
                app,
                service.latest,
                what="a published observation with the synthetic window up",
            )

            # The assertion that would fail first, and loudly, if
            # first_matching_hwnd regressed to returning 0: warm-up's
            # hwnd <= 0 bypass would then be indistinguishable from "engaged".
            assert observation.target_hwnd != 0, (
                "PerceptionService published target_hwnd=0 for a window that "
                "is demonstrably on screen -- first_matching_hwnd (the "
                "production hwnd_source default) is not seeing it, which "
                "silently disables warm-up for every application"
            )
            assert observation.target_hwnd == expected_hwnd, (
                f"published target_hwnd {observation.target_hwnd} does not "
                f"match the synthetic window's real handle {expected_hwnd}"
            )

            # The property warm-up actually depends on: a production handle
            # must engage the grace period, not fall through the hwnd <= 0
            # bypass that exists for the "no window observed" case.
            warmup = WarmUp(budget_s=2.0, clock=lambda: 0.0)
            assert warmup.allows_tier2(observation.target_hwnd) is False, (
                "a real, production-sourced window handle was allowed "
                "straight through to tier 2 on first sight -- indistinguishable "
                "from the hwnd <= 0 bypass, which means warm-up is not "
                "actually engaging for real windows"
            )
        finally:
            service.stop()


def test_the_tick_loop_suppresses_tier2_through_the_real_wiring(monkeypatch, tmp_path):
    """Closes the seam this file's module docstring names but the first test
    does not reach: that test proves a real handle engages a real `WarmUp`,
    but never runs the tick loop. `tests/test_warmup_tour.py` proves the tick
    loop consults warm-up and suppresses `request_tier2`, but does so with a
    FAKE handle hand-set on a scripted `_ScriptedService`, never a real
    `PerceptionService`. Nothing anywhere runs BOTH halves at once: the real
    tick loop, in `ghostcursor.run.run_tour`, driving a REAL `PerceptionService`
    (default `hwnd_source=first_matching_hwnd`)
    against a real Win32 window, with a target that never grounds so warm-up
    is the only thing standing between every tick and a tier-2 request.

    Runs `run_tour` on a background thread with REAL time (no injected clock
    or sleeper -- there is no way to rendezvous with `run_tour`'s outer loop
    here the way `test_warmup_tour.py`'s barrier does, because the perception
    WORKER also runs concurrently on its own thread and needs this test's
    main thread pumping `SyntheticApp`'s message queue essentially
    continuously the whole time, not just between ticks -- see
    `_wait_until_pumping`'s docstring above). `PerceptionService.request_tier2`
    is spied at the class level (so it is intercepted no matter which
    instance `run_tour` constructs internally) and every call is timestamped
    against `time.monotonic()`, the same clock `run_tour` itself defaults to.

    This proves BOTH halves: no request lands inside [first failed grounding,
    first failed grounding + budget_s), AND at least one lands after that
    interval -- so the test cannot pass for the trivial reason that tier 2
    was never going to fire at all.

    The suppression window is anchored to the first FAILED call of
    `ghostcursor.reasoning.grounding.ground` (spied the same way
    `request_tier2` is), not to when this test's thread launches. Anchoring
    to thread-launch was tried first and was a false green: `run_tour` has
    to construct a `PerceptionService`, start its worker, have that worker
    complete a real UIA walk and publish an observation (`run.py` skips the
    tick entirely while `service.latest()` is None), and only THEN reach its
    first failed grounding -- which is the moment `warmup.allows_tier2` is
    first consulted and the budget clock actually starts. That startup cost
    alone can exceed a short budget, so a thread-launch-anchored
    `before_budget == []` can be empty because nothing had happened yet, not
    because anything was suppressed -- confirmed by mutation: deleting the
    `if not warmup.allows_tier2(...): ... return None` guard in `run.py`
    entirely still passed a thread-launch-anchored version of this test.
    Anchoring to the real event closes that gap.
    """
    import json
    import threading
    import time as time_module

    from ghostcursor.overlay import window as real_window
    from ghostcursor.perception import appinfo
    from ghostcursor.reasoning import grounding as grounding_module

    #: Longer than the original 0.5s/3.0s pairing, per the false-green fix:
    #: room for the interval to be unambiguous rather than swallowed by
    #: startup jitter (real UIA walk, real worker thread, real window).
    budget_s = 1.5
    total_seconds = 5.0

    #: Every call to grounding.ground, timestamped, with whether it FAILED
    #: (returned None). The first failure is the real "warm-up opens" event
    #: -- not this test's thread-launch time, which precedes a real UIA
    #: worker start, a real walk, and a real published observation.
    ground_calls: list[tuple[float, bool]] = []
    real_ground = grounding_module.ground

    def spy_ground(*args, **kwargs):
        result = real_ground(*args, **kwargs)
        ground_calls.append((time_module.monotonic(), result is None))
        return result

    with SyntheticApp(title="GhostCursorWarmupTickLoopProbe") as app:
        title_re = f".*{app.title}.*"

        recipe_path = tmp_path / "recipe.json"
        recipe_path.write_text(
            json.dumps(
                {
                    "app_id": "warmup-tickloop-probe",
                    "intent": "warmup tick loop probe",
                    "steps": [
                        {
                            "user_action": "click",
                            "target_descriptor": {
                                "claimed": {"name": "ThisControlDoesNotExist"}
                            },
                            "instruction_text": "Click a control that is not there.",
                            "verification_rule": {"kind": "user_confirms", "args": {}},
                            "risk": "normal",
                        }
                    ],
                }
            )
        )

        # No real overlay window: this test is about warm-up gating, not
        # rendering, and a stray full-screen click-through window left behind
        # by a test run is exactly what this project refuses to risk.
        monkeypatch.setattr(real_window, "create_overlay_window", lambda: 4242)
        monkeypatch.setattr(real_window, "destroy_overlay_window", lambda hwnd: None)
        monkeypatch.setattr(real_window, "pump_messages_nonblocking", lambda: None)
        monkeypatch.setattr(
            real_window,
            "set_hint",
            lambda hwnd, x, y, radius=None, freshness=None: None,
        )
        monkeypatch.setattr(real_window, "clear_hint", lambda hwnd: None)

        # No PowerShell shell-out for app identity: irrelevant to what this
        # test measures, and run_tour's own comment notes it can take up to
        # 25s for a Store app. Also keeps persistence (ObservationStore) out
        # of this test entirely.
        monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: None)
        # Preserve real HWND discovery, which is the seam under test, while
        # removing same-process UIA's unrelated WM_GETOBJECT round-trip. Real
        # tree walking is exercised in the desktop/pixel lane.
        monkeypatch.setattr(
            run_module,
            "perception_walker_for",
            lambda _app_id: (lambda _title_re: []),
        )

        # Neutralize real keyboard state so a key genuinely held down on the
        # machine running this test cannot end the tour early via ESC or
        # confirm a step it never reached.
        monkeypatch.setattr(run_module, "escape_pressed", lambda: False)
        monkeypatch.setattr(run_module, "key_was_pressed", lambda vk: False)

        # Patched on the module -- `make_grounder`'s `grounder()` closure
        # (in run.py) does `from ghostcursor.reasoning import grounding` and
        # then calls `grounding.ground(...)`, an attribute lookup at call
        # time, so patching the module attribute here reaches it regardless
        # of which function object closed over the name first.
        monkeypatch.setattr(grounding_module, "ground", spy_ground)

        requests: list[tuple[float, int]] = []
        real_request_tier2 = PerceptionService.request_tier2

        def spy_request_tier2(self, step_index):
            requests.append((time_module.monotonic(), step_index))
            return real_request_tier2(self, step_index)

        # Patched on the CLASS, not an instance -- run_tour constructs its
        # own PerceptionService internally, using the production default
        # hwnd_source (first_matching_hwnd), which is the entire point.
        monkeypatch.setattr(PerceptionService, "request_tier2", spy_request_tier2)

        wall_start = time_module.monotonic()
        result: dict = {}

        def target():
            result["rc"] = run_module.run_tour(
                str(recipe_path),
                title_re,
                seconds=total_seconds,
                warmup_budget_s=budget_s,
            )

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        # Pump continuously (see _wait_until_pumping's docstring): the
        # perception worker's UIA walk round-trips through this process's
        # message loop, and a sleep-and-poll cadence here was measured to
        # leave it blocked indefinitely.
        pump_deadline = wall_start + total_seconds + 5.0
        while thread.is_alive() and time_module.monotonic() < pump_deadline:
            app.pump()
            time_module.sleep(0.001)
        thread.join(timeout=5.0)
        assert not thread.is_alive(), "run_tour did not finish within its own deadline"
        assert "rc" in result, "run_tour's background thread never completed"

        # The real anchor: the first FAILED grounding attempt is when
        # `warmup.allows_tier2` is first consulted in run.py, i.e. when the
        # budget clock actually starts -- not when this test's thread
        # launched (see the docstring for why that was a false green).
        failures = [t for t, failed in ground_calls if failed]
        assert failures, (
            "grounding.ground was never called, or never failed -- the "
            "target must be ungroundable for warm-up to be the only thing "
            "standing between the tick loop and a tier-2 request"
        )
        warmup_opened_at = failures[0]
        budget_expires_at = warmup_opened_at + budget_s

        requested_at = [t for t, _ in requests]

        suppressed_window = [t for t in requested_at if t < budget_expires_at]
        assert suppressed_window == [], (
            f"tier 2 was requested at t={[t - warmup_opened_at for t in suppressed_window]}s "
            f"relative to warm-up opening, before the {budget_s}s budget "
            "expired -- warm-up did not suppress for a real, "
            "production-sourced window handle"
        )

        released_after = [t for t in requested_at if t >= budget_expires_at]
        assert released_after, (
            f"tier 2 was never requested even after the {budget_s}s warm-up "
            f"budget expired (opened at t={warmup_opened_at - wall_start:.2f}s "
            f"into the tour), within a {total_seconds}s tour -- this test "
            "would then only prove suppression, never release"
        )
