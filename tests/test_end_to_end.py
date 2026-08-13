"""End-to-end check of the real pipeline: perception -> coordinate -> overlay.

The unit-level overlay tests prove the overlay draws where it is *told* to.
This proves the whole chain agrees: a window is found by the perception layer,
its coordinates survive the trip, and the ring lands on the actual window on
screen — the property that was silently broken while the coordinate space was
flipping between logical and physical pixels.

Uses a synthetic target window of known geometry rather than a real app, so
the expected answer is exact and the test needs nothing open beforehand.

Run:  python -m tests.test_end_to_end      (from D:\\PROJECTS\\AIOS)
"""

import sys
import time

import mss
import numpy as np
import win32gui

from ghostcursor import run as gc_run
from ghostcursor.overlay import dpi
from ghostcursor.overlay import window as ov
from ghostcursor.perception import uia
from tests import backdrop, test_overlay

TARGET_TITLE = "GhostCursorTestTarget"
TARGET_RECT = (300, 200, 600, 500)  # left, top, width, height
TARGET_SCREEN_RECT = (300, 200, 900, 700)  # same window as left/top/right/bottom
TOLERANCE_PX = 3

_results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((ok, name, detail))


def settle() -> None:
    for _ in range(3):
        win32gui.PumpWaitingMessages()
        time.sleep(0.08)


def run() -> None:
    left, top, width, height = TARGET_RECT
    expected = (left + width // 2, top + height // 2)

    # Full-screen backdrop first so nothing else on the real desktop (cyan
    # terminal text, for one) can be mistaken for the ring. The target window
    # is created after it, and so sits above it.
    base = backdrop.create_backdrop()
    target = backdrop.create_backdrop(rect=TARGET_RECT, title=TARGET_TITLE)
    hwnd = None
    try:
        settle()

        # --- perception finds the window and reports the right rect ---------
        bbox = gc_run.resolve_target(f".*{TARGET_TITLE}.*", None)
        check(
            "perception resolves the target's centre",
            bbox is not None
            and abs(bbox[0] - expected[0]) <= TOLERANCE_PX
            and abs(bbox[1] - expected[1]) <= TOLERANCE_PX,
            f"got {bbox}, expected ~{expected}",
        )

        # --- the ring actually lands on that window on screen ---------------
        hwnd = ov.create_overlay_window()
        ov.set_hint(hwnd, *bbox)
        settle()

        with mss.MSS() as sct:
            frame = np.array(sct.grab(dpi.capture_region()))[:, :, :3]
        b, g, r = frame[:, :, 0], frame[:, :, 1], frame[:, :, 2]
        ring = (r < 80) & (g > 150) & (b > 190)

        ys, xs = np.where(ring)
        if not len(xs):
            check("ring rendered on screen", False, "no ring pixels found")
            return
        check("ring rendered on screen", True, f"{len(xs)} px")

        centre = (int(round(xs.mean())), int(round(ys.mean())))
        check(
            "ring centred on the target window",
            abs(centre[0] - expected[0]) <= TOLERANCE_PX
            and abs(centre[1] - expected[1]) <= TOLERANCE_PX,
            f"ring centre {centre}, target centre {expected}",
        )
        # --- offscreen / minimized targets must be refused -------------------
        # Windows parks minimized windows at (-32000, -32000); pointing there
        # draws the hint into the void with no visible error.
        check(
            "minimized-window rect rejected",
            not uia.is_on_screen((-32000, -32000, -31800, -31900)),
        )
        check(
            "degenerate zero-area rect rejected",
            not uia.is_on_screen((0, 0, 0, 0)),
        )
        check(
            "fully off-desktop rect rejected",
            not uia.is_on_screen((99999, 99999, 100500, 100400)),
        )
        check("on-screen rect accepted", uia.is_on_screen(TARGET_SCREEN_RECT))

        check(
            "ring lies inside the target window's bounds",
            xs.min() >= left
            and xs.max() <= left + width
            and ys.min() >= top
            and ys.max() <= top + height,
            f"ring bbox x {int(xs.min())}-{int(xs.max())} "
            f"y {int(ys.min())}-{int(ys.max())}, window {TARGET_RECT}",
        )
    finally:
        if hwnd is not None:
            ov.destroy_overlay_window(hwnd)
        backdrop.destroy_backdrop(target)
        backdrop.destroy_backdrop(base)


def main() -> int:
    try:
        test_overlay.require_capturable_desktop()
    except test_overlay.EnvironmentUnavailable as exc:
        print(f"[SKIP] ENVIRONMENT: {exc}")
        return 2

    run()
    width = max(len(n) for _, n, _ in _results)
    failed = sum(1 for ok, _, _ in _results if not ok)
    for ok, name, detail in _results:
        suffix = f"   {detail}" if detail else ""
        print(f"[{'PASS' if ok else 'FAIL'}] {name.ljust(width)}{suffix}")
    print(f"\n{len(_results) - failed}/{len(_results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
