"""How old an observation may get before the overlay stops trusting it.

Staged rather than a single policy, because the honest answer changes with
age: through ordinary tick jitter the hint is still right; a little later it
is "last known, unconfirmed"; later still the odds the UI has actually moved
outweigh the value of showing a ring at all.

Measured from the last CONFIRMED-FRESH observation — a walk that completed
without raising, however many elements it found — and never reset by a single
lucky observation, so a flaky application cannot flicker between states.
"""

from __future__ import annotations

import time
from enum import Enum, auto
from typing import Callable

DEFAULT_DIM_AFTER_S = 1.5
DEFAULT_HIDE_AFTER_S = 5.0
#: Consecutive observations required to leave HIDDEN. One is not enough: a
#: half-hung app that answers occasionally would otherwise blink the hint.
DEFAULT_RECOVER_AFTER = 3


class Freshness(Enum):
    FRESH = auto()  # draw the hint normally
    DIMMED = auto()  # draw it, visibly unconfirmed
    INFERRED = auto()  # draw it, but it was read off pixels, not confirmed
    HIDDEN = auto()  # draw nothing


class StalenessLadder:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        dim_after_s: float = DEFAULT_DIM_AFTER_S,
        hide_after_s: float = DEFAULT_HIDE_AFTER_S,
        recover_after: int = DEFAULT_RECOVER_AFTER,
    ) -> None:
        self.clock = clock
        self.dim_after_s = dim_after_s
        self.hide_after_s = hide_after_s
        self.recover_after = recover_after
        self._last_seen: float | None = None
        self._streak = 0
        # Debounced recovery only applies once we have actually gone HIDDEN
        # due to staleness. Before the very first observation there is
        # nothing to "recover" from — a single fresh observation is enough
        # to show the hint. Conflating "never observed" with "needs a
        # debounced recovery run" would make the very first observed() call
        # sit hidden for `recover_after` ticks, which is not the intent.
        self._needs_recovery = False

    def observed(self) -> None:
        """Record a confirmed-fresh observation."""
        now = self.clock()
        if self._last_seen is not None and now - self._last_seen > self.hide_after_s:
            self._streak = 0  # the gap broke any recovery run
            self._needs_recovery = True
        self._last_seen = now
        self._streak += 1
        if self._needs_recovery and self._streak >= self.recover_after:
            self._needs_recovery = False

    def age(self) -> float:
        if self._last_seen is None:
            return float("inf")
        return self.clock() - self._last_seen

    def freshness(self) -> Freshness:
        if self._last_seen is None:
            return Freshness.HIDDEN
        age = self.age()
        if age > self.hide_after_s:
            self._needs_recovery = True
            self._streak = 0
            return Freshness.HIDDEN
        if self._needs_recovery:
            return Freshness.HIDDEN
        if age > self.dim_after_s:
            return Freshness.DIMMED
        return Freshness.FRESH


def display_freshness(ladder_state: Freshness, source: str) -> Freshness:
    """Combine the staleness axis with the source axis into what is drawn.

    Two independent doubts: DIMMED is about TIME ("was this true a moment
    ago"), INFERRED is about SOURCE ("I matched text on pixels rather than
    confirming the control"). Collapsing them would tell the user to be
    careful without telling them what kind of caution applies.

    Precedence is strict: HIDDEN > DIMMED > INFERRED > FRESH. Staleness
    dominates, because "possibly outdated" subsumes "possibly misread".

    The source axis PERSISTS underneath the display: a stale OCR hint shows
    DIMMED, and when perception recovers this returns INFERRED, never FRESH.
    Otherwise a round trip through staleness would launder a pixel guess into
    a confirmed control.

    FRESH requires a recognized confirmed source (currently only "uia").
    Everything else—including future tiers like "vlm", unrecognized strings,
    typos, or missing values—is deliberately treated as INFERRED rather than
    trusted. This is the fail-safe direction: an unknown source shown as
    slightly-cautious costs nothing; the same source shown as fully trusted
    violates the safety rule.
    """
    if ladder_state in (Freshness.HIDDEN, Freshness.DIMMED):
        return ladder_state
    return Freshness.FRESH if source == "uia" else Freshness.INFERRED
