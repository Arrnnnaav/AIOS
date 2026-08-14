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

#: How long without a confirmed-fresh observation before a living worker is
#: treated as dead. Comfortably past the ~10s bound a hung application
#: imposes, so an ordinary hang is not mistaken for a dead worker.
DEFAULT_DEAD_AFTER_S = 15.0


class WorkerHealth:
    def __init__(
        self,
        service,
        ladder,
        dead_after_s: float = DEFAULT_DEAD_AFTER_S,
        log: Callable[[str], None] = print,
    ) -> None:
        self.service = service
        self.ladder = ladder
        self.dead_after_s = dead_after_s
        self.log = log
        self._restarted = False
        #: When the replacement worker started, on the LADDER's clock — the
        #: same clock the stall decision is measured against, so the two can
        #: never disagree and no second clock has to be injected.
        self._restarted_at: float | None = None

    def check(self) -> str | None:
        """Called once per tick. Returns a failure reason when the tour
        should end, otherwise None."""
        dead = not self.service.is_alive()
        stalled = self.ladder.age() > self.dead_after_s
        if (
            stalled
            and self._restarted_at is not None
            and self.ladder.clock() - self._restarted_at <= self.dead_after_s
        ):
            # A replacement worker inherits the staleness of the one it
            # replaced — the clock measures observations, not workers. Judging
            # it on that would end the tour on the very next tick, so give it
            # the same budget the original had before calling it stalled too.
            stalled = False
        if not (dead or stalled):
            return None

        cause = "exited" if dead else f"stalled for {self.ladder.age():.1f}s"
        # Heartbeat is recorded, never consulted: it tells a later reader
        # whether the worker was blocked in a call or looping through
        # failures.
        self.log(
            f"Ghost Cursor: perception worker {cause} "
            f"(heartbeat {self.service.heartbeat})"
        )

        if self._restarted:
            return f"perception stopped working ({cause}); ending the tour"

        self._restarted = True
        self._restarted_at = self.ladder.clock()
        self.service.restart()
        self.log("Ghost Cursor: restarted the perception worker")
        return None
