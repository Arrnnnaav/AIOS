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
from typing import Callable

import win32api
import win32con

# Import order matters: overlay.window pulls in overlay.dpi, which declares
# DPI awareness before any window exists (see ghostcursor/overlay/dpi.py).
from ghostcursor.overlay import window
from ghostcursor.perception import uia
from ghostcursor.reasoning.schema import Step, VerificationKind

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


#: GetAsyncKeyState's low-order bit: set when the key was pressed at any
#: point since the previous call, even if it is no longer down. Without this,
#: a tick that runs long (run_tour performs three UIA tree walks per tick,
#: each able to block, and a tick can exceed a second) can miss a tap
#: entirely — the "currently down" bit alone requires the user to hold the
#: key for the whole tick. ESC is the escape hatch and must not require
#: holding.
_PRESSED_SINCE_LAST_CALL = 0x0001
_CURRENTLY_DOWN = 0x8000


def key_was_pressed(vk: int, key_state=win32api.GetAsyncKeyState) -> bool:
    """True if `vk` is down right now, or was tapped since the last poll."""
    state = key_state(vk)
    return bool(state & _CURRENTLY_DOWN or state & _PRESSED_SINCE_LAST_CALL)


def escape_pressed() -> bool:
    # Polled rather than hooked: the overlay never has focus, so it cannot
    # receive key events of its own.
    return key_was_pressed(VK_ESCAPE)


def get_ui_locale() -> str:
    """Best-effort OS UI language as a BCP-47-ish tag, else "unknown".

    Used only as promotion provenance (which locale an observation was
    recorded under) — never to filter live matching (see grounding.py
    module docstring). Cheap and approximate is fine; an elaborate mapping
    is out of scope here (spec §9 is knowledge-base territory).
    """
    try:
        import ctypes

        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        import locale as locale_module

        name = locale_module.windows_locale.get(lang_id)
        if name:
            return name.replace("_", "-")
    except Exception:
        pass
    return "unknown"


def make_grounder(title_re: str) -> Callable[[object, int], object]:
    """Build the grounder used by a live run_tour: ground, then promote.

    Factored out of run_tour so it is directly testable without a live UIA
    window. Promotion is spec §5's headline mechanism — "the recipe becomes
    more robust every time it is used" — and previously ran only in tests
    because run.py's grounder never called it, leaving rung 1 unreachable
    outside the test suite.

    Note: promotion writes to the in-memory Step object only. There is no
    knowledge base yet (spec §8-10 is deferred), so these observations are
    lost the moment the process exits — this makes today's runs individually
    more robust (rung 1 within a single tour) but does not yet persist
    across runs.
    """
    from ghostcursor.reasoning import grounding

    ui_locale = get_ui_locale()

    def grounder(step, i):
        grounded = grounding.ground(step, title_re, locale=ui_locale)
        if grounded is not None:
            # app_version="unknown": detecting the real installed app
            # version (exe VERSIONINFO / Appx package version) is spec §9
            # scope, deferred along with the rest of the knowledge base.
            grounding.promote(step, grounded, app_version="unknown", locale=ui_locale)
        return grounded

    return grounder


def should_poll_space(current_step: Step | None) -> bool:
    """True only while the current step is actually waiting on a user
    confirmation. Otherwise a space typed into some other application would
    silently advance the tour — inventing progress the user never made.
    """
    return (
        current_step is not None
        and current_step.verification_rule.kind is VerificationKind.USER_CONFIRMS
    )


def run_tour(recipe_path: str, title_re: str, seconds: float) -> int:
    """Drive a hand-authored recipe against a live window."""
    from ghostcursor.reasoning.loop import GuidedTour, State
    from ghostcursor.reasoning.renderer import OverlayRenderer
    from ghostcursor.reasoning.schema import Recipe
    from ghostcursor.reasoning.verification import take_snapshot, verify

    recipe = Recipe.load(recipe_path)
    hwnd = window.create_overlay_window()
    print(f"Guided tour: {recipe.intent!r}. ESC to quit.")

    deadline = time.monotonic() + seconds
    last_printed: str | None = None
    try:
        tour = GuidedTour(
            recipe=recipe,
            grounder=make_grounder(title_re),
            snapshotter=lambda: take_snapshot(title_re),
            verifier=verify,
            renderer=OverlayRenderer(hwnd),
        )
        while time.monotonic() < deadline:
            if escape_pressed():
                print("ESC pressed — exiting.")
                break
            if should_poll_space(tour.current_step) and key_was_pressed(
                win32con.VK_SPACE
            ):
                tour.confirm()

            state = tour.tick()
            if state is State.DONE:
                print("Tour complete.")
                break
            if state is State.FAILED:
                print(f"Stopped: {tour.failure_reason}")
                break
            # Only print when the instruction changes — this loop runs at
            # 4 ticks/sec and the instruction is unchanged across most of
            # them (AWAITING_USER_ACTION dwells while polling).
            instruction = tour.renderer.last_instruction
            if instruction and instruction != last_printed:
                print(f"  step {tour.step_index + 1}: {instruction}")
                last_printed = instruction

            window.pump_messages_nonblocking()
            time.sleep(REFRESH_SECONDS)
        else:
            print("Time limit reached — exiting.")
    finally:
        window.destroy_overlay_window(hwnd)
    return 0


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
    parser.add_argument(
        "--recipe", help="path to a recipe JSON to run as a guided tour"
    )
    args = parser.parse_args()

    if args.recipe:
        return run_tour(args.recipe, args.target, args.seconds)

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
