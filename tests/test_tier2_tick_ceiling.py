"""D020's tick ceiling, measured WHILE TIER 2 IS ENGAGED.

The coverage gap this closes: tests/test_tick_latency.py bounds a tick against
an ABSENT window, so grounding never fails, so tier 2 never turns on and the
OCR path is entirely outside that file's reach. Capture plus OCR measured
0.14-0.23s on a 976x1028 window on this machine, and OCR cost scales with
captured AREA — a full 4K screen is several times that. On the tick path it
eats D020's 0.5s ceiling outright and brings back exactly the freeze D021
moved perception off the UI thread to prevent: ESC is polled BETWEEN ticks, so
a tick that blocks is time the user cannot dismiss a full-screen,
click-through, unfocused overlay.

So this drives the REAL `run_tour` loop with the REAL `PerceptionService`
thread, against a step UIA can never ground (tier 2 therefore engages and
stays engaged) and an OCR engine deliberately slowed to `SLOW_OCR_S` — well
past the ceiling, so anything that runs it on the tick path shows up as a
blocked tick rather than as a slightly slow one.

Asserted on the MAXIMUM GAP between consecutive ESC polls, never on total
elapsed. A flat total budget averages a 0.9s tick away against a dozen fast
ones and reports "fine" — this project has been bitten by that before
(tests/test_run_threaded.py says the same thing for the hung-window case).
The gap IS the tick: one ESC poll to the next.
"""

import time

import numpy as np

from ghostcursor.overlay import dpi  # noqa: F401  DPI awareness before any window
from ghostcursor.perception.service import PerceptionService
from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.staleness import Freshness
from tests.test_run_threaded import _fake_overlay, _recipe_file

#: How long one OCR read takes in this test. Chosen so that a tick which runs
#: OCR is unambiguously over the ceiling rather than marginally over it: on the
#: UI thread the gap becomes REFRESH_SECONDS + this, which is past MAX_TICK_GAP_S
#: with room to spare, while off it the gap stays at REFRESH_SECONDS. It is not
#: an unrealistic figure either — 0.23s measured against a quarter-screen window,
#: scaling with area, reaches this on a full 4K screen.
SLOW_OCR_S = 0.6

#: Same derivation as tests/test_run_threaded.py's: REFRESH_SECONDS (0.25) plus
#: D020's 0.5s ceiling on the work a tick may do. A larger bound would permit a
#: tick that is itself a D020 violation.
MAX_TICK_GAP_S = 0.75

#: Enough loop iterations to get well past the first grounding failure (which
#: is what turns tier 2 on) and through several worker publications.
TICKS = 16

FURNITURE = Element("Minimise", "Button", "view_1", (0, 0, 20, 20))


class SlowOcr:
    """An engine with the cost of a real one on a large window."""

    def __init__(self):
        self.reads = 0

    def read(self, frame):
        from ghostcursor.perception.ocr import OcrRead

        self.reads += 1
        time.sleep(SLOW_OCR_S)
        return [OcrRead(text="Export", bbox=(10, 20, 110, 44))]


def _changing_capture():
    """A never-settling region: every frame differs from the last.

    Without this, `frames_differ` short-circuits after the first read and the
    test would measure a tick that does no OCR at all — which is precisely the
    vacuous pass this file exists to avoid.
    """
    n = {"i": 0}

    def capture(_title_re):
        n["i"] += 1
        frame = np.full((120, 120, 3), (n["i"] * 37) % 251, dtype=np.uint8)
        return frame, (0, 0, 120, 120)

    return capture


def test_no_tick_exceeds_the_ceiling_while_tier_2_is_running(tmp_path, monkeypatch):
    import ghostcursor.run as run_module
    from ghostcursor.perception import appinfo, service as service_module, tier2
    from ghostcursor.perception.tier2 import Tier2Controller

    calls = _fake_overlay(monkeypatch)
    # Identity lookup can shell out to PowerShell for up to 25s; not what this
    # measures.
    monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: None)
    monkeypatch.setattr(run_module, "key_was_pressed", lambda vk: False)

    ocr = SlowOcr()
    # A REAL controller (its own floor and cap included), with only the engine
    # and the screen faked, so the thing under test is where it RUNS.
    monkeypatch.setattr(
        tier2,
        "build_controller",
        lambda clock: Tier2Controller(
            ocr=ocr,
            capture=_changing_capture(),
            clock=clock,
            #: No floor: maximum pressure on whichever thread runs the reads.
            min_interval_s=0.0,
        ),
    )

    # A real service and a real worker thread — the whole point — with only
    # the UIA walk faked, so it is permanently blind to "Export" and grounding
    # for the step can only ever come from tier 2.
    monkeypatch.setattr(
        service_module,
        "PerceptionService",
        lambda title_re, **kwargs: PerceptionService(
            title_re,
            walker=lambda _t: [FURNITURE],
            clock=kwargs.get("clock", time.monotonic),
            interval_s=0.05,
            tier2=kwargs.get("tier2"),
        ),
    )

    polls: list[float] = []

    def fake_escape():
        polls.append(time.perf_counter())
        return len(polls) >= TICKS

    monkeypatch.setattr(run_module, "escape_pressed", fake_escape)

    printed: list[str] = []
    monkeypatch.setattr(
        "builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a)))
    )

    run_module.run_tour(_recipe_file(tmp_path), ".*app.*", seconds=30.0)

    # --- the test must not be vacuous -------------------------------------
    assert ocr.reads >= 2, (
        f"OCR ran {ocr.reads} time(s), so tier 2 was never really engaged and "
        f"this measured a tick that does no OCR at all: {printed}"
    )
    inferred = [c for c in calls if c[0] == "set_hint" and c[3] is Freshness.INFERRED]
    assert inferred, (
        "no OCR-grounded hint was ever drawn, so tier 2's output never reached "
        f"the tick path being measured: {calls} / {printed}"
    )

    # --- the property ------------------------------------------------------
    gaps = [b - a for a, b in zip(polls, polls[1:])]
    worst = max(gaps)
    assert worst < MAX_TICK_GAP_S, (
        f"the slowest tick took {worst:.2f}s (ceiling {MAX_TICK_GAP_S}s) with "
        f"tier 2 engaged and OCR costing {SLOW_OCR_S}s — ESC is polled between "
        f"ticks, so that is time the user cannot escape a full-screen overlay. "
        f"OCR is running on the UI thread. Gaps: "
        f"{[round(g, 3) for g in gaps]}"
    )
