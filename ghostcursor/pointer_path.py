"""Where the ghost pointer is, frame by frame, and for how long.

Pure geometry and timing. It computes a path and a schedule and draws nothing,
because the parts that can be wrong here — an endpoint that misses the
control, a frame count that overruns the input-poll floor, a settle that ends
before the label is readable — are all arithmetic, and arithmetic can be
tested without a desktop.

Two rules the numbers serve, both from D109:

**The pointer ends where the action happens.** The final frame sits at the
centre of the control's own rectangle, not near it, because the click is
dispatched to that control while the pointer is displayed there.

**The movement is followable.** A traversal the eye cannot track, or a label
that lands after the click, communicate nothing. The dwell is the deliverable,
not overhead to trim.

Frame counts are DERIVED from a measured paint cost. There is no default:
Phase E measures what a full-overlay paint actually costs on the machine, and
a plausible constant here would be the placeholder that measurement exists to
replace — and the number every test would silently agree with.
"""

from __future__ import annotations

from dataclasses import dataclass


class PointerPathError(ValueError):
    """A path or schedule that must not be presented."""


def centre_of(rectangle) -> tuple[int, int]:
    """The centre of a (left, top, right, bottom) rectangle.

    That convention, not (left, top, width, height): observed rectangles come
    from UIA and `EnumDisplayMonitors`, and this module is only ever handed
    observed rectangles. Mixing the two would put the pointer somewhere
    plausible and wrong.
    """

    left, top, right, bottom = _rectangle(rectangle)
    return ((left + right) // 2, (top + bottom) // 2)


def _rectangle(value) -> tuple[int, int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise PointerPathError("a rectangle is four integers")
    parts = []
    for part in value:
        if isinstance(part, bool) or not isinstance(part, int):
            raise PointerPathError("rectangle coordinates must be integers")
        parts.append(part)
    left, top, right, bottom = parts
    if right <= left or bottom <= top:
        # A degenerate rectangle has no centre worth pointing at, and would
        # place the pointer on an edge or outside the control entirely.
        raise PointerPathError(f"rectangle {tuple(parts)} has no positive area")
    return left, top, right, bottom


def ease_out(fraction: float) -> float:
    """Cubic ease-out.

    Fast departure, slow arrival. The slow end is the point: the eye needs
    the most time exactly where the pointer is coming to rest, because that
    is the position the action is about to happen at.
    """

    if not 0.0 <= fraction <= 1.0:
        raise PointerPathError("progress is a fraction between 0 and 1")
    return 1.0 - (1.0 - fraction) ** 3


def frame_count(traversal_ms: int, frame_budget_ms: int, *, ceiling: int = 12) -> int:
    """How many frames a traversal may use, from a MEASURED paint cost.

    `frame_budget_ms` is what one full-overlay paint was measured to cost,
    with margin. It is required, because a default would be a number nobody
    measured, and every test would agree with it.
    """

    for label, value in (
        ("traversal_ms", traversal_ms),
        ("frame_budget_ms", frame_budget_ms),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise PointerPathError(f"{label} must be a positive integer")
    return max(1, min(ceiling, traversal_ms // frame_budget_ms))


@dataclass(frozen=True)
class Frame:
    """One painted position, and when it is due."""

    x: int
    y: int
    at_ms: float
    final: bool


def traversal(
    start,
    target,
    *,
    traversal_ms: int,
    frame_budget_ms: int,
    ceiling: int = 12,
) -> tuple[Frame, ...]:
    """Frames from ``start`` to the centre of ``target``.

    ``start`` may be None — the first cue of a run has nowhere to come from,
    and a pointer that flies in from an arbitrary corner would suggest it had
    been somewhere it was not. That case is a single settled frame at the
    destination.
    """

    end_x, end_y = centre_of(target)
    if start is None:
        return (Frame(end_x, end_y, 0.0, True),)
    if (
        not isinstance(start, (list, tuple))
        or len(start) != 2
        or any(isinstance(v, bool) or not isinstance(v, int) for v in start)
    ):
        raise PointerPathError("a start position is two integers")
    start_x, start_y = start
    if (start_x, start_y) == (end_x, end_y):
        # Already there. Moving zero distance over 400 ms reads as a freeze,
        # not as motion.
        return (Frame(end_x, end_y, 0.0, True),)

    count = frame_count(traversal_ms, frame_budget_ms, ceiling=ceiling)
    step_ms = traversal_ms / count
    frames = []
    for index in range(1, count + 1):
        progress = ease_out(index / count)
        frames.append(
            Frame(
                round(start_x + (end_x - start_x) * progress),
                round(start_y + (end_y - start_y) * progress),
                index * step_ms,
                index == count,
            )
        )
    # The last frame lands exactly on the centre, never on a rounded
    # approximation of it: the pointer must be ON the control it is about to
    # act on, not a pixel beside it.
    last = frames[-1]
    frames[-1] = Frame(end_x, end_y, last.at_ms, True)
    return tuple(frames)


@dataclass(frozen=True)
class Schedule:
    """The full timing of one cue, in milliseconds from its request."""

    frames: tuple[Frame, ...]
    settled_until_ms: float
    poll_interval_ms: int

    @property
    def total_ms(self) -> float:
        return self.settled_until_ms

    def poll_points(self) -> tuple[float, ...]:
        """Instants at which Stop, Pause and ESC must be checked.

        Dense enough that the longest gap never exceeds the poll interval —
        the whole presentation is time in which the user must be able to
        interrupt, and the settle is the longest stretch with nothing else
        happening.
        """

        points = []
        moment = 0.0
        while moment < self.settled_until_ms:
            points.append(moment)
            moment += self.poll_interval_ms
        points.append(self.settled_until_ms)
        return tuple(points)


def schedule_for(
    start,
    target,
    *,
    traversal_ms: int,
    settle_ms: int,
    frame_budget_ms: int,
    poll_interval_ms: int = 50,
    ceiling: int = 12,
) -> Schedule:
    """The complete cue: move, then hold still long enough to be read."""

    for label, value in (
        ("settle_ms", settle_ms),
        ("poll_interval_ms", poll_interval_ms),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise PointerPathError(f"{label} must be a positive integer")
    if frame_budget_ms > poll_interval_ms:
        # One paint must not outlast the interval in which the user's Stop has
        # to be noticed. If it does, geometry is not affordable on this
        # machine and the caller must fall back to rail text.
        raise PointerPathError(
            f"a {frame_budget_ms}ms paint cannot hold a {poll_interval_ms}ms "
            "poll interval"
        )
    frames = traversal(
        start,
        target,
        traversal_ms=traversal_ms,
        frame_budget_ms=frame_budget_ms,
        ceiling=ceiling,
    )
    return Schedule(frames, frames[-1].at_ms + settle_ms, poll_interval_ms)


__all__ = [
    "Frame",
    "PointerPathError",
    "Schedule",
    "centre_of",
    "ease_out",
    "frame_count",
    "schedule_for",
    "traversal",
]
