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
import time
from typing import Callable

import win32api
import win32con

# Import order matters: overlay.window pulls in overlay.dpi, which declares
# DPI awareness before any window exists (see ghostcursor/overlay/dpi.py).
from ghostcursor.overlay import window
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


def run_tour(
    recipe_path: str,
    title_re: str,
    seconds: float,
    clock=time.monotonic,
    sleeper=time.sleep,
    warmup_budget_s: float = DEFAULT_WARMUP_BUDGET_S,
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

    app_info = app_info_for_window(title_re)

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
        # The controller is HANDED OVER here and never touched again from this
        # thread. Capture + OCR measured 0.14-0.23s on a 976x1028 window and
        # scales with captured area; on the tick path that is D020's 0.5s
        # ceiling gone and the D021 freeze back. The UI thread keeps the
        # DECIDING half (only it knows the current step and whether grounding
        # just failed) and asks through a request slot; the worker executes.
        service = PerceptionService(title_re, clock=clock, tier2=tier2_controller)
        #: Patience before escalating to tier 2 on a freshly-seen window. Same
        #: clock as the deadline, the health budget and the staleness ladder;
        #: two independently-driftable clocks here is the D026 failure
        #: exactly.
        warmup = WarmUp(budget_s=warmup_budget_s, clock=clock)
        ladder = StalenessLadder(clock=clock)
        health = WorkerHealth(service=service, ladder=ladder)
        service.start()

        hwnd = window.create_overlay_window()
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
                name = step.target_descriptor.claimed.name
                if observation.tier2_exhausted:
                    return (
                        f"could not read {name!r} on screen after "
                        f"{observation.tier2_max_runs} attempts"
                    )
                if observation.tier2_engaged:
                    return f"could not read {name!r} on screen"
                return None

            tour = GuidedTour(
                recipe=recipe,
                grounder=grounder_from_slot,
                snapshotter=snapshotter,
                verifier=verify,
                renderer=OverlayRenderer(
                    hwnd, freshness_source=current_display_freshness
                ),
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
                    print("ESC pressed — exiting.")
                    break

                if tour.step_index != tier2_step_on_screen:
                    # The tour left the step that asked. Cancel unconditionally
                    # — whatever is standing belongs to a step nobody is on.
                    service.cancel_tier2()
                    tier2_step_on_screen = tour.step_index
                if should_poll_space(tour.current_step) and key_was_pressed(
                    win32con.VK_SPACE
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
                    print("Tour complete.")
                    break
                if state is State.FAILED:
                    print(f"Stopped: {tour.failure_reason}")
                    break

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
                print("Time limit reached — exiting.")
        finally:
            window.destroy_overlay_window(hwnd)
    finally:
        if service is not None:
            service.stop()
        if store is not None:
            store.close()
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
