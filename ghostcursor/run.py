"""Entry point for Ghost Cursor.

Two modes:

- No `--recipe`: the original static-hint mode. Finds a target control in a
  window via UIA and draws a ring around it, refreshed on a timer. No
  reasoning loop.
- `--recipe <path>`: runs a hand-authored recipe as a guided tour through
  the observe-act-verify state machine (`ghostcursor.reasoning.loop`),
  grounding each step against the live UI, promoting what it learns, and
  persisting learned observations to the on-disk knowledge base
  (`ghostcursor.memory.store`) so later runs against the same app resolve
  faster. See FLOW.md for the full call graph and "you are here" marker.

Usage:
    python -m ghostcursor.run                  # targets Notepad
    python -m ghostcursor.run --target Chrome  # any window title (regex)
    python -m ghostcursor.run --seconds 30     # auto-stop after 30s
    python -m ghostcursor.run --recipe path/to/recipe.json --target Chrome

Press ESC at any time to quit, from any application — the overlay is
click-through and never takes focus, so a normal window-close is not
available. It also stops on its own after --seconds. Both of those exist
because a stranded full-screen overlay is what locks a user out of their
machine.
"""

import argparse
import os
import re
import time
from pathlib import Path
from typing import Callable

import win32api
import win32con
import win32gui

# Import order matters: overlay.window pulls in overlay.dpi, which declares
# DPI awareness before any window exists (see ghostcursor/overlay/dpi.py).
from ghostcursor.overlay import window
from ghostcursor.overlay import bar
from ghostcursor.perception import uia
from ghostcursor.perception.warmup import DEFAULT_WARMUP_BUDGET_S, WarmUp
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
#: a tick that runs long (perception is now on a worker thread, but grounding,
#: persistence and the message pump still run here and a tick can exceed a
#: second) can miss a tap entirely — the "currently down" bit alone requires the user to hold the
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


def hydrate_recipe(recipe, app_id: str, store) -> int:
    """Load each step's previously learned observations from disk.

    This is the half that was missing: promotion already discovered
    AutomationIds and wrote them onto the in-memory Step, but nothing read
    them back, so every run re-learned from scratch.

    Per controller ruling P2: this REPLACES a step's `confirmed` list rather
    than merging it with whatever the recipe JSON shipped. Recipes are
    hand-authored with `confirmed: []` because documentation cannot supply
    an AutomationId, so there is nothing to merge, and replacing keeps the
    store the single source of truth for learned data.
    """
    from ghostcursor.reasoning.identity import step_key

    loaded = 0
    for step in recipe.steps:
        observations = store.observations_for(step_key(recipe.intent, step), app_id)
        if observations:
            step.target_descriptor.confirmed = observations
            loaded += len(observations)
    return loaded


def persist_step(
    recipe_intent: str, step, app_id: str, store, observation=None
) -> None:
    """Write what this step learned to disk, idempotently.

    Pass `observation` to write only that one. The grounder does, because it
    is called on every DECIDING tick: writing the step's whole `confirmed`
    list each time re-wrote observations hydrated from previous runs that this
    tour never grounded, incrementing their `ok_count` on every tick and
    issuing a write per observation per tick. `ok_count` is meant to count
    times-observed, not times-persisted.

    Omit it to write every confirmed observation — the whole-step form, for
    callers that genuinely mean "flush this step".
    """
    from ghostcursor.reasoning.identity import step_key

    key = step_key(recipe_intent, step)
    to_write = (
        [observation] if observation is not None else step.target_descriptor.confirmed
    )
    for entry in to_write:
        store.record(key, app_id, entry)


def make_grounder(
    title_re: str, app_info=None, store=None, recipe_intent: str = ""
) -> Callable[[object, int], object]:
    """Build the grounder used by the live compiled tour: ground, promote, persist.

    Factored out of the production tour so it is directly testable without a live UIA
    window. Promotion is spec §5's headline mechanism — "the recipe becomes
    more robust every time it is used" — and previously ran only in tests
    because run.py's grounder never called it, leaving rung 1 unreachable
    outside the test suite.

    When `store` and `app_info` are supplied, promoted observations are also
    written to disk immediately, so they survive past this process exiting
    and are available to `hydrate_recipe` on the next run. Backwards
    compatible: with no store/app_info (the default), behaviour is unchanged
    from before — grounds and promotes in-memory only, with
    app_version="unknown".
    """
    import sqlite3

    from ghostcursor.reasoning import grounding

    ui_locale = get_ui_locale()
    app_version = app_info.version if app_info else "unknown"
    app_id = app_info.app_id if app_info else None
    # Persistence is best-effort: a full disk, a read-only file, or
    # "database is locked" from a second Ghost Cursor process must degrade
    # grounding, not end the tour on a raw traceback. Report once, not once
    # per tick, so a repeated failure does not spam the console.
    warned = False

    def grounder(step, i, elements=None):
        nonlocal warned
        # `elements` is the tree walk OBSERVING already did this tick.
        grounded = grounding.ground(
            step,
            title_re,
            locale=ui_locale,
            app_version=app_version,
            elements=elements,
        )
        if grounded is not None:
            if os.environ.get("GHOSTCURSOR_DEBUG_PERCEPTION") == "1":
                # Gate 2 resets the count on any OCR-grounded run, so which
                # tier actually grounded the step has to be observable. Without
                # it a run reports only "Tour complete." -- the outcome-only
                # signal that let Open Folder's tier-1 perception go dark while
                # OCR quietly carried the workflow (D069).
                print(
                    f"Ghost Cursor: step {i} provenance "
                    f"source={grounded.source} rung={grounded.rung} "
                    f"name={grounded.name!r}"
                )
            grounding.promote(step, grounded, app_version=app_version, locale=ui_locale)
            # Second half of the same guard as promote()'s: nothing tier 2
            # produced reaches the knowledge base (D030). Without this, the
            # lookup below matches on `automation_id`, which for an OCR target
            # is "" — so the only thing keeping pixel-derived rows out of the
            # database was that no stored row happened to have an empty id.
            # That is a coincidence, not a construction.
            confirmed_source = grounded.source == grounding.CONFIRMED_SOURCE
            if store is not None and app_id is not None and confirmed_source:
                # Write only what promote() just recorded for this grounding —
                # not the step's whole confirmed list. This runs every tick,
                # and rewriting observations hydrated from earlier runs would
                # inflate their ok_count and cost a write each per tick.
                learned = next(
                    (
                        obs
                        for obs in step.target_descriptor.confirmed
                        if obs.automation_id == grounded.automation_id
                        and obs.app_version == app_version
                    ),
                    None,
                )
                try:
                    persist_step(
                        recipe_intent, step, app_id, store, observation=learned
                    )
                except sqlite3.Error as exc:
                    if not warned:
                        print(f"Persistence disabled for the rest of this run: {exc}")
                        warned = True
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


def confirmation_focus_is_safe(target_hwnd: int, bar_hwnd: int | None = None) -> bool:
    """SPACE may confirm only when the intended application owns focus."""
    foreground = win32gui.GetForegroundWindow()
    return bool(target_hwnd) and foreground == target_hwnd and foreground != bar_hwnd


def space_confirmation_requested(
    target_hwnd: int, bar_hwnd: int | None = None
) -> bool:
    """Read one safe, explicit confirmation from the live desktop."""
    return confirmation_focus_is_safe(target_hwnd, bar_hwnd) and key_was_pressed(
        win32con.VK_SPACE, key_state=win32api.GetAsyncKeyState
    )


class CompiledTourControls:
    """Focusable Stop/Pause/Ask host for the shared compiled executor.

    The cursor overlay is deliberately click-through and can never host a
    button. A compiled tour therefore needs the same separate focusable rail
    as the v1 tour. `poll()` is called from the executor's message-pump seam;
    the executor reads the resulting abort/pause state through callbacks, so
    the bar never reaches into reasoning state or invents progress.
    """

    def __init__(
        self,
        hwnd: int,
        *,
        bar_api=bar,
        pump_messages=window.pump_messages_nonblocking,
        escape_source=None,
    ) -> None:
        self.hwnd = hwnd
        self._bar = bar_api
        self._pump_messages = pump_messages
        self._escape_source = escape_source or escape_pressed
        self._stop_requested = False
        self._paused = False
        #: What the bar should say while the tour is simply running. The
        #: executor replaces it as steps advance; until it does, a rail that
        #: named no step at all was the state this text is here to end.
        self._step_text = "Running"

    def poll(self) -> None:
        """Pump once and consume each edge-triggered bar request once."""
        self._pump_messages()
        requests = self._bar.bar_state(self.hwnd)
        self._bar.clear_requests(self.hwnd)
        if requests.stop_requested:
            self._stop_requested = True
            self._bar.set_status(self.hwnd, "Stopping…")
        if requests.pause_requested:
            self._paused = not self._paused
            # Resuming restores the STEP, not the word "Running": the executor
            # reports only on change, so a resume that wrote "Running" would
            # leave the rail lying about progress until the next step began --
            # and on the last step, until the tour ended.
            self._bar.set_status(
                self.hwnd, "Paused" if self._paused else self._step_text
            )
        if requests.ask_requested:
            self._bar.set_status(
                self.hwnd, "Finish or stop the active tour before asking"
            )

    def report_step(self, index: int, total: int) -> None:
        """Show which step is running. Called BY the executor, never polled.

        The rail cannot read reasoning state and must not: a surface that
        counted steps itself could disagree with the executor about which one
        is running, which is the invented progress this class exists to avoid.

        A stop already under way keeps its own message -- "Stopping…" is the
        more urgent fact, and overwriting it would make the rail look like it
        had ignored the request.
        """
        self._step_text = f"Step {index + 1} of {total}"
        if not self._paused and not self._stop_requested:
            self._bar.set_status(self.hwnd, self._step_text)

    def should_abort(self) -> bool:
        return self._stop_requested or self._escape_source()

    def should_pause(self) -> bool:
        return self._paused

    def dispose(self) -> None:
        self._bar.destroy_bar_window(self.hwnd)


def create_compiled_tour_controls() -> CompiledTourControls:
    """Create the real compiled control rail without stealing app focus."""
    hwnd = bar.create_bar_window()
    try:
        bar.set_status(hwnd, "Running")
        return CompiledTourControls(hwnd)
    except Exception:
        bar.destroy_bar_window(hwnd)
        raise

def main() -> int:
    parser = argparse.ArgumentParser(description="Ghost Cursor guided UI assistant")
    parser.add_argument("--target", default=None, help="window title regex")
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
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--goal", help="natural-language goal to classify and guide")
    args = parser.parse_args()

    if args.goal:
        from ghostcursor.reasoning.planner import PlanStatus, plan_compiled_goal

        result = plan_compiled_goal(args.goal, target_title_re=args.target)
        print(f"Planner: {result.status.value} ({result.confidence:.2f}) — {result.explanation}")
        if result.plan is None or result.intent_id is None:
            return 2
        if result.status not in (PlanStatus.SUPPORTED, PlanStatus.MODEL_UNAVAILABLE_FALLBACK, PlanStatus.INVALID_MODEL_OUTPUT):
            return 2
        return run_tour_for_workflow(
            result.plan,
            seconds=args.seconds,
        )

    target = args.target or DEFAULT_TARGET
    hwnd = window.create_overlay_window()
    print(
        f"Overlay running. Pointing at {target!r}. ESC to quit "
        f"(auto-stops after {args.seconds:g}s)."
    )

    deadline = time.monotonic() + args.seconds
    missing_reported = False
    try:
        while time.monotonic() < deadline:
            if escape_pressed():
                print("ESC pressed — exiting.")
                break

            point = resolve_target(target, args.control)
            if point is None:
                window.clear_hint(hwnd)
                if not missing_reported:
                    print(f"No window matching {target!r} — waiting for it.")
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


# ---------------------------------------------------------------------------
# Schema v2 launch entry point
# ---------------------------------------------------------------------------


def run_tour_for_workflow(
    workflow,
    *,
    seconds: float,
    clock=time.monotonic,
    sleeper=time.sleep,
    warmup_budget_s: float = DEFAULT_WARMUP_BUDGET_S,
) -> int:
    """Launch a guided tour from a `CompiledWorkflow`, never from a path.

    The production-facing v2 entry point: `--goal` and Ask hand the exact
    object planning returned straight to the tour, with no second artifact
    lookup that could resolve to different bytes than the ones the plan was
    authorized against.

    **Every authority input is chosen here, not accepted here.** The window
    reader, the catalog loader, and the project root are what revalidation
    decides with -- a caller who supplies them supplies the PID, executable,
    title, and version that authorize the launch, which is the same bypass the
    boolean callback was, just spelled with more arguments. This function takes
    none of them. `clock` and `sleeper` remain parameters because they drive
    the timeline and decide nothing about authority.

    Revalidation happens FIRST, before anything creates a window. Ordering is
    the whole guarantee: an overlay is full-screen, topmost and click-through,
    so a launch that aborts after creating one has already put a window over
    the user's screen for a workflow it then refuses to run. On any change
    this raises `WorkflowUnavailable` and nothing is drawn -- runtime never
    substitutes the new artifacts transparently and never falls back to the
    old in-memory workflow, because one runs bytes nobody accepted and the
    other runs bytes someone withdrew.

    `--recipe <path>` has no counterpart here on purpose. A path-based loader
    exists only inside the developer acceptance harness and is unreachable
    from planning, Ask, and this entry point.
    """
    from ghostcursor.packs.activation import load_catalog
    from ghostcursor.packs.workflow import live_window_reader

    from ghostcursor.overlay import window as overlay_window

    project_root = Path(__file__).resolve().parent.parent
    return _launch_compiled_workflow(
        workflow,
        seconds=seconds,
        reload_catalog=lambda: load_catalog(project_root),
        read_window=live_window_reader(),
        project_root=project_root,
        clock=clock,
        sleeper=sleeper,
        warmup_budget_s=warmup_budget_s,
        create_overlay=overlay_window.create_overlay_window,
    )


def _launch_compiled_workflow(
    workflow,
    *,
    seconds: float,
    reload_catalog,
    read_window,
    project_root,
    clock,
    sleeper,
    warmup_budget_s: float,
    create_overlay,
    observe=None,
    renderer=None,
) -> int:
    """The revalidation seam. Private, and hermetic tests are its only callers.

    Separated from the public entry point so a test can substitute a screen, a
    catalog, and a filesystem root without those becoming things production
    code is able to pass. Nothing importable as public API reaches this with
    fabricated facts: `run_tour_for_workflow()` selects all three itself and
    offers no way to override them.
    """
    from ghostcursor.packs.workflow import revalidate

    revalidate(
        workflow,
        reload_catalog=reload_catalog,
        read_window=read_window,
        project_root=project_root,
    )

    # Only now may a window exist. `create_overlay` is injected here, and only
    # here, so a test can prove the ordering by asserting it was never reached.
    return _run_compiled_tour(
        workflow,
        seconds=seconds,
        clock=clock,
        sleeper=sleeper,
        warmup_budget_s=warmup_budget_s,
        create_overlay=create_overlay,
        observe=observe,
        renderer=renderer,
    )


def _run_compiled_tour(
    workflow,
    *,
    seconds: float,
    clock,
    sleeper,
    warmup_budget_s: float,
    create_overlay,
    observe=None,
    renderer=None,
    on_grounding=None,
) -> int:
    """Run the compiled workflow through the shared executor.

    The SAME `execute_compiled_workflow()` the candidate harness calls. Two
    executors would mean acceptance certified semantics production does not
    have, so there is one, and the cutover changes only which authority path
    arrives here.

    The overlay is created here and nowhere earlier: revalidation has already
    run and passed by the time this is reached.
    """
    from ghostcursor.reasoning.compiled_tour import (
        RunOutcome,
        execute_compiled_workflow,
    )
    from ghostcursor.reasoning.renderer import OverlayRenderer
    from ghostcursor.reasoning.staleness import Freshness

    # The ladder is built by the perception composition below, but the
    # renderer needs it now. A one-slot cell rather than a hardcoded FRESH:
    # claiming every hint is confirmed-current is the single thing the
    # staleness ladder exists to deny, and a hint that never dims is one the
    # user cannot tell from a live one.
    renderer_ladder = [None]
    hwnd = create_overlay()
    controls = None
    try:
        if renderer is None:
            renderer = OverlayRenderer(
                hwnd,
                freshness_source=lambda: (
                    renderer_ladder[0].freshness()
                    if renderer_ladder[0] is not None
                    else Freshness.HIDDEN
                ),
            )
            try:
                controls = create_compiled_tour_controls()
            except Exception as exc:
                # Additive safety UI: ESC remains the mandatory escape hatch
                # if the separate focusable rail cannot be registered.
                print(f"Control bar unavailable: {exc}")
        else:
            renderer_ladder = None
        stop_perception = None
        if observe is None:  # pragma: no cover - needs a real desktop
            from ghostcursor.perception import tier2 as tier2_module
            from ghostcursor.perception.compiled import build_compiled_perception

            perception = build_compiled_perception(
                workflow, clock, tier2=tier2_module.build_controller(clock)
            )
            if renderer_ladder is not None:
                renderer_ladder[0] = perception.source.ladder
            # ONE start operation, shared with the candidate harness. Starting
            # the worker and arming the health grace are the same event, and
            # anywhere they are two steps the gap between them is spent
            # against a worker that does not exist yet.
            #
            # The returned stop is KEPT and used. Reaching past it to
            # `service.stop()` stops the worker but leaves the composition
            # believing it is still running, so a later start would be treated
            # as a no-op and the health grace would never be armed for the
            # worker that actually followed. One lifecycle owner means one
            # stop as well as one start.
            observe, on_grounding, stop_perception = perception.start()

        try:
            def _pump_compiled_ui():
                if controls is not None:
                    controls.poll()
                else:
                    pump_messages()

            result = execute_compiled_workflow(
                workflow,
                observe=observe,
                renderer=renderer,
                clock=clock,
                sleeper=sleeper,
                seconds=seconds,
                should_abort=(
                    controls.should_abort
                    if controls is not None
                    else escape_pressed
                ),
                should_pause=(
                    controls.should_pause if controls is not None else None
                ),
                confirmation_requested=lambda: space_confirmation_requested(
                    workflow.target.hwnd,
                    controls.hwnd if controls is not None else None,
                ),
                pump=_pump_compiled_ui,
                on_grounding=on_grounding,
                on_step=(controls.report_step if controls is not None else None),
            )
        finally:
            if stop_perception is not None:  # pragma: no cover - real desktop
                stop_perception()
    finally:
        try:
            if controls is not None:
                controls.dispose()
        finally:
            # Every exit path, exceptions included. The overlay is full-screen,
            # topmost, click-through and has no title bar: one left behind after
            # a failure, a timeout or an ESC is one the user cannot close.
            _destroy_overlay(hwnd)

    print(
        f"{result.outcome.value}: {result.steps_completed}/{result.steps_total} "
        f"step(s), grounded by "
        f"{', '.join(p.value for p in result.provenance) or 'nothing'}"
    )
    # Always, not only on failure. A timeout is the case that needs the marks,
    # and a run that printed them only when something went wrong would give no
    # baseline to compare the bad run against.
    print(
        "timing: "
        + (
            ", ".join(f"{name}={value:.2f}s" for name, value in result.timing.items())
            or "nothing recorded"
        )
    )
    return 0 if result.outcome is RunOutcome.PASSED else 1


def _destroy_overlay(hwnd) -> None:
    """Tear down the overlay, never letting teardown mask the real outcome."""
    if not hwnd:
        return
    try:
        win32gui.DestroyWindow(hwnd)
    except Exception:
        pass


def pump_messages() -> None:
    """One non-blocking drain of the UI thread's message queue.

    The overlay is a real window; a window that never pumps stops repainting
    and is reported as hung by the shell.
    """
    try:
        import pythoncom

        pythoncom.PumpWaitingMessages()
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
