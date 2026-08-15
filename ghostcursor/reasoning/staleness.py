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

import sys
import time
from enum import Enum, auto
from typing import Callable

DEFAULT_DIM_AFTER_S = 1.5
DEFAULT_HIDE_AFTER_S = 5.0
#: How long observations may keep arriving with nobody ever ASKING what to
#: draw, before the ladder says so. Deliberately longer than hide_after_s: by
#: then the hint should certainly have dimmed and hidden at least once, so
#: silence past this point means the display state is not being read at all.
#:
#: The failure this catches has no other symptom. A driver that never calls
#: `renderer.settle()` leaves the ladder unqueried: the hint never dims, never
#: hides, and the recovery debounce never arms — the system looks fine and
#: quietly stops degrading honestly. That is the shape that has bitten this
#: project three times, and it is invisible precisely because nothing errors.
DEFAULT_UNQUERIED_AFTER_S = 3.0 * DEFAULT_HIDE_AFTER_S
#: Consecutive observations required to leave HIDDEN. One is not enough: a
#: half-hung app that answers occasionally would otherwise blink the hint.
DEFAULT_RECOVER_AFTER = 3


def _warn_to_stderr(message: str) -> None:
    """Where the unqueried-ladder report goes.

    stderr, not stdout: stdout carries the tour's own step-by-step guidance,
    and this is a developer-facing report about a driver bug, not something
    the user did. It is also not the primary guard — `GuidedTour.tick()`
    calls `settle()` itself, so a driver cannot omit it — which matters,
    because the user of a full-screen click-through overlay is not watching a
    console at all.
    """
    print(message, file=sys.stderr)


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
        unqueried_after_s: float = DEFAULT_UNQUERIED_AFTER_S,
        warn=None,
    ) -> None:
        self.clock = clock
        self.dim_after_s = dim_after_s
        self.hide_after_s = hide_after_s
        self.recover_after = recover_after
        self.unqueried_after_s = unqueried_after_s
        self.warn = warn if warn is not None else _warn_to_stderr
        #: When the display state was last asked for, or when observations
        #: started arriving if it never has been. See DEFAULT_UNQUERIED_AFTER_S.
        self._last_queried: float | None = None
        self._warned_unqueried = False
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
        self._check_someone_is_reading(now)

    def _check_someone_is_reading(self, now: float) -> None:
        """Say so, once, if observations keep arriving and nobody ever asks.

        Perception working while the display state is never read is a silent
        freeze, not an error: the hint stays as it was drawn, forever. Only
        the ladder can see it — it is the one object that knows both that
        observations are flowing and that nothing is consuming its verdict.
        """
        if self._last_queried is None:
            self._last_queried = now
            return
        if self._warned_unqueried:
            return
        if now - self._last_queried > self.unqueried_after_s:
            self._warned_unqueried = True
            self.warn(
                "Ghost Cursor: the hint's display state has not been read for "
                f"{now - self._last_queried:.0f}s while observations keep "
                "arriving — the overlay is frozen at whatever it last drew and "
                "will never dim or hide. Whatever drives the loop is not "
                "calling renderer.settle() each tick (D027)."
            )

    def age(self) -> float:
        if self._last_seen is None:
            return float("inf")
        return self.clock() - self._last_seen

    def freshness(self) -> Freshness:
        # Recording the read is the whole basis of the unqueried check above:
        # this is the only call that means "something is going to act on the
        # verdict". Note this method also MUTATES recovery state, which is why
        # callers must ask exactly once per tick.
        self._last_queried = self.clock()
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
