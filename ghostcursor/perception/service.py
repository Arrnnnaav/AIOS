"""Perception on a worker thread, published into a single slot.

The UI thread owns the overlay window and must never block: ESC is polled
between ticks, so any blocking call there is time the user cannot dismiss a
window covering their screen. A UIA walk against an application that has
stopped pumping messages blocks for ~40s on first contact and ~10s after,
with no timeout available to tune — so the walk cannot happen on the UI
thread at all. A watchdog cannot rescue it either: DestroyWindow from a
non-owning thread is denied, and PostMessage needs the very message pump the
blocked tick is not running.

A single slot, not a queue: a queue drained to "newest, discard the rest" is
a depth-1 buffer with extra ceremony — no depth to tune, no explicit discard
step. Overwrite IS the discard. The slot holds one observation and no
history.

No futures. A future answers "which request does this answer belong to"; the
timestamp on the published observation answers the same question here, and
the staleness ladder needs that timestamp anyway. Futures would also force
async control flow into GuidedTour and change every injected fake, when the
collaborator contract must keep its current shape.

COM: the worker calls CoInitializeEx and owns its own UIA access. UIA objects
are apartment-bound, so only frozen dataclasses of primitives ever cross the
thread boundary — Element, Snapshot, Observation. No COM object does.

"Confirmed-fresh" means the walk completed without raising, regardless of how
many elements it found: a window that genuinely contains nothing matchable is
a SUCCESSFUL observation. Treating empty as failure would make a legitimately
empty target look permanently frozen.
"""

from __future__ import annotations

import threading
import time
import os
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping

from ghostcursor.perception.focus import read_focused_automation_id
from ghostcursor.perception.uia import Element, first_matching_hwnd, iter_elements
from ghostcursor.reasoning.verification import Snapshot, take_snapshot

DEFAULT_INTERVAL_S = 0.2
#: How often focus is sampled during the inter-walk wait. Focus reads cost a
#: 2.66ms median, so this is cheap; it is 50ms because the case worth catching
#: is a wrong click the user corrects themselves, which happens far slower
#: than that. See the design spec, section 2.3.
DEFAULT_FOCUS_SLICE_S = 0.05
#: Ceiling on ids carried per observation, so a control that cycles focus
#: cannot grow the published payload without bound. At the DEFAULTs this is a
#: backstop, not the primary bound: interval_s / focus_slice_s = 0.2 / 0.05 =
#: 4 samples per wait, plus the one walk-start sample, is already well under
#: this cap. It starts doing real work only if either constant is retuned
#: toward a much longer interval or a much finer slice. When it fires, the
#: ids that survive are the EARLIEST distinct ones seen this interval: the
#: append guard in `_record_focus` (called from both `_sample_focus_while_waiting`
#: and the walk-start sample in `_run`) checks `len(visited) < MAX_FOCUS_VISITED`
#: before appending, so once the cap is hit later distinct ids are silently
#: dropped rather than evicting an earlier one. Documented, not changed:
#: recency vs. earliest-seen is a real tradeoff and this task does not decide it.
MAX_FOCUS_VISITED = 8


@dataclass(frozen=True)
class Tier2Request:
    """The UI thread's ask, crossing the boundary the other way.

    Tier 2's TRIGGER is inherently a UI-thread concept -- only the loop knows
    which step is current and whether grounding just failed -- while its COST
    (capture + OCR, 0.14-0.23s measured on a 976x1028 window, scaling with
    captured area) belongs anywhere but the tick. So the UI thread decides and
    the worker executes, through one overwritten slot, exactly as results
    travel the other way (D022).

    Primitives only (D021): no controller, no COM object, nothing live.
    `grounded` is the UI thread reporting that the LAST read produced a usable
    target, which resets the controller's fruitless-run budget; the worker
    takes it and clears it.

    There is no `wanted` flag: the ABSENCE of a request is "not wanted".
    A flag would have to be set to False by exactly the callers that can
    instead clear the slot, and a False request still carries a step index and
    a stale `grounded` that nothing would ever clear.
    """

    step_index: int
    grounded: bool = False


@dataclass(frozen=True)
class Observation:
    """One completed look at the target. Crosses the thread boundary, so
    every field is a primitive or a frozen dataclass of primitives."""

    snapshot: Snapshot
    elements: tuple[Element, ...]
    observed_at: float
    ok: bool
    #: What tier 2 read, if it was asked to read at all this iteration.
    #: Empty when tier 2 was not wanted, is unavailable on this machine, or
    #: found nothing.
    ocr_elements: tuple[Element, ...] = ()
    #: The step `ocr_elements` and the two flags below describe. -1 when tier
    #: 2 did not run: a consumer must check this before trusting them, or it
    #: would read one step's exhaustion as another's.
    tier2_step: int = -1
    #: Worker-owned tier-2 state, published rather than reached into. The UI
    #: thread needs `exhausted` to name a READ failure instead of the generic
    #: "cannot find" (D024, D028), and `engaged` to know tier 2 ran at all.
    tier2_engaged: bool = False
    tier2_exhausted: bool = False
    #: The controller's per-step run cap, echoed so the failure message can
    #: quote it without the UI thread holding the controller.
    tier2_max_runs: int = 0
    #: The topmost window matching `title_re` when this observation was taken,
    #: or 0 if none was found. NOT guaranteed to be the window the walk itself
    #: enumerated: `hwnd_source` and `walker` are resolved independently, and
    #: while both are gated by the same `windows_matching`, `iter_elements`
    #: hands its final selection to pywinauto. With several matching windows
    #: the two can name different ones -- bounded, because a sibling handle
    #: among the matches still gets its own warm-up patience. See
    #: `uia.first_matching_hwnd`.
    #: A plain int by design -- only primitives cross the worker boundary
    #: (D021). Warm-up is keyed on it because a title regex cannot distinguish
    #: Discord's 'Discord Updater' splash from Discord itself, and those are
    #: different HWNDs.
    target_hwnd: int = 0
    #: Distinct in-process AutomationIds that focus MOVED TO since the
    #: previous observation -- not where focus rests now, and not merely
    #: where it was found to be at any one sample. An id already holding
    #: focus at the interval boundary is deliberately excluded: only a
    #: TRANSITION away from the previously-held id is reported, so a control
    #: focus never left is never re-reported on every observation while it
    #: holds focus (see `PerceptionService._record_focus`). The case this
    #: exists for is a wrong click the user corrects before the next walk
    #: completes. Plain strings, because only primitives cross the worker
    #: boundary (D021). Empty ids are never recorded: "" means focus is
    #: somewhere we cannot name, and naming is the point.
    focus_visited: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkerProgress:
    """Primitive lifecycle data published for health diagnosis.

    This is deliberately separate from :class:`Observation`: a worker can be
    alive and completing failed walks without producing a fresh observation.
    Health must distinguish that case from a thread blocked inside one UIA
    call.
    """

    generation: int
    heartbeat: int
    stage: str
    iteration_started_at: float | None
    last_completed_at: float | None
    last_published_at: float | None
    last_error: str | None


class PerceptionService:
    def __init__(
        self,
        title_re: str,
        walker: Callable[[str], list[Element]] = iter_elements,
        hwnd_source: Callable[[str], int] = first_matching_hwnd,
        clock: Callable[[], float] = time.monotonic,
        interval_s: float = DEFAULT_INTERVAL_S,
        tier2=None,
        focus_reader: Callable[[int], str] = read_focused_automation_id,
        focus_slice_s: float = DEFAULT_FOCUS_SLICE_S,
        plan_runner: Callable[[int], tuple] | None = None,
    ) -> None:
        self.title_re = title_re
        self.walker = walker
        #: A compiled observation plan, run ON THIS WORKER in place of the
        #: walker. It returns `(selector_results, elements)` for one target
        #: HWND. Optional because the v1 walkers are still what production
        #: uses; when it is set, the compiled path gets everything the worker
        #: already provides -- the published slot, tier 2, focus sampling,
        #: worker-death detection -- instead of walking UIA on the UI thread,
        #: which is the 41-second freeze D021 exists to prevent.
        self.plan_runner = plan_runner
        self.hwnd_source = hwnd_source
        self.focus_reader = focus_reader
        self.focus_slice_s = focus_slice_s
        #: The tier-2 controller, owned entirely by this side of the boundary
        #: from here on. It is built on the UI thread (it has to report "no
        #: OCR on this machine" before the overlay exists) and then handed
        #: over; nothing on the UI thread may call it again. None means OCR is
        #: unavailable, which is a supported configuration -- the tour runs on
        #: UIA alone.
        self.tier2 = tier2
        self.clock = clock
        #: Throttle. Perception costs ~26ms against a 250ms tick, so an
        #: unthrottled loop would spin ~10x faster than anything consumes.
        self.interval_s = interval_s

        #: Diagnostic ONLY. Advances every loop iteration whether or not the
        #: observation succeeded, so that after the fact "blocked inside a
        #: slow UIA call" (heartbeat frozen) stays distinguishable from
        #: "alive but looping through silent failures" (heartbeat climbing,
        #: slot ageing). It is logged when a restart-or-give-up policy fires
        #: and is never an input to that policy — nothing here or in any
        #: caller may branch on its value.
        self.heartbeat = 0
        self.restarts = 0
        self._generation = 0
        self._progress_lock = threading.Lock()
        self._stage = "stopped"
        self._iteration_started_at: float | None = None
        self._last_completed_at: float | None = None
        self._last_published_at: float | None = None
        self._last_error: str | None = None
        self._slot: Observation | None = None
        #: The request slot: one overwritten value, same shape as the result
        #: slot. Setting it never blocks and never waits for OCR -- the answer
        #: turns up in a LATER observation, and grounding failing for a tick
        #: or two meanwhile is already handled by the grounding grace and the
        #: staleness ladder.
        self._tier2_request: Tier2Request | None = None
        self._lock = threading.Lock()
        #: Each worker generation gets its OWN stop Event, never a shared one
        #: that start() clears. A worker blocked in a 41s UIA walk cannot be
        #: joined, so restart() necessarily leaves it running; with a shared
        #: Event, start() clearing it for the replacement would ALSO un-stop
        #: the orphan, which then resumes looping when its walk finally
        #: returns. Two workers would publish into one slot: observed_at
        #: could go backwards (freshness oscillating for no reason the user
        #: could explain), heartbeat increments would be lost, and a sick app
        #: would take double the COM load. Set before start() so a
        #: never-started service reads as stopped.
        self._stop = threading.Event()
        self._stop.set()
        self._thread: threading.Thread | None = None
        self._cached_hwnd = 0
        # Focus is useful for wrong-action feedback but must never be able to
        # stall the primary UIA walk. Some native controls can block a COM
        # GetFocusedElement call; keep the real reader on its own daemon.
        self._focus_lock = threading.Lock()
        self._focus_request = 0
        self._focus_cache: dict[int, str] = {}
        self._focus_stop = threading.Event()
        self._focus_thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self.is_alive():
            return  # a second worker would fight the first for the slot
        stop = threading.Event()
        self._stop = stop
        self._generation += 1
        generation = self._generation
        with self._progress_lock:
            self._stage = "starting"
            self._iteration_started_at = None
            self._last_completed_at = self.clock()
            self._last_error = None
        self._thread = threading.Thread(
            target=self._run,
            args=(stop, generation),
            name="ghostcursor-perception",
            daemon=True,
        )
        self._thread.start()
        if self.focus_reader is read_focused_automation_id and (
            self._focus_thread is None or not self._focus_thread.is_alive()
        ):
            self._focus_stop.clear()
            self._focus_thread = threading.Thread(
                target=self._focus_run,
                name="ghostcursor-focus",
                daemon=True,
            )
            self._focus_thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._focus_stop.set()
        with self._progress_lock:
            self._stage = "stopping"
        if self._thread is not None:
            # A worker blocked in UIA cannot be interrupted; it is a daemon
            # thread and will exit with the process. Waiting briefly is
            # enough for the common case.
            self._thread.join(timeout=timeout)

    def restart(self) -> None:
        """Replace a worker that has died — or is wedged in a walk that will
        not return. Callers decide the policy (how many times, when to give
        up); this only performs one.

        The old worker's own stop Event stays set forever, so when its walk
        eventually returns it exits instead of resuming alongside the
        replacement.

        **Never joins.** This runs on the UI thread, and it fires precisely
        when the worker is wedged in a walk that will not return for tens of
        seconds — so any join here always burns its full timeout, with no ESC
        poll and no message pump, under a full-screen click-through overlay.
        That is the exact freeze this whole design exists to prevent (D021).
        The join is unnecessary anyway: the retired worker's Event is already
        set, and it re-checks that Event before publishing, so it can neither
        publish nor resume once its walk returns.
        """
        self._stop.set()
        self.restarts += 1
        self._thread = None  # a still-blocked worker must not block start()
        self.start()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def progress(self) -> WorkerProgress:
        """Return a non-COM snapshot of the current worker lifecycle."""
        with self._progress_lock:
            return WorkerProgress(
                generation=self._generation,
                heartbeat=self.heartbeat,
                stage=self._stage,
                iteration_started_at=self._iteration_started_at,
                last_completed_at=self._last_completed_at,
                last_published_at=self._last_published_at,
                last_error=self._last_error,
            )

    def _progress(
        self,
        generation: int,
        *,
        stage: str | None = None,
        iteration_started: float | None = None,
        completed: float | None = None,
        published: float | None = None,
        error: str | None = None,
    ) -> None:
        """Update diagnostics only if this is still the active generation."""
        with self._progress_lock:
            if generation != self._generation:
                return
            if stage is not None:
                self._stage = stage
            if iteration_started is not None:
                self._iteration_started_at = iteration_started
            if completed is not None:
                self._last_completed_at = completed
                self._iteration_started_at = None
            if published is not None:
                self._last_published_at = published
            if error is not None:
                self._last_error = error

    # -- the slot ----------------------------------------------------------
    def latest(self) -> Observation | None:
        """The most recent observation, or None if there is not one yet.

        None at tour start is a normal starting condition, not a failure.
        Never blocks: the lock is held only for a reference read, never
        across a UIA call.
        """
        with self._lock:
            return self._slot

    def request_tier2(self, step_index: int) -> None:
        """Ask the worker to read the screen for `step_index`. Never blocks.

        Overwrite, not enqueue: a second request for the same step while the
        first is still being read IS the same request. The `grounded` flag is
        carried across only within one step -- a new step starts with a clean
        one, which is where tier 2's stickiness resets (D028).
        """
        with self._lock:
            previous = self._tier2_request
            carried = (
                previous is not None
                and previous.step_index == step_index
                and previous.grounded
            )
            self._tier2_request = Tier2Request(step_index=step_index, grounded=carried)

    def cancel_tier2(self, step_index: int | None = None) -> None:
        """Stop reading the screen. Never blocks.

        A standing request is a STANDING COST: capture plus OCR, 0.14-0.23s,
        as often as the 1.0s floor allows. Nothing but this ends it, so the UI
        thread must say when tier 2 stopped being wanted -- when grounding
        succeeded without it, and when the tour left the step that asked. Left
        uncancelled, a request for step 3 keeps being serviced through all of
        step 4, delaying the UIA observations for the step the user is
        actually on and pushing the staleness ladder toward DIMMED; the 20-run
        cap is not a substitute, because a `grounded` report consumed after
        the advance resets even that.

        Pass `step_index` to cancel only if the standing request is for THAT
        step -- so a late cancel from a step already left cannot silently
        discard the current step's request. Pass nothing to cancel whatever is
        there, which is what a step boundary means.
        """
        with self._lock:
            request = self._tier2_request
            if request is None:
                return
            if step_index is not None and request.step_index != step_index:
                return
            self._tier2_request = None

    def report_tier2_grounded(self, step_index: int) -> None:
        """Report that the last OCR read produced a usable target.

        A productive read must not spend the step's fruitless-run budget
        (D028), but that budget lives on the worker side now, so the UI thread
        can only say so through the same slot.
        """
        with self._lock:
            previous = self._tier2_request
            if previous is not None and previous.step_index == step_index:
                self._tier2_request = Tier2Request(step_index=step_index, grounded=True)

    def _take_tier2_request(self) -> "Tier2Request | None":
        """The current request, with `grounded` consumed.

        The request itself persists -- it is a standing state for the step,
        ended only by `cancel_tier2` -- while `grounded` is a one-shot event,
        so leaving it set would reset the budget forever off a single
        successful read.
        """
        with self._lock:
            request = self._tier2_request
            if request is not None and request.grounded:
                self._tier2_request = Tier2Request(
                    step_index=request.step_index, grounded=False
                )
            return request

    def _tier2_payload(self) -> tuple:
        """Run tier 2 if a request is standing, and describe the result.

        Returns the tier-2 fields the observation carries. Failure here never
        costs the UIA observation it travels with: an OCR engine that raises
        degrades to "no OCR elements this time", which grounding already
        treats as a normal outcome.
        """
        empty = ((), -1, False, False, 0)
        request = self._take_tier2_request()
        if self.tier2 is None or request is None:
            return empty
        step = request.step_index
        try:
            if request.grounded:
                self.tier2.grounded(step)
            elements = tuple(self.tier2.elements_for(step, self.title_re))
            return (
                elements,
                step,
                bool(self.tier2.engaged(step)),
                bool(self.tier2.exhausted(step)),
                int(getattr(self.tier2, "max_runs_per_step", 0)),
            )
        except Exception:
            return empty

    def _safe_hwnd(self) -> int:
        """The handle is a nicety; the walk is the product. A failure here
        degrades to 0 rather than discarding an observation that is otherwise
        perfectly good."""
        try:
            if self._cached_hwnd:
                import win32gui

                if win32gui.IsWindow(self._cached_hwnd):
                    return self._cached_hwnd
            self._cached_hwnd = int(self.hwnd_source(self.title_re))
            return self._cached_hwnd
        except Exception:
            self._cached_hwnd = 0
            return 0

    def _safe_focus(self, hwnd: int) -> str:
        """Never let a focus failure cost an observation."""
        if self.focus_reader is read_focused_automation_id:
            # The real COM focus query is asynchronous. Return the most recent
            # answer immediately; an unfinished query cannot block perception.
            with self._focus_lock:
                if hwnd > 0:
                    self._focus_request = hwnd
                return self._focus_cache.get(hwnd, "")
        try:
            return self.focus_reader(hwnd)
        except Exception:
            return ""

    def _focus_run(self) -> None:
        """Sample the real focus reader without coupling it to UIA walks."""
        pythoncom = None
        try:
            import pythoncom

            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        except Exception:
            pass
        try:
            while not self._focus_stop.wait(0.01):
                with self._focus_lock:
                    hwnd = self._focus_request
                    self._focus_request = 0
                if not hwnd:
                    continue
                try:
                    value = self.focus_reader(hwnd)
                except Exception:
                    value = ""
                with self._focus_lock:
                    self._focus_cache[hwnd] = value
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def _record_focus(
        self, focused: str, visited: list[str], last_focus_holder: list
    ) -> None:
        """Append only a TRANSITION, never a resting state.

        `last_focus_holder` is a one-element list, not a plain variable: it is
        shared and mutated across both sampling sites (this walk-start read
        and every slice of `_sample_focus_while_waiting`) and across every
        interval in the worker's lifetime -- it is created once in `_run`,
        outside the per-interval `visited` list, so it survives
        `visited.clear()` at a successful publish. That persistence is the
        whole fix: a control focus never left must never be reported, no
        matter how many observations elapse while it holds focus.

        An empty read is never a transition -- it means "focus is somewhere
        we cannot name" and must not overwrite `last_focus_holder` either, or
        a name we cannot confirm was left could be resurrected as a false
        transition and shows up as a real focus_visited entry when it is not.

        The FIRST non-empty read of the worker's lifetime only seeds
        `last_focus_holder` -- it is never appended -- so the id already
        holding focus when the tour starts is never reported as a "visit".
        """
        if not focused:
            return
        last_focus = last_focus_holder[0]
        if last_focus is None:
            last_focus_holder[0] = focused
            return
        if focused != last_focus:
            if len(visited) < MAX_FOCUS_VISITED:
                visited.append(focused)
            last_focus_holder[0] = focused

    def _sample_focus_while_waiting(
        self,
        stop: threading.Event,
        hwnd: int,
        visited: list[str],
        last_focus_holder: list,
    ) -> None:
        """Wait out `interval_s`, sampling focus in slices as it passes.

        Replaces a single `stop.wait(interval_s)`. Sampling at the WALK's
        cadence would land every 0.4-1.0s, and a user who clicks the wrong
        control and corrects themselves does it in well under a second -- the
        first of the two cases this feature exists for. Slicing the wait
        catches it for 1-3ms a sample.

        `stop` is still honoured promptly, but "within one slice" is not
        exact: a stopping worker leaves after at most one slice's wait PLUS
        one focus read, because `stop.wait` is checked before the read and
        not after it. That read's cost against a non-pumping window is
        unmeasured (design spec section 9) -- unlike the walk, it is not
        covered by a hung-window test. This still cannot freeze the overlay:
        `stop()` joins with a timeout rather than blocking on it, so the UI
        thread never waits on this worker either way (D021).
        """
        remaining = self.interval_s
        while remaining > 1e-9 and not stop.is_set():
            # Floor guards focus_slice_s <= 0: zero would make every
            # iteration's wait a no-op stop.wait(0), spinning the loop into
            # back-to-back focus reads with no pacing; a negative value is floored to
            # that same 1ms, so it samples very fast rather than making
            # `remaining` grow -- the floor, not the sign, is what bounds it. min(..., remaining) still
            # wins over the floor near the end of the interval, so the last
            # slice does not overshoot.
            slice_s = max(min(self.focus_slice_s, remaining), 1e-3)
            if stop.wait(slice_s):
                return
            remaining -= slice_s
            focused = self._safe_focus(hwnd)
            self._record_focus(focused, visited, last_focus_holder)

    def _publish(self, observation: Observation) -> None:
        # Overwrite. There is no history and no append anywhere in this
        # class — that is the whole architectural claim of the slot.
        with self._lock:
            self._slot = observation

    # -- worker ------------------------------------------------------------
    def _run(self, stop: threading.Event, generation: int) -> None:
        # `stop` is this generation's Event, passed in rather than read from
        # self._stop: an orphaned worker must keep checking the Event it was
        # started with, not whatever the current generation is using.
        try:
            import pythoncom

            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        except Exception:
            # Without COM this worker cannot observe anything, but it must
            # not die silently — it keeps looping and the staleness ladder
            # reports the resulting absence of observations.
            pass

        try:
            visited: list[str] = []
            #: Survives `visited.clear()` at every successful publish (unlike
            #: `visited`, which is per-interval) -- it lives for the whole
            #: worker generation, so a control that never lost focus across
            #: many observations is never reported as freshly "visited". See
            #: `_record_focus`.
            last_focus_holder: list = [None]
            while not stop.is_set():
                self.heartbeat += 1
                iteration_started = self.clock()
                self._progress(
                    generation,
                    stage="starting",
                    iteration_started=iteration_started,
                    error=None,
                )
                walked = None
                target_hwnd_for_wait = 0
                stage = "hwnd"
                debug = os.environ.get("GHOSTCURSOR_DEBUG_PERCEPTION") == "1"
                if debug:
                    print(
                        f"Ghost Cursor: perception iteration {self.heartbeat} starting"
                    )
                try:
                    self._progress(generation, stage="hwnd")
                    target_hwnd = self._safe_hwnd()
                    target_hwnd_for_wait = target_hwnd
                    if debug:
                        print(f"Ghost Cursor: hwnd lookup returned {target_hwnd}")
                    stage = "focus"
                    self._progress(generation, stage="focus")
                    focused_now = self._safe_focus(target_hwnd)
                    if debug:
                        print(f"Ghost Cursor: focus sample returned {focused_now!r}")
                    # Recovers the walk-start sample that would otherwise be
                    # read and discarded: this is the ONE moment focus is read
                    # outside `_sample_focus_while_waiting`, and until now it
                    # went only to the snapshot, never into `visited`. Does
                    # not close the blind window -- the walk itself
                    # (0.18-0.70s) and tier 2 when standing (0.14-0.23s) still
                    # pass with no sampling at all -- but it is one line and
                    # strictly better. See design spec section 7's corrected
                    # trigger. Goes through `_record_focus` like every other
                    # sample, so it only ever records a TRANSITION.
                    self._record_focus(focused_now, visited, last_focus_holder)
                    stage = "walk"
                    self._progress(generation, stage="walk")
                    if debug:
                        print("Ghost Cursor: UIA walk starting")
                    if self.plan_runner is not None:
                        selector_results, elements = self.plan_runner(target_hwnd)
                        elements = tuple(elements)
                    else:
                        selector_results = ()
                        elements = tuple(self.walker(self.title_re))
                    self._progress(generation, stage="walk-complete")
                    if debug:
                        print(
                            f"Ghost Cursor: perception walk returned {len(elements)} element(s)"
                        )
                    observed_at = self.clock()
                    stage = "snapshot"
                    self._progress(generation, stage="snapshot")
                    walked = (
                        take_snapshot(
                            self.title_re,
                            elements=elements,
                            observed_at=observed_at,
                            focused_automation_id=focused_now,
                            selector_results=selector_results,
                        ),
                        elements,
                        observed_at,
                        target_hwnd,
                    )
                except Exception as exc:
                    # A failed walk publishes nothing: the previous
                    # observation simply keeps ageing, which is exactly what
                    # the staleness ladder is for. The heartbeat still
                    # advances, so "looping through failures" stays
                    # distinguishable from "blocked in a call".
                    if os.environ.get("GHOSTCURSOR_DEBUG_PERCEPTION") == "1":
                        print(f"Ghost Cursor: perception {stage} failed: {exc!r}")
                    self._progress(
                        generation,
                        stage=f"{stage}-failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )

                # Tier 2 runs HERE, on this thread -- never on the UI thread.
                # Capture plus OCR measured 0.14-0.23s on a 976x1028 window and
                # scales with captured AREA, which on a full 4K screen alone
                # would eat D020's 0.5s tick ceiling and reintroduce the freeze
                # D021 exists to prevent.
                #
                # OUTSIDE the walk's try, deliberately. Tier 2 needs only a
                # capture, so a walker that raises every iteration -- the
                # window transiently gone, a COM hiccup -- must not silently
                # suppress OCR: that is precisely the situation OCR exists for.
                # The two halves fail independently; only publication is joint.
                self._progress(generation, stage="tier2")
                ocr = self._tier2_payload()
                self._progress(generation, stage="tier2-complete")

                if walked is not None and not stop.is_set():
                    # A retired worker must not publish the walk it was
                    # already inside when it was retired: the timestamp
                    # would be current while the contents are from
                    # before the restart, and it could land after the
                    # replacement's newer observation.
                    snapshot, elements, observed_at, target_hwnd = walked
                    self._publish(
                        Observation(
                            snapshot=snapshot,
                            elements=elements,
                            observed_at=observed_at,
                            ok=True,
                            ocr_elements=ocr[0],
                            tier2_step=ocr[1],
                            tier2_engaged=ocr[2],
                            tier2_exhausted=ocr[3],
                            tier2_max_runs=ocr[4],
                            target_hwnd=target_hwnd,
                            focus_visited=tuple(visited),
                        )
                    )
                    self._progress(
                        generation, stage="published", published=self.clock()
                    )
                    # Cleared only here, on a SUCCESSFUL publish -- not on
                    # every iteration. A walk that raises must not discard
                    # this interval's ids: nothing was published to carry
                    # them, so the next successful observation is the first
                    # chance the contract (see `Observation.focus_visited`'s
                    # docstring: "since the previous observation") has to
                    # report them. The competing risk -- a long failure
                    # streak eventually reporting a detour from several
                    # seconds ago -- is real but bounded by
                    # MAX_FOCUS_VISITED, and Task 3 only fires while the step
                    # is still unsatisfied, so a stale-but-unresolved wrong
                    # action is still a true statement about a step the user
                    # has not completed. Losing evidence of a real user
                    # action is the worse failure.
                    visited.clear()
                self._progress(generation, stage="idle")
                self._sample_focus_while_waiting(
                    stop, target_hwnd_for_wait, visited, last_focus_holder
                )
                self._progress(generation, stage="idle", completed=self.clock())
        finally:
            try:
                import pythoncom

                pythoncom.CoUninitialize()
            except Exception:
                pass


# --------------------------------------------------------------------------
# Compiled observation plans
#
# The executor for a `ghostcursor.packs.compile.ObservationPlan`. It lives on
# the perception side because it touches UIA; the plan itself is pure data
# compiled from a verified recipe, so nothing here is workflow-specific.
#
# Not yet wired into the production tick: the v1 walkers stay in place until
# the cutover, and this is exercised through tests and the candidate harness.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TickObservation:
    """What one bounded observation tick publishes.

    Two views of the same read, and both are needed. `selectors` answers "what
    did THIS selector match", which is what a step's action and its
    verification each ask. `union` answers "what did this tick observe at
    all", which is what anything reasoning over the screen as a whole needs --
    and it cannot be rebuilt from `selectors` afterwards, because by then the
    elements are frozen values with no backend identity and merging them would
    have to fall back on value equality (D021, D069).

    So the union is deduplicated worker-side, while the handles are still
    live: identity-bearing duplicates collapse, identity-less candidates are
    all retained. Two selectors matching the same control contribute it once;
    two indistinguishable controls stay two.
    """

    selectors: Mapping[str, tuple[Element, ...]]
    union: tuple[Element, ...]


def run_observation_plan(
    plan,
    *,
    walk_for,
    query_for,
    make_info,
) -> TickObservation:
    """Observe every selector in `plan` in one tick.

    `walk_for(control_type)` returns a callable performing one bounded walk of
    that control type; `query_for(control_type, name)` returns a callable
    performing one provider `FindAll`; `make_info(raw)` wraps a provider result
    for property reads. All three are injected so the grouping and failure
    rules can be exercised with no live provider.

    **Each compiled group is read exactly once.** A bounded traversal runs one
    walk per control type; a provider query performs one `FindAll`. Every
    selector in the group then judges its own cardinality and limit over that
    single shared read. Reading per selector instead would let two selectors
    on one compiled query observe two different screens within one tick and
    disagree about how many controls exist -- a disagreement no caller could
    detect, because each read is individually consistent.

    **A non-absence fault invalidates the entire tick.** The fault propagates
    and the caller publishes nothing. Publishing the selectors that did read
    would be a partial observation that looks complete: a verification whose
    selector faulted would see an empty result and read it as "the control is
    not there", which is the flattening of fault into absence that D069
    exists to prevent. A clean absence is not a fault and publishes as an
    empty tuple.
    """
    from ghostcursor.perception import uia

    results: dict[str, tuple[Element, ...]] = {}
    observed: list[uia.Candidate] = []

    for traversal in plan.traversals:
        # ONE walk per unique control type, shared by every selector over it.
        walk = walk_for(traversal.control_type)
        try:
            candidates = list(walk())
        except Exception as exc:  # noqa: BLE001 - re-raised as a typed fault
            raise uia.ProviderQueryFault(
                f"bounded walk of {traversal.control_type} failed: {exc}"
            ) from exc
        for selector_id in traversal.selector_ids:
            selector = plan.selectors[selector_id]
            # Each selector filters the SHARED candidates independently and
            # judges its own cardinality. The walk is shared; the answer is not.
            chosen = uia.bounded_candidates(
                lambda candidates=candidates: candidates,
                selector.names,
                limit=selector.result_limit,
                cardinality=selector.cardinality,
                normalise=selector.normalise,
            )
            results[selector_id] = tuple(c.element for c in chosen)
            observed.extend(chosen)

    for query in plan.queries:
        # ONE FindAll per compiled query, shared by every selector on it.
        found = uia.provider_candidates(
            query_for(query.control_type, query.name), make_info
        )
        for selector_id in query.selector_ids:
            selector = plan.selectors[selector_id]
            chosen = uia.apply_cardinality(
                found,
                cardinality=selector.cardinality,
                limit=selector.result_limit,
                label="provider selector",
            )
            results[selector_id] = tuple(c.element for c in chosen)
            observed.extend(chosen)

    missing = set(plan.selectors) - results.keys()
    if missing:  # pragma: no cover - every selector belongs to a group
        raise uia.ProviderQueryFault(f"plan left selectors unobserved: {sorted(missing)}")

    # Deduplicate the union HERE, while the identities are still live. After
    # this point only Elements survive, and merging those would mean value
    # equality -- which cannot tell one control reached by two selectors from
    # two controls that agree on every published field.
    union = tuple(c.element for c in uia.deduplicated(observed))
    return TickObservation(selectors=MappingProxyType(results), union=union)
