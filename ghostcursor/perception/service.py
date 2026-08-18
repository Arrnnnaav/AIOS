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
from dataclasses import dataclass
from typing import Callable

from ghostcursor.perception.uia import Element, iter_elements
from ghostcursor.reasoning.verification import Snapshot, take_snapshot

DEFAULT_INTERVAL_S = 0.2


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


class PerceptionService:
    def __init__(
        self,
        title_re: str,
        walker: Callable[[str], list[Element]] = iter_elements,
        clock: Callable[[], float] = time.monotonic,
        interval_s: float = DEFAULT_INTERVAL_S,
        tier2=None,
    ) -> None:
        self.title_re = title_re
        self.walker = walker
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

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self.is_alive():
            return  # a second worker would fight the first for the slot
        stop = threading.Event()
        self._stop = stop
        self._thread = threading.Thread(
            target=self._run, args=(stop,), name="ghostcursor-perception", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
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

    def _publish(self, observation: Observation) -> None:
        # Overwrite. There is no history and no append anywhere in this
        # class — that is the whole architectural claim of the slot.
        with self._lock:
            self._slot = observation

    # -- worker ------------------------------------------------------------
    def _run(self, stop: threading.Event) -> None:
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
            while not stop.is_set():
                self.heartbeat += 1
                walked = None
                try:
                    elements = tuple(self.walker(self.title_re))
                    observed_at = self.clock()
                    walked = (
                        take_snapshot(
                            self.title_re, elements=elements, observed_at=observed_at
                        ),
                        elements,
                        observed_at,
                    )
                except Exception:
                    # A failed walk publishes nothing: the previous
                    # observation simply keeps ageing, which is exactly what
                    # the staleness ladder is for. The heartbeat still
                    # advances, so "looping through failures" stays
                    # distinguishable from "blocked in a call".
                    pass

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
                ocr = self._tier2_payload()

                if walked is not None and not stop.is_set():
                    # A retired worker must not publish the walk it was
                    # already inside when it was retired: the timestamp
                    # would be current while the contents are from
                    # before the restart, and it could land after the
                    # replacement's newer observation.
                    snapshot, elements, observed_at = walked
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
                        )
                    )
                stop.wait(self.interval_s)
        finally:
            try:
                import pythoncom

                pythoncom.CoUninitialize()
            except Exception:
                pass
