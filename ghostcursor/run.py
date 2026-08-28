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


def perception_walker_for(app_id: str, recipe_intent: str = ""):
    """Choose the narrowest trusted perception surface for an app recipe."""
    if app_id.casefold() == "code.exe":
        if recipe_intent.casefold() == "open the integrated terminal in vscode":
            return uia.iter_vscode_terminal_elements
        return uia.iter_vscode_elements
    return uia.iter_elements


def perception_hwnd_source_for(app_id: str):
    """Use executable identity whenever the recipe declares one."""
    if app_id.casefold().endswith(".exe"):
        return lambda title_re: uia.first_matching_hwnd_for_executable(
            title_re, app_id
        )
    return uia.first_matching_hwnd


def tier2_capture_for(app_id: str):
    """Keep pixel perception on the same executable-bounded target HWND."""
    if app_id.casefold().endswith(".exe"):
        from ghostcursor.perception.capture import capture_window

        return lambda title_re: capture_window(title_re, executable_name=app_id)
    return None


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
    """Build the grounder used by a live run_tour: ground, promote, persist.

    Factored out of run_tour so it is directly testable without a live UIA
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


def run_tour(
    recipe_path: str,
    title_re: str,
    seconds: float,
    clock=time.monotonic,
    sleeper=time.sleep,
    warmup_budget_s: float = DEFAULT_WARMUP_BUDGET_S,
    ai_goal: str | None = None,
) -> int:
    """Run a recipe as a guided tour.

    `clock` and `sleeper` exist so a test can drive the timeline by hand
    instead of sleeping through it. They are ONE shared time source: the
    deadline, the health budget and the staleness ladder all read `clock`, and
    `sleeper` is what advances it. Two independently-driftable clocks here
    would be worse than none — the whole point of the staleness ladder is that
    its notion of "now" agrees with the loop's. Everything with a sense of time
    reads it: the deadline, the health budget, the staleness ladder, the
    perception worker's throttle, and `GuidedTour`'s grounding grace and idle
    timeout.
    """
    from ghostcursor.memory.store import ObservationStore
    from ghostcursor.perception.appinfo import app_info_for_window
    from ghostcursor.perception import tier2
    from ghostcursor.perception.health import WorkerHealth
    from ghostcursor.perception.service import PerceptionService
    from ghostcursor.reasoning.loop import (
        DEFAULT_GROUNDING_GRACE_S,
        GuidedTour,
        State,
    )
    from ghostcursor.reasoning.renderer import OverlayRenderer
    from ghostcursor.reasoning.schema import Recipe
    from ghostcursor.reasoning.grounding import GroundedTarget
    from ghostcursor.reasoning.staleness import (
        StalenessLadder,
    )
    from ghostcursor.reasoning.verification import Snapshot, verify

    recipe = Recipe.load(recipe_path)

    # app_info_for_window can shell out to PowerShell (Store-app version
    # lookup, up to 25s) and ObservationStore() can raise (corrupt/
    # read-only db, %LOCALAPPDATA% undefined). Both now run before the
    # overlay is created — there is no full-screen, click-through, unfocused
    # window on screen during this slow pre-tour phase, so there is nothing
    # to escape from yet. The overlay's own escape hatch only has to cover
    # the tour loop below, which is what it was designed for.
    if escape_pressed():
        print("ESC pressed — exiting.")
        return 0

    expected_app_id = recipe.app_id if recipe.app_id.casefold().endswith(".exe") else None
    app_info = (
        app_info_for_window(title_re, expected_app_id=expected_app_id)
        if expected_app_id is not None
        else app_info_for_window(title_re)
    )

    if expected_app_id is not None and app_info is None:
        print(
            f"Stopped: no trusted {expected_app_id!r} window matched "
            f"the target {title_re!r}"
        )
        return 1

    if escape_pressed():
        print("ESC pressed — exiting.")
        return 0

    store = None
    service = None
    try:
        if app_info is not None:
            store = ObservationStore()
            loaded = hydrate_recipe(recipe, app_info.app_id, store)
            print(f"Loaded {loaded} learned observation(s) from previous runs.")
        else:
            print(
                "No application identity for this window — persistence disabled "
                "for this run."
            )

        if escape_pressed():
            print("ESC pressed — exiting.")
            return 0

        # Perception moves off the UI thread here, before the overlay exists.
        # A "Not Responding" target blocks a single UIA walk for ~40s, and ESC
        # is polled BETWEEN ticks — so a walk on this thread is 40s in which
        # the user cannot dismiss a window covering their whole screen. The
        # worker absorbs that block; the UI thread only ever reads a slot.
        # Same clock as everything else with a sense of time. Tier 2's
        # min-interval floor and the loop's ticks must agree on "now", or the
        # floor throttles against a clock the tour is not running on.
        tier2_controller = tier2.build_controller(clock)
        if tier2_controller is None:
            print("Ghost Cursor: OCR unavailable on this machine — UIA only.")
        else:
            bounded_capture = tier2_capture_for(recipe.app_id)
            if bounded_capture is not None:
                tier2_controller.capture = bounded_capture
        # The controller is HANDED OVER here and never touched again from this
        # thread. Capture + OCR measured 0.14-0.23s on a 976x1028 window and
        # scales with captured area; on the tick path that is D020's 0.5s
        # ceiling gone and the D021 freeze back. The UI thread keeps the
        # DECIDING half (only it knows the current step and whether grounding
        # just failed) and asks through a request slot; the worker executes.
        target_hwnd_source = perception_hwnd_source_for(recipe.app_id)
        service = PerceptionService(
            title_re,
            walker=perception_walker_for(recipe.app_id, recipe.intent),
            hwnd_source=target_hwnd_source,
            clock=clock,
            tier2=tier2_controller,
        )
        #: Patience before escalating to tier 2 on a freshly-seen window. Same
        #: clock as the deadline, the health budget and the staleness ladder;
        #: two independently-driftable clocks here is the D026 failure
        #: exactly.
        warmup = WarmUp(budget_s=warmup_budget_s, clock=clock)
        ladder = StalenessLadder(clock=clock)
        health = WorkerHealth(service=service, ladder=ladder)
        service.start()

        hwnd = window.create_overlay_window()
        bar_hwnd = None
        try:
            bar_hwnd = bar.create_bar_window()
        except Exception as exc:
            # The safety bar is additive.  A registration/display failure must
            # never remove the keyboard ESC escape hatch.
            print(f"Control bar unavailable: {exc}")
        print(f"Guided tour: {recipe.intent!r}. ESC to quit.")
        try:
            deadline = clock() + seconds
            tour_started = clock()
            last_printed: str | None = None
            live_grounder = make_grounder(
                title_re,
                app_info=app_info,
                store=store,
                recipe_intent=recipe.intent,
            )
            ai_hint_decision = None
            #: observed_at of the newest observation the ladder has been told
            #: about. The ladder measures time since the last CONFIRMED-FRESH
            #: walk, so it must only be advanced by a genuinely NEW one —
            #: re-reading the same slot every tick would reset the clock
            #: forever and a hung target would never dim, never hide, and
            #: never trip the health check.
            last_fed_to_ladder = 0.0
            #: The observation THIS tick is reasoning about — the one
            #: OBSERVING took its snapshot from. DECIDING reads it instead of
            #: re-reading the slot, so the UIA half and the OCR half always
            #: come from the same instant (D019). Re-reading gave grounding
            #: observation B's `ocr_elements` alongside observation A's UIA
            #: elements, merged into one list, which is exactly the
            #: same-instant rule the snapshot exists to keep.
            current_observation = None
            # HWND discovery belongs to the perception worker. Calling the
            # source here duplicated the lookup on the control thread; a
            # single hung desktop window can block Windows' enumeration and
            # freeze ESC/the control rail before the first tick. Keep SPACE
            # disabled until a completed worker observation supplies the
            # trusted HWND identity.
            target_hwnd = 0
            paused = False
            terminal_reported = False
            terminal_service_stopped = False

            def snapshotter():
                nonlocal last_fed_to_ladder, current_observation
                observation = service.latest()
                current_observation = observation
                if observation is None:
                    # No observation yet is a normal starting condition. An
                    # empty untimestamped snapshot reads as FRESH to the loop
                    # (observed_at 0.0), which is right: there is nothing to
                    # call stale yet.
                    return Snapshot(title="", elements=())
                if observation.observed_at > last_fed_to_ladder:
                    last_fed_to_ladder = observation.observed_at
                    ladder.observed()
                return observation.snapshot

            def grounder_from_slot(step, i, elements=None):
                nonlocal ai_hint_decision
                # Grounds against the LAST observation, not a live walk. While
                # observations are merely stale this keeps succeeding, so the
                # loop's grounding grace never starts — the hint stays drawn
                # and simply dims. The grace clock starts only once a new
                # observation arrives that grounding genuinely fails against.
                #
                # Use the elements the LOOP passed in whenever it has them.
                # Those came from the snapshot OBSERVING took, and D019 requires
                # OBSERVING and DECIDING to describe the same instant. Re-reading
                # the slot here would ground observation B while verification
                # baselines on observation A, so the hint could point at a
                # control the baseline never saw. `current_observation` is that
                # same observation, captured by the snapshotter — so the OCR
                # half below comes from the instant these elements do.
                observation = current_observation
                if elements is None:
                    elements = observation.elements if observation else ()

                if ai_goal and i == 0 and ai_hint_decision is None and elements:
                    from ghostcursor.inference.screen_hint import decide_next_hint

                    if bar_hwnd is not None:
                        bar.set_status(bar_hwnd, "AI thinking…")
                    ai_hint_decision = decide_next_hint(
                        ai_goal,
                        list(elements),
                        tuple(
                            name
                            for name in (
                                step.target_descriptor.claimed.name,
                                *step.target_descriptor.claimed.name_synonyms,
                            )
                            if name
                        ),
                    )
                    print(
                        f"AI hint: {ai_hint_decision.source} selected "
                        f"{ai_hint_decision.automation_id!r} — "
                        f"{ai_hint_decision.explanation}"
                    )
                    if bar_hwnd is not None:
                        bar.set_status(bar_hwnd, "AI hint selected")

                target = None
                if ai_hint_decision is not None and ai_hint_decision.automation_id:
                    allowed = {
                        name.casefold()
                        for name in (
                            step.target_descriptor.claimed.name,
                            *step.target_descriptor.claimed.name_synonyms,
                        )
                        if name
                    }
                    selected = next(
                        (
                            element
                            for element in elements
                            if element.automation_id == ai_hint_decision.automation_id
                            and element.source == "uia"
                            and element.name.casefold() in allowed
                        ),
                        None,
                    )
                    if selected is not None:
                        # The model's bounded selection is the hint. It is
                        # already validated against the live UI and the
                        # recipe-approved names, so stale KB rows cannot
                        # override it.
                        target = GroundedTarget(
                            bbox=selected.bbox,
                            rung=2,
                            automation_id=selected.automation_id,
                            control_type=selected.control_type,
                            name=selected.name,
                            source=selected.source,
                        )
                if target is None:
                    target = live_grounder(step, i, elements)
                if target is not None:
                    # UIA answered, so tier 2 is not wanted for this step. A
                    # standing request costs capture + OCR on the worker as
                    # often as the 1.0s floor allows, delaying the UIA
                    # observations this step is actually being grounded from.
                    service.cancel_tier2(i)
                    warmup.note_grounded(
                        observation.target_hwnd if observation is not None else 0
                    )
                    return target

                # Tier 2. Triggered by GROUNDING FAILURE for this step, never
                # by an empty walk: Chrome returned 43 elements containing zero
                # page content, so "UIA returned nothing" would never fire.
                #
                # The trigger is all that happens here. Setting the request is
                # a lock-and-assign; the READING happens on the perception
                # worker and its result turns up in a later observation. There
                # is deliberately no wait, join or future: this thread is the
                # one polling ESC. Grounding may therefore fail for a tick or
                # two before OCR elements arrive, which the 10s grounding grace
                # and the staleness ladder already cover.
                # Warm-up. A cold Chromium tree is populating, not blind: VS
                # Code grounded its targets 0.57s after the window appeared and
                # Discord 0.92s. Escalating inside that window burns OCR reads
                # and risks drawing an amber INFERRED ring when a cyan one off a
                # confirmed control was half a second away. Keyed by HANDLE, not
                # title -- Discord's 'Discord Updater' splash matches the same
                # regex and is a different window.

                target_hwnd = observation.target_hwnd if observation is not None else 0
                if not warmup.allows_tier2(target_hwnd):
                    # A standing request from a previous window (or from the
                    # ticks before this one existed) is a standing COST on the
                    # worker; nothing but this ends it, and warm-up means we do
                    # not want it. Same argument as the UIA-success path above.
                    service.cancel_tier2(i)
                    return None
                service.request_tier2(i)
                ocr_elements = (
                    observation.ocr_elements
                    if observation is not None and observation.tier2_step == i
                    else ()
                )
                if not ocr_elements:
                    return None
                target = live_grounder(step, i, list(elements) + list(ocr_elements))
                if target is not None:
                    # A read that produced a usable target is not a fruitless
                    # one, so it does not spend the step's budget (D028). A
                    # churning page can re-ground the same OCR target for
                    # minutes; the budget is there to stop UNPRODUCTIVE
                    # re-reads, and counting productive ones killed a tour
                    # whose amber ring was sitting correctly on the target.
                    # The budget lives with the reader now, so this says so
                    # through the same slot instead of calling the controller.
                    service.report_tier2_grounded(i)
                return target

            def current_display_freshness():
                #: The AGE half of the tick's display state. The SOURCE half is
                #: no longer supplied here on purpose: it belongs to the hint
                #: (see renderer._Hint). Tracked beside the renderer, as a
                #: variable DECIDING could advance while the previous step's
                #: ring was still on screen, it laundered an OCR centre into
                #: the confirmed-control colour for one full tick.
                #:
                #: `ladder.freshness()` MUTATES the ladder's recovery state, so
                #: exactly one call per tick is the right number; the renderer
                #: caches it for the tick.
                return ladder.freshness()

            def verifier(rule, before, after):
                if recipe.app_id == "code.exe" and rule.args.get("vscode_workspace_title"):
                    from ghostcursor.reasoning.vscode import verify_open_folder

                    return verify_open_folder(before, after, ai_goal or "")
                return verify(rule, before, after)

            def read_failure_reason(step, index):
                """Why this step is ungroundable, when tier 2 knows better.

                Called only once the grounding grace has expired, and only
                the loop's generic "cannot find X on screen" is replaced.
                Whether the run cap or the grace ran out first is deliberately
                NOT what decides the wording: with a 10s grace and a 1.0s
                floor between reads, a screen nobody can read reaches the
                grace after ~10 reads and never gets near the 20-run cap, so a
                message keyed on exhaustion described the opposite case from
                the one it was written for — it appeared only when reading
                intermittently WORKED. What decides it is whether tier 2 was
                engaged for this step at all: if we ran OCR and still could
                not locate the target, the honest report is that we could not
                read the screen (D024, D028). Saying "cannot find" there
                points the user at their own application instead of at ours.
                """
                # Read from the published observation, never from the
                # controller: the controller's per-step state is now worker-
                # owned mutable state, and the UI thread reaching into it
                # across a thread boundary is the sort of racy read this
                # design exists to avoid. `tier2_step` is checked first — the
                # flags describe ONE step, and trusting them for another would
                # report the previous step's exhaustion as this step's.
                observation = service.latest()
                if observation is None or observation.tier2_step != index:
                    return None
                name = step.target_descriptor.claimed.name or "the requested application state"
                if observation.tier2_exhausted:
                    return (
                        f"could not read {name!r} on screen after "
                        f"{observation.tier2_max_runs} attempts"
                    )
                if observation.tier2_engaged:
                    return f"could not read {name!r} on screen"
                return None

            def focus_visited_source():
                # Read from `current_observation`, never re-read the slot
                # (D019): every other consumer in this file does the same --
                # see the reasoning at grounder_from_slot's docstring above
                # and the tier2 status reader below. `snapshotter()` runs
                # before `_wrong_action` in the tick, so `current_observation`
                # is always the observation this tick's `after` came from; a
                # fresh `service.latest()` call here could instead return
                # observation N+1, attributing `touched` to a later walk than
                # the one verification actually ran against.
                return (
                    current_observation.focus_visited
                    if current_observation is not None
                    else ()
                )

            def on_wrong_action(touched: str, target: str) -> None:
                # The console is the RECORD; the ring is the correction. The
                # user is looking at their application, not at this terminal,
                # so the ring re-asserting through OBSERVING is what they
                # actually see -- this line is what explains it afterwards.
                print(
                    f"  that was {touched!r}, not {target!r} — "
                    "re-showing the hint on the right control"
                )

            tour = GuidedTour(
                recipe=recipe,
                grounder=grounder_from_slot,
                snapshotter=snapshotter,
                verifier=verifier,
                renderer=OverlayRenderer(
                    hwnd, freshness_source=current_display_freshness
                ),
                focus_visited_source=focus_visited_source,
                on_wrong_action=on_wrong_action,
                # Stock grace. The two clocks used to race — a dead worker made
                # grounding fail every tick, so the grace expired before the
                # health budget and the tour said "cannot find 'Export' on
                # screen" about an element sitting right there, pointing the
                # user at their own application instead of at ours. Inflating
                # the grace to outrun health was the first fix and was wrong
                # twice over: health's worst case is TWO budgets (suppressed
                # until dead_after_s from tour start, then the restart grants
                # the replacement another), so one budget still lost the race;
                # and inflating it made a genuinely missing element take 40s to
                # report. The race is now removed at its source instead — see
                # the `service.latest() is None` guard in the tick loop below.
                grounding_grace_s=DEFAULT_GROUNDING_GRACE_S,
                # Same clock as the ladder and the loop. GuidedTour owns the
                # 10s grounding grace and the 30s idle timeout; left on its
                # own default those run on real time while everything else
                # runs on the injected one, so a timeline test could never
                # exercise the grace-vs-health interaction at all.
                clock=clock,
                ungroundable_reason=read_failure_reason,
            )
            #: The step the standing tier-2 request (if any) belongs to. The
            #: worker cannot notice a step boundary — only this thread knows
            #: which step is current — and nothing else ends a request, so a
            #: step that asked for OCR and was then LEFT would keep the worker
            #: reading the screen for it through every later step, whether or
            #: not those steps ever call the grounder (AWAITING_USER_ACTION
            #: dwells for many ticks without one).
            tier2_step_on_screen = tour.step_index
            while clock() < deadline:
                if escape_pressed():
                    if bar_hwnd is not None and bar.panel_is_open(bar_hwnd):
                        bar.close_panel(bar_hwnd)
                        bar.set_status(bar_hwnd, "Ask cancelled")
                        continue
                    print("ESC pressed — exiting.")
                    break

                # Refresh focus arbitration from the worker's published slot,
                # never by walking/enumerating windows on this thread. A zero
                # handle is deliberately retained as zero: confirmation must
                # fail closed while the target cannot be identified.
                focus_observation = service.latest()
                if focus_observation is not None:
                    target_hwnd = focus_observation.target_hwnd

                if bar_hwnd is not None:
                    requests = bar.bar_state(bar_hwnd)
                    bar.clear_requests(bar_hwnd)
                    if requests.stop_requested:
                        print("Stop requested — exiting.")
                        break
                    if requests.pause_requested:
                        paused = not paused
                        bar.set_status(bar_hwnd, "Paused" if paused else "Running")
                    if requests.ask_requested:
                        if getattr(tour, "state", State.DONE) in (State.IDLE, State.DONE, State.FAILED):
                            bar.open_panel(bar_hwnd)
                        else:
                            bar.set_status(bar_hwnd, "Finish or stop the active tour before asking")
                    submitted = bar.take_submitted_goal(bar_hwnd)
                    if submitted is not None:
                        # Ask uses the same planner as --goal, but an active
                        # tour is never replaced behind the user's back.
                        from ghostcursor.reasoning.planner import plan_compiled_goal

                        asked = plan_compiled_goal(submitted, target_title_re=title_re)
                        # A supported nested tour deliberately keeps its own
                        # control bar alive after completion. Announce the Ask
                        # result before entering that blocking session so the
                        # console proves the handoff immediately instead of
                        # only when the session timeout eventually returns.
                        print(f"Ask received: {submitted!r} — {asked.status.value}")
                        if asked.plan is not None and asked.intent_id is not None:
                            # A terminal tour is an idle host for Ask. Tear
                            # down this bar before launching the nested tour
                            # so the user never sees two interactive bars.
                            bar.set_status(bar_hwnd, f"Starting {asked.intent_id}…")
                            bar.restore_focus_if_safe(bar_hwnd, target_hwnd)
                            old_bar = bar_hwnd
                            bar_hwnd = None
                            bar.destroy_bar_window(old_bar)
                            run_tour_for_workflow(
                                asked.plan,
                                seconds=max(1.0, deadline - clock()),
                                clock=clock,
                                sleeper=sleeper,
                                warmup_budget_s=warmup_budget_s,
                            )
                            bar_hwnd = bar.create_bar_window()
                            bar.set_status(bar_hwnd, "Ready")
                        else:
                            bar.set_status(bar_hwnd, f"Ask: {asked.status.value}")
                            bar.restore_focus_if_safe(bar_hwnd, target_hwnd)
                if paused:
                    window.pump_messages_nonblocking()
                    sleeper(REFRESH_SECONDS)
                    continue

                # A terminal tour no longer needs perception. Keep pumping
                # messages so the bar remains available for Ask, but do not
                # let a stale worker trigger a health restart after success.
                if getattr(tour, "state", None) in (State.DONE, State.FAILED):
                    if not terminal_service_stopped:
                        service.stop()
                        terminal_service_stopped = True
                    window.pump_messages_nonblocking()
                    sleeper(REFRESH_SECONDS)
                    continue

                if tour.step_index != tier2_step_on_screen:
                    # The tour left the step that asked. Cancel unconditionally
                    # — whatever is standing belongs to a step nobody is on.
                    service.cancel_tier2()
                    tier2_step_on_screen = tour.step_index
                if (
                    should_poll_space(tour.current_step)
                    and confirmation_focus_is_safe(target_hwnd, bar_hwnd)
                    and key_was_pressed(win32con.VK_SPACE)
                ):
                    tour.confirm()

                # WorkerHealth's stall signal is ladder.age(), which is
                # infinite until the first observation lands. Checking it
                # unguarded would restart the worker on tick 1 and end the tour
                # on tick 2, before perception had answered even once. Suppress
                # it only until the same dead_after_s budget has elapsed from
                # tour start — a worker that never produces anything at all is
                # still caught, just from a start time that exists.
                started_reporting = (
                    ladder.age() != float("inf")
                    or clock() - tour_started > health.dead_after_s
                )
                if started_reporting:
                    reason = health.check()
                    if reason is not None:
                        print(f"Stopped: {reason}")
                        break

                # Spec §9: "no observation yet at tour start -> the loop stays
                # in OBSERVING rather than treating it as a failure." Ticking
                # before the first observation lands would let the empty
                # placeholder snapshot become a VERIFICATION BASELINE: the loop
                # advances to DECIDING, grounding can succeed off an observation
                # that arrived between the two ticks, and then verify compares
                # against an empty `before` — where ANY_MEANINGFUL_CHANGE is
                # unconditionally true and ELEMENT_APPEARS matches anything
                # already on screen. The tour would mark a step complete that
                # the user never performed, which is the one thing D006 exists
                # to prevent.
                #
                # This is also what keeps the two clocks from racing. Grounding
                # is now only ever attempted once a real observation exists, so
                # a grounding failure means perception IS working and the
                # element genuinely is not there — which is exactly when
                # "cannot find X on screen" is the correct thing to say. A dead
                # worker leaves its last observation in the slot, so grounding
                # keeps succeeding against it and the grace never starts at all;
                # the health check is left to name the failure. The grace can
                # therefore stay at its stock 10s rather than being inflated to
                # outrun the health budget, which would have made a genuinely
                # missing element take 40s to report.
                if service.latest() is None:
                    window.pump_messages_nonblocking()
                    sleeper(REFRESH_SECONDS)
                    continue

                # No exhaustion check here, on purpose. There used to be one,
                # and it ended the tour the instant tier 2 spent its budget.
                # Spec §4 says the opposite: an exhausted step is TREATED AS
                # UNGROUNDABLE, feeding the existing grounding grace, so the
                # last observation keeps ageing normally through the staleness
                # ladder — it dims, then hides — and the user gets those
                # seconds to act instead of the tour dying under a ring that
                # is still correct. `elements_for` already returns nothing once
                # the budget is spent, so grounding fails on its own and the
                # grace does the rest; `read_failure_reason` above is what
                # makes the grace name the read failure.
                state = tour.tick()
                if state is State.DONE:
                    if not terminal_reported:
                        print("Tour complete.")
                        terminal_reported = True
                    if bar_hwnd is None:
                        break
                    bar.set_status(bar_hwnd, "Done — Ask is available")
                    window.pump_messages_nonblocking()
                    sleeper(REFRESH_SECONDS)
                    continue
                if state is State.FAILED:
                    if not terminal_reported:
                        print(f"Stopped: {tour.failure_reason}")
                        terminal_reported = True
                    if bar_hwnd is None:
                        break
                    bar.set_status(bar_hwnd, "Failed — Ask is available")
                    window.pump_messages_nonblocking()
                    sleeper(REFRESH_SECONDS)
                    continue

                # No drawing happens here, on purpose. `tour.tick()` closes its
                # own tick by calling `renderer.settle()`, which is the single
                # write path (D027): if the loop already drew, settle is a
                # no-op; otherwise it is where a STALENESS-ONLY transition
                # reaches the screen.
                #
                # There used to be a corrective `window.set_hint` at this point,
                # run after the renderer had already painted. It is deleted, not
                # reordered: two writes per tick, each ending in a synchronous
                # UpdateWindow, meant the provisional frame really was
                # displayed. Do not reintroduce drawing into this loop.

                # Only print when the instruction changes — this loop runs
                # at 4 ticks/sec and the instruction is unchanged across
                # most of them (AWAITING_USER_ACTION dwells while polling).
                instruction = tour.renderer.last_instruction
                if instruction and instruction != last_printed:
                    print(f"  step {tour.step_index + 1}: {instruction}")
                    last_printed = instruction

                window.pump_messages_nonblocking()
                sleeper(REFRESH_SECONDS)
            else:
                if terminal_reported:
                    print("Control-bar session time limit reached — exiting.")
                else:
                    print("Time limit reached — exiting.")
        finally:
            window.destroy_overlay_window(hwnd)
            if bar_hwnd is not None:
                bar.destroy_bar_window(bar_hwnd)
    finally:
        if service is not None:
            service.stop()
        if store is not None:
            store.close()
    return 0


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
