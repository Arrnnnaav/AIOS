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

    def check(self) -> str | None:
        """Called once per tick. Returns a failure reason when the tour
        should end, otherwise None."""
        dead = not self.service.is_alive()
        stalled = self.ladder.age() > self.dead_after_s
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
        self.service.restart()
        self.log("Ghost Cursor: restarted the perception worker")
        return None
