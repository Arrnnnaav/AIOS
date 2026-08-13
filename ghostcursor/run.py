"""Beginner Project milestone: static hint overlay.

Finds a target control in a window via UIA and draws a ring around it,
refreshed on a timer. No AI, no reasoning loop — see FLOW.md for what this
milestone deliberately does not do yet.

Usage:
    python -m ghostcursor.run                  # targets Notepad
    python -m ghostcursor.run --target Chrome  # any window title (regex)
    python -m ghostcursor.run --seconds 30     # auto-stop after 30s

Press ESC at any time to quit, from any application — the overlay is
click-through and never takes focus, so a normal window-close is not
available. It also stops on its own after --seconds. Both of those exist
because a stranded full-screen overlay is what locks a user out of their
machine.
"""

import argparse
import time

import win32api
import win32con

# Import order matters: overlay.window pulls in overlay.dpi, which declares
# DPI awareness before any window exists (see ghostcursor/overlay/dpi.py).
from ghostcursor.overlay import window
from ghostcursor.perception import uia

REFRESH_SECONDS = 0.25
DEFAULT_TARGET = ".*Notepad.*"
DEFAULT_CONTROL = "Save"
VK_ESCAPE = win32con.VK_ESCAPE


def resolve_target(title_re: str, control_name: str | None) -> tuple[int, int] | None:
    """Screen coordinate to point at, or None if the window isn't open."""
    bbox = None
    if control_name:
        bbox = uia.find_element(title_re, name_re=control_name)
    if bbox is None:
        bbox = uia.window_bbox(title_re)
    if bbox is None:
        return None

    left, top, right, bottom = bbox
    return ((left + right) // 2, (top + bottom) // 2)


def escape_pressed() -> bool:
    # Polled rather than hooked: the overlay never has focus, so it cannot
    # receive key events of its own.
    return bool(win32api.GetAsyncKeyState(VK_ESCAPE) & 0x8000)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ghost Cursor static hint overlay")
    parser.add_argument("--target", default=DEFAULT_TARGET, help="window title regex")
    parser.add_argument(
        "--control",
        default=DEFAULT_CONTROL,
        help="control name to point at; falls back to the window centre",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=60.0,
        help="stop automatically after this long (safety net)",
    )
    args = parser.parse_args()

    hwnd = window.create_overlay_window()
    print(
        f"Overlay running. Pointing at {args.target!r}. ESC to quit "
        f"(auto-stops after {args.seconds:g}s)."
    )

    deadline = time.monotonic() + args.seconds
    missing_reported = False
    try:
        while time.monotonic() < deadline:
            if escape_pressed():
                print("ESC pressed — exiting.")
                break

            point = resolve_target(args.target, args.control)
            if point is None:
                window.clear_hint(hwnd)
                if not missing_reported:
                    print(f"No window matching {args.target!r} — waiting for it.")
                    missing_reported = True
            else:
                missing_reported = False
                window.set_hint(hwnd, *point)

            window.pump_messages_nonblocking()
            time.sleep(REFRESH_SECONDS)
        else:
            print("Time limit reached — exiting.")
    except KeyboardInterrupt:
        print("Interrupted — exiting.")
    finally:
        window.destroy_overlay_window(hwnd)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
