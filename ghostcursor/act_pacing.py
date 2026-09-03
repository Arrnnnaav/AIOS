"""How fast a run goes, and how it stays stoppable while going slowly.

Two modes, and the difference between them is entirely presentational:

- **Quick Build** runs at the executor's own speed. 255 object-model nodes in
  about 65 seconds. Nothing waits.
- **Watch Build** paces each node so a person can follow what is happening.
  The same nodes, the same order, the same authorization — only slower.

**A pause is never a plain sleep.** This is the whole reason this module
exists. `time.sleep(400)` between nodes would make Watch Build the mode in
which Stop does not work: the run would sit inside a call that cannot be
interrupted for four tenths of a second at a time, and D020 gives the abort
path half a second total. So every wait here is sliced, and the interrupt is
read on every slice. Going slower must give the user MORE chances to stop the
run, not fewer, and that is only true if the waiting itself is interruptible.

**These numbers are a choice, not a measurement.** Unlike `frame_budget_ms`,
which is a measured paint cost and therefore has no default, a pacing delay
is a preference about legibility. It gets a default and is labelled as what
it is, so nobody later cites it as though something had been measured (D034).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

#: The longest a wait may go without reading the interrupt. Matches the
#: presenter's poll interval deliberately: the two are the same promise about
#: how soon a Stop is noticed, and letting them differ would mean the answer
#: depended on which part of a node the user pressed it in.
POLL_INTERVAL_MS = 50


class PacingError(ValueError):
    """A pace that must not be run."""


@dataclass(frozen=True)
class Pace:
    """What a mode waits for, in milliseconds.

    `before_node_ms` is the pause the user reads the upcoming step in;
    `after_node_ms` is the beat that lets the document change register before
    the next one starts. Both exist because a change that appears and is
    immediately replaced reads as a flicker rather than as an action.
    """

    name: str
    before_node_ms: int = 0
    after_node_ms: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise PacingError("a pace needs a name")
        for label in ("before_node_ms", "after_node_ms"):
            value = getattr(self, label)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PacingError(f"{label} must be a non-negative integer")

    @property
    def total_ms(self) -> int:
        return self.before_node_ms + self.after_node_ms

    @property
    def waits(self) -> bool:
        return self.total_ms > 0


#: The executor's own speed. Nothing waits, so nothing here can delay a Stop.
QUICK = Pace("quick")

#: Paced for watching. Chosen for legibility, not measured: roughly a beat to
#: read the step and a beat to see the slide change. On the 255-node deck this
#: is about 255 x 0.55s of added time on top of the 65s build.
WATCH = Pace("watch", before_node_ms=300, after_node_ms=250)

PACES = {pace.name: pace for pace in (QUICK, WATCH)}


def pace_by_name(name: str) -> Pace:
    try:
        return PACES[name]
    except KeyError:
        raise PacingError(
            f"unknown pace {name!r}; known paces are {sorted(PACES)}"
        ) from None


def interruptible_wait(
    duration_ms: int,
    *,
    poll: Callable[[], bool],
    clock: Callable[[], float],
    sleep: Callable[[float], None] | None = None,
    interval_ms: int = POLL_INTERVAL_MS,
) -> bool:
    """Wait ``duration_ms``, reading ``poll`` at least every ``interval_ms``.

    Returns False the moment ``poll`` does, without finishing the wait.

    ``poll`` is asked BEFORE the deadline is checked, so a zero-length wait
    still reads the interrupt once. Otherwise Quick Build — where every wait
    is zero — would be a mode that never checks Stop between nodes at all,
    and the pacing setting would silently decide whether the run was
    interruptible.
    """

    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int):
        raise PacingError("duration_ms must be an integer")
    if duration_ms < 0:
        raise PacingError("duration_ms must not be negative")
    if isinstance(interval_ms, bool) or not isinstance(interval_ms, int):
        raise PacingError("interval_ms must be an integer")
    if interval_ms <= 0:
        raise PacingError("interval_ms must be positive")
    if sleep is None:
        sleep = _sleep

    deadline = clock() + duration_ms
    while True:
        if not poll():
            return False
        remaining = deadline - clock()
        if remaining <= 0:
            return True
        sleep(min(float(interval_ms), remaining))


def _sleep(milliseconds: float) -> None:
    """Replaced in tests by passing `sleep=`, so a paced run costs nothing to
    test. Kept as a module function rather than an inline call so the
    production path has no branch that exists only for tests."""

    time.sleep(milliseconds / 1000.0)


__all__ = [
    "PACES",
    "POLL_INTERVAL_MS",
    "QUICK",
    "WATCH",
    "Pace",
    "PacingError",
    "interruptible_wait",
    "pace_by_name",
]
