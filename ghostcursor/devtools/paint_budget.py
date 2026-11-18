"""Measures what one full-overlay cue paint actually costs on this machine.

`pointer_path.frame_count` and `CueBudget` both refuse a `frame_budget_ms`
they were not given, because a plausible constant is the placeholder that
measurement exists to replace — and the number every test would silently
agree with. This is the thing that produces the number.

What it measures is the whole checked round trip a real frame pays: one
coordinate-space agreement check, `set_cue`/synchronous `WM_PAINT`, and the
second coordinate-space agreement check that proves the space held across the
paint. Timing only `set_cue` would certify an implementation production no
longer runs (D116). The full virtual-screen fill still scales with desktop
area, so the number is valid only for the monitor topology recorded beside it.

Read-only with respect to the user's machine: it creates its own overlay,
paints into it, and destroys it. It moves no cursor and synthesizes no input.

    py -3.12 -m ghostcursor.devtools.paint_budget --frames 300

The reported budget is the p99 rounded up, not the mean. A frame budget is a
deadline: the mean tells you what usually happens, and the frames that blow
the poll interval are exactly the ones that do not.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from dataclasses import dataclass
from typing import Callable

from ghostcursor import act_overlay
from ghostcursor.act_protocol import TrustClass
from ghostcursor.coordinate_space import BracketedGeometry, observe_bracketed
from ghostcursor.overlay import dpi, window
from ghostcursor.overlay.cue import CueScene, label_box


class PaintMeasurementRefused(RuntimeError):
    """The frame could not hold one trustworthy coordinate space."""


def _paint_checked_frame(
    hwnd: int,
    scene: CueScene,
    geometry: BracketedGeometry,
    rectangle: tuple[int, int, int, int],
    *,
    check: Callable[[int, object, tuple[int, int, int, int]], tuple[str, ...]] = (
        act_overlay._coordinate_disagreements
    ),
    paint: Callable[[int, CueScene], None] = window.set_cue,
) -> None:
    """Run the exact pre-check/paint/post-check transaction production pays."""

    reasons = tuple(check(hwnd, geometry, rectangle))
    if reasons:
        raise PaintMeasurementRefused(
            "coordinate space refused before measured paint: " + "; ".join(reasons)
        )
    paint(hwnd, scene)
    reasons = tuple(check(hwnd, geometry, rectangle))
    if reasons:
        raise PaintMeasurementRefused(
            "coordinate space changed during measured paint: " + "; ".join(reasons)
        )


@dataclass(frozen=True)
class PaintMeasurement:
    """One campaign's timings, in milliseconds."""

    frames: int
    samples: tuple[float, ...]
    bounds: tuple[int, int, int, int]
    monitors: int

    @property
    def mean_ms(self) -> float:
        return statistics.fmean(self.samples)

    @property
    def median_ms(self) -> float:
        return statistics.median(self.samples)

    @property
    def p99_ms(self) -> float:
        ordered = sorted(self.samples)
        index = min(len(ordered) - 1, int(round(0.99 * (len(ordered) - 1))))
        return ordered[index]

    @property
    def max_ms(self) -> float:
        return max(self.samples)

    @property
    def budget_ms(self) -> int:
        """The number to hand `CueBudget`. p99 rounded up, floor of 1.

        Not the mean. A frame budget is a deadline, and the frames that
        overrun the interrupt poll interval are precisely the ones a mean
        hides.
        """

        return max(1, math.ceil(self.p99_ms))  # 2.0004 ms is 3, never 2

    def as_dict(self) -> dict:
        return {
            "frames": self.frames,
            "mean_ms": round(self.mean_ms, 3),
            "median_ms": round(self.median_ms, 3),
            "p99_ms": round(self.p99_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "budget_ms": self.budget_ms,
            "virtual_screen": list(self.bounds),
            "monitors": self.monitors,
        }


def measure(frames: int = 300, *, hold_s: float = 0.0) -> PaintMeasurement:
    """Paint `frames` cue frames at moving positions and time each one."""

    left, top, width, height = dpi.virtual_screen_rect()
    bounds = (left, top, left + width, top + height)
    hwnd = window.create_overlay_window()
    samples: list[float] = []
    try:
        metrics = window.measure_label(hwnd, "New Slide")
        # A moving target and a moving pointer, so no frame can be cheap
        # because it repainted an identical scene. The invalidation is
        # unconditional either way, but a static scene would still be an
        # unrepresentative one.
        for index in range(frames):
            x = left + 200 + (index * 7) % max(1, width - 400)
            y = top + 200 + (index * 11) % max(1, height - 400)
            target = (x, y, x + 120, y + 40)
            pointer = (x + 60, y + 20)
            scene = CueScene(
                pointer=pointer,
                target=target,
                label="New Slide",
                trust=TrustClass.NEUTRAL,
                final=False,
                label_rect=label_box(
                    pointer, "New Slide", metrics, bounds=bounds, avoid=target
                ),
            )
            # This producer-side bracket is intentionally outside the timed
            # section. Production receives it with the observation; one frame
            # pays only the two overlay-side checks around its paint.
            geometry = observe_bracketed(lambda: [target])
            started = time.perf_counter()
            _paint_checked_frame(hwnd, scene, geometry, target)
            samples.append((time.perf_counter() - started) * 1000.0)
            window.pump_messages_nonblocking()
        if hold_s:
            # Optional: leave the last cue up so a human can confirm it is
            # actually drawn where the numbers say it is.
            deadline = time.monotonic() + hold_s
            while time.monotonic() < deadline:
                window.pump_messages_nonblocking()
                time.sleep(0.02)
    finally:
        window.clear_cue(hwnd)
        window.destroy_overlay_window(hwnd)

    return PaintMeasurement(
        frames=frames,
        samples=tuple(samples),
        bounds=bounds,
        monitors=len(dpi.monitor_topology()),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument(
        "--hold",
        type=float,
        default=0.0,
        help="seconds to leave the final cue on screen, for a human to look at",
    )
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()

    result = measure(arguments.frames, hold_s=arguments.hold)
    if arguments.json:
        print(json.dumps(result.as_dict(), indent=2))
        return 0

    print(f"frames            {result.frames}")
    print(f"virtual screen    {result.bounds}  ({result.monitors} monitor(s))")
    print(f"mean              {result.mean_ms:.3f} ms")
    print(f"median            {result.median_ms:.3f} ms")
    print(f"p99               {result.p99_ms:.3f} ms")
    print(f"max               {result.max_ms:.3f} ms")
    print(f"frame_budget_ms   {result.budget_ms}   <- p99 rounded up")
    print()
    print("A budget above the 50ms interrupt poll interval means geometry is")
    print("not affordable here and `schedule_for` will refuse it outright.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
