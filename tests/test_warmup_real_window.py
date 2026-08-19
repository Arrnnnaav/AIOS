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

This test starts a REAL `PerceptionService` (real `iter_elements` walker, and
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


from ghostcursor.perception.service import PerceptionService
from ghostcursor.perception.uia import windows_matching
from ghostcursor.perception.warmup import WarmUp
from tests.uia_app import SyntheticApp


def _wait_until_pumping(app, predicate, timeout=5.0, what="condition"):
    """Poll until predicate() is truthy, pumping `app`'s message queue on
    every spin. Returns the value; fails loudly.

    A same-process UIA walk (the worker thread reading a window owned by
    THIS process's main thread) round-trips through SendMessage(WM_GETOBJECT)
    to that window's owning thread. `SyntheticApp.pump()` on a periodic
    sleep-and-poll cadence (as `_wait_until` elsewhere in this suite does)
    was measured to leave the worker thread's walk blocked indefinitely --
    the reply needs the owning thread back in its message loop essentially
    continuously, not every few tens of milliseconds. A real target
    application (a different process, as production always sees) pumps its
    own queue continuously regardless of what this test does, so this
    tight-pump requirement is specific to using an in-process synthetic
    window and is not itself a discovery about production behaviour.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.pump()
        value = predicate()
        if value:
            return value
        # Deliberately no sleep (or a negligible one): PumpWaitingMessages
        # must run essentially back-to-back for the owning thread to answer
        # WM_GETOBJECT promptly enough for the worker's walk to complete.
        time.sleep(0.001)
    raise AssertionError(f"{what} never became true within {timeout}s")


def test_a_real_windows_handle_reaches_warmup_and_is_not_the_zero_bypass():
    """End-to-end: real window -> real PerceptionService (default
    hwnd_source) -> real Observation.target_hwnd -> real WarmUp suppresses.
    """
    with SyntheticApp(title="GhostCursorWarmupProbe") as app:
        title_re = f".*{app.title}.*"

        # Independently obtained ground truth for what the handle SHOULD be --
        # not through the service under test, so this isn't circular.
        expected_hwnd = windows_matching(title_re)[0]
        assert expected_hwnd == app.hwnd

        service = PerceptionService(title_re=title_re, interval_s=0.01)
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
