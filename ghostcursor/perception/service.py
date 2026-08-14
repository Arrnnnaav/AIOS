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
class Observation:
    """One completed look at the target. Crosses the thread boundary, so
    every field is a primitive or a frozen dataclass of primitives."""

    snapshot: Snapshot
    elements: tuple[Element, ...]
    observed_at: float
    ok: bool


class PerceptionService:
    def __init__(
        self,
        title_re: str,
        walker: Callable[[str], list[Element]] = iter_elements,
        clock: Callable[[], float] = time.monotonic,
        interval_s: float = DEFAULT_INTERVAL_S,
    ) -> None:
        self.title_re = title_re
        self.walker = walker
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
                try:
                    elements = tuple(self.walker(self.title_re))
                    observed_at = self.clock()
                    snapshot = take_snapshot(
                        self.title_re, elements=elements, observed_at=observed_at
                    )
                    if not stop.is_set():
                        # A retired worker must not publish the walk it was
                        # already inside when it was retired: the timestamp
                        # would be current while the contents are from
                        # before the restart, and it could land after the
                        # replacement's newer observation.
                        self._publish(
                            Observation(
                                snapshot=snapshot,
                                elements=elements,
                                observed_at=observed_at,
                                ok=True,
                            )
                        )
                except Exception:
                    # A failed walk publishes nothing: the previous
                    # observation simply keeps ageing, which is exactly what
                    # the staleness ladder is for. The heartbeat still
                    # advances, so "looping through failures" stays
                    # distinguishable from "blocked in a call".
                    pass
                stop.wait(self.interval_s)
        finally:
            try:
                import pythoncom

                pythoncom.CoUninitialize()
            except Exception:
                pass
