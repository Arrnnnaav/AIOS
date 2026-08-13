"""Verification harness for the Ghost Cursor overlay.

Proves the properties that matter and that are easy to get silently wrong:

  1. TRANSPARENCY — the overlay must not obscure what is underneath it.
  2. CLICK-THROUGH — the overlay must not intercept the user's mouse.
  3. NO STALE PIXELS — moving/clearing a hint must not leave the old one behind.

Verified against a controlled solid-colour backdrop (tests/backdrop.py) rather
than the live desktop, so unrelated screen activity can't produce false
results.

Run:  python -m tests.test_overlay      (from D:\\PROJECTS\\AIOS)

Every path tears both windows down in a finally block. A stranded full-screen
window is the exact failure mode that locks a user out of their machine.
"""

import sys
import time

import mss
import numpy as np
import win32con
import win32gui

# Importing dpi declares DPI awareness before any window is created and before
# mss can flip it underneath us — see ghostcursor/overlay/dpi.py.
from ghostcursor.overlay import dpi
from ghostcursor.overlay import window as ov
from tests import backdrop

RING_SLACK = 6  # GDI pen width spill around the nominal radius

_results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((ok, name, detail))


def grab() -> np.ndarray:
    # dpi.capture_region(), never mss.monitors[1] — see ghostcursor/overlay/dpi.py
    with mss.MSS() as sct:
        return np.array(sct.grab(dpi.capture_region()))[:, :, :3]


class EnvironmentUnavailable(RuntimeError):
    """Raised when the machine can't support these tests at all."""


def require_capturable_desktop() -> None:
    """Fail loudly, and as an *environment* problem, when screen capture isn't
    available.

    These tests assert against real pixels, so they need an interactive
    desktop session. Run from a service, an SSH session, a locked workstation
    or a context with no window station and BitBlt returns an error or a black
    frame — which otherwise shows up as a pile of confusing assertion failures
    that look like code bugs. This distinguishes "your code is broken" from
    "this machine can't run these tests".
    """
    expected = dpi.capture_region()
    try:
        frame = grab()
    except Exception as exc:  # mss raises its own error types
        raise EnvironmentUnavailable(
            f"screen capture failed ({type(exc).__name__}: {exc}). "
            "These tests need an interactive desktop session."
        ) from exc

    if frame.shape[0] != expected["height"] or frame.shape[1] != expected["width"]:
        raise EnvironmentUnavailable(
            f"captured {frame.shape[1]}x{frame.shape[0]} but the desktop is "
            f"{expected['width']}x{expected['height']} — the capture doesn't "
            "correspond to this desktop (usually a DPI-awareness mismatch)."
        )

    if not frame.any():
        raise EnvironmentUnavailable(
            "captured an entirely black frame — no visible desktop session "
            "(locked screen, headless session, or no window station)."
        )


def settle() -> None:
    """Let the compositor catch up before screenshotting."""
    for _ in range(3):
        win32gui.PumpWaitingMessages()
        time.sleep(0.08)


def classify(frame: np.ndarray) -> dict[str, np.ndarray]:
    b, g, r = frame[:, :, 0], frame[:, :, 1], frame[:, :, 2]
    return {
        "backdrop": (np.abs(b.astype(int) - backdrop.BACKDROP_BGR[0]) < 24)
        & (np.abs(g.astype(int) - backdrop.BACKDROP_BGR[1]) < 24)
        & (np.abs(r.astype(int) - backdrop.BACKDROP_BGR[2]) < 24),
        "ring": (r < 80) & (g > 150) & (b > 190),
        "magenta": (r > 200) & (g < 60) & (b > 200),
    }


def run() -> None:
    bd = backdrop.create_backdrop()
    hwnd = None
    try:
        settle()
        h, w = grab().shape[:2]
        target = (w // 2, h // 2)
        moved = (w // 2 + 300, h // 2 + 150)
        radius = 24

        hwnd = ov.create_overlay_window()
        settle()

        # --- extended styles ------------------------------------------------
        ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        for flag, label in (
            (win32con.WS_EX_LAYERED, "WS_EX_LAYERED"),
            (win32con.WS_EX_TRANSPARENT, "WS_EX_TRANSPARENT"),
            (win32con.WS_EX_TOPMOST, "WS_EX_TOPMOST"),
            (win32con.WS_EX_TOOLWINDOW, "WS_EX_TOOLWINDOW"),
        ):
            check(f"style {label} set", bool(ex & flag))

        # --- click-through --------------------------------------------------
        # WindowFromPoint does real hit-testing. With WS_EX_TRANSPARENT the
        # overlay must be invisible to it, so the hit must land on the
        # backdrop sitting underneath.
        hit = win32gui.WindowFromPoint(target)
        check(
            "click-through: hit-test passes to window beneath",
            hit == bd,
            f"hit={hit} backdrop={bd} overlay={hwnd}",
        )

        # --- transparent when idle -------------------------------------------
        settle()
        idle = classify(grab())
        total = h * w
        check(
            "idle overlay is fully transparent",
            idle["backdrop"].mean() > 0.98,
            f"{100 * idle['backdrop'].mean():.2f}% of screen is still backdrop",
        )
        check(
            "colorkey never renders as visible magenta",
            int(idle["magenta"].sum()) == 0,
            f"{int(idle['magenta'].sum())} magenta px",
        )

        # --- hint rendering ---------------------------------------------------
        ov.set_hint(hwnd, *target, radius=radius)
        settle()
        shown = classify(grab())

        ring_px = int(shown["ring"].sum())
        check("hint ring visible", ring_px > 50, f"{ring_px} ring px")

        ys, xs = np.where(shown["ring"])
        if ring_px:
            bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
            allowed = (
                target[0] - radius - RING_SLACK,
                target[1] - radius - RING_SLACK,
                target[0] + radius + RING_SLACK,
                target[1] + radius + RING_SLACK,
            )
            check(
                "hint drawn at the requested coordinate",
                bbox[0] >= allowed[0]
                and bbox[1] >= allowed[1]
                and bbox[2] <= allowed[2]
                and bbox[3] <= allowed[3],
                f"bbox={bbox} allowed={allowed}",
            )

        non_backdrop = total - int(shown["backdrop"].sum())
        check(
            "overlay obscures nothing except the hint",
            non_backdrop < 4 * ring_px + 500,
            f"{non_backdrop} px are neither backdrop nor negligible "
            f"(ring is {ring_px} px)",
        )

        # --- moving a hint must not leave the old one behind -----------------
        ov.set_hint(hwnd, *moved, radius=radius)
        settle()
        after_move = classify(grab())
        ys2, xs2 = np.where(after_move["ring"])
        if len(xs2):
            stale = bool((xs2 < target[0] - radius - 40).any()) and bool(
                (ys2 < target[1] - radius - 40).any()
            )
            check(
                "moving the hint leaves no stale ring",
                not stale and int(xs2.min()) > target[0],
                f"ring bbox after move x {int(xs2.min())}-{int(xs2.max())}, "
                f"old hint was at x~{target[0]}",
            )
        else:
            check("moving the hint leaves no stale ring", False, "no ring after move")

        # --- clearing ---------------------------------------------------------
        ov.clear_hint(hwnd)
        settle()
        cleared = classify(grab())
        check(
            "clear_hint removes the hint completely",
            int(cleared["ring"].sum()) == 0,
            f"{int(cleared['ring'].sum())} ring px remain",
        )
        check(
            "screen fully restored after clear",
            cleared["backdrop"].mean() > 0.98,
            f"{100 * cleared['backdrop'].mean():.2f}% backdrop",
        )
    finally:
        if hwnd is not None:
            ov.destroy_overlay_window(hwnd)
        backdrop.destroy_backdrop(bd)

    check("overlay destroyed on exit", not win32gui.IsWindow(hwnd))


def main() -> int:
    try:
        require_capturable_desktop()
    except EnvironmentUnavailable as exc:
        print(f"[SKIP] ENVIRONMENT: {exc}")
        return 2  # distinct from 1, so CI can tell "can't run" from "failed"

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
