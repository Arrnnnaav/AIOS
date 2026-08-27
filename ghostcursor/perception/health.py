"""Detecting a perception worker that has stopped doing its job.

Two signals drive recovery, and a third is diagnosis only:

  * the staleness clock detects "alive but not progressing" — it is already
    needed to decide what the overlay shows, so it is free here;
  * Thread.is_alive() distinguishes "the worker raised and exited", which the
    clock alone would report as merely stale forever;
  * the heartbeat counter is LOGGED when the policy fires and never read by
    it. It separates "blocked in a slow UIA call" from "alive but looping
    through silent failures" after the fact, without that distinction
    quietly influencing behaviour.

Policy: restart exactly once, then end the tour with an explicit reason. A
worker that dies twice is not going to recover, and sitting silently stuck is
the failure mode this exists to prevent.

For that policy to mean anything, the replacement worker gets a fresh budget
before the STALL signal may judge it. The staleness clock belongs to the
observations, not to the worker, so a restart does not reset it — the tick
after a restart would otherwise re-fire on the dead worker's staleness and end
the tour ~0.25s later, having never given the replacement a chance to observe
anything. "Restart once, then give up" would degenerate into "give up".

The fresh budget deliberately does NOT apply to the `is_alive()` signal. A
thread that is not running is a definitive answer available immediately;
"stalled" is the only signal that needs time to accumulate.
"""

from __future__ import annotations

from typing import Callable

#: A worker can legitimately spend a short interval inside a complex UIA
#: walk. This is a diagnostic threshold, not a restart threshold.
DEFAULT_SLOW_AFTER_S = 2.0
#: The escape hatch for a living worker that has not completed an iteration.
DEFAULT_DEAD_AFTER_S = 12.0


class PerceptionUnhealthy(RuntimeError):
    """The health policy has given up on this worker.

    Raised rather than returned so a caller cannot mistake it for an ordinary
    empty observation. `check()` returning a reason is the END of the tour --
    the restart has already been spent -- and a source that discarded that
    reason went on publishing the last stale slot, which reads exactly like a
    screen that stopped changing.
    """


class WorkerHealth:
    def __init__(
        self,
        service,
        ladder,
        dead_after_s: float = DEFAULT_DEAD_AFTER_S,
        slow_after_s: float = DEFAULT_SLOW_AFTER_S,
        log: Callable[[str], None] = print,
    ) -> None:
        self.service = service
        self.ladder = ladder
        self.dead_after_s = dead_after_s
        self.slow_after_s = slow_after_s
        self.log = log
        self._restarted = False
        #: When the replacement worker started, on the LADDER's clock — the
        #: same clock the stall decision is measured against, so the two can
        #: never disagree and no second clock has to be injected.
        self._restarted_at: float | None = None
        self._last_state: str | None = None

    def check(self) -> str | None:
        """Called once per tick. Returns a failure reason when the tour
        should end, otherwise None."""
        dead = not self.service.is_alive()
        progress = self.service.progress() if hasattr(self.service, "progress") else None
        now = self.ladder.clock()
        if progress is not None and progress.last_completed_at is not None:
            progress_age = max(0.0, now - progress.last_completed_at)
        else:
            progress_age = self.ladder.age()
        stalled = progress_age > self.dead_after_s
        if (
            stalled
            and self._restarted_at is not None
            and now - self._restarted_at <= self.dead_after_s
        ):
            # A replacement worker inherits the staleness of the one it
            # replaced — the clock measures observations, not workers. Judging
            # it on that would end the tour on the very next tick, so give it
            # the same budget the original had before calling it stalled too.
            stalled = False
        if dead:
            state = "DEAD"
        elif stalled:
            state = "STALLED"
        elif progress_age > self.slow_after_s:
            state = "SLOW"
        else:
            state = "HEALTHY"
        # Some bounded test/services expose progress without the legacy
        # service-level counter, and some expose only the legacy counter.
        # Nested getattr defaults are evaluated eagerly, so using
        # ``getattr(progress, "heartbeat", self.service.heartbeat)`` crashes
        # even when progress already has the value. Resolve the fallback in
        # two explicit steps instead.
        service_heartbeat = getattr(self.service, "heartbeat", 0)
        heartbeat = getattr(progress, "heartbeat", service_heartbeat)
        if state != self._last_state:
            stage = getattr(progress, "stage", "unknown") if progress else "unknown"
            self.log(
                f"Ghost Cursor: perception health {state.lower()} "
                f"(stage {stage}, age {progress_age:.1f}s, heartbeat {heartbeat})"
            )
            self._last_state = state

        if state == "HEALTHY" or state == "SLOW":
            return None

        if dead:
            cause = "exited"
        elif progress_age == float("inf"):
            # Never observed anything at all — "stalled for inf s" is true but
            # tells a human nothing about what went wrong.
            cause = "never produced an observation"
        else:
            cause = f"stalled for {progress_age:.1f}s"
        # Heartbeat is recorded, never consulted: it tells a later reader
        # whether the worker was blocked in a call or looping through
        # failures.
        self.log(
            f"Ghost Cursor: perception worker {cause} "
            f"(stage {getattr(progress, 'stage', 'unknown')}, "
            f"heartbeat {heartbeat})"
        )

        if self._restarted:
            return f"perception stopped working ({cause}); ending the tour"

        self._restarted = True
        self._restarted_at = now
        self.service.restart()
        self.log("Ghost Cursor: restarted the perception worker")
        return None
