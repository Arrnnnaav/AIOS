"""What one Act cue looks like: glyph shape, colour, and label placement.

Pure. No win32, no device context, no window — because the ways a cue can
mislead are nearly all arithmetic, and arithmetic can be checked without a
desktop:

- a pointer glyph whose *tip* is not on the control (D109: the pointer is
  shown where the click is dispatched, so the tip is the contract, not the
  glyph's bounding box);
- a label that covers the very control it names, leaving the user reading a
  word over a button they cannot see;
- a label that runs off the screen edge, so the last characters of "Insert →
  New Slide" are simply absent;
- a colour that happens to be the overlay's colorkey, which does not render as
  a colour at all — it renders as a hole.

`window.py` owns the GDI calls and consumes what this module computes.

Trust colours follow D109's classes. They are deliberately different HUES
rather than shades of one: a user who cannot tell "verified by reading the
saved file" from "verified from live UI state" from "nothing proven yet"
cannot calibrate trust, and calibrated trust is the whole point of showing
the cue at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TrustClass(str, Enum):
    """How strongly a step was proven, for presentation (the colour key)."""

    #: Verified by reading the saved artifact.
    ARTIFACT = "artifact"
    #: Verified from fresh live UI state after a true UIA pattern.
    LIVE_STATE = "live_state"
    #: Verified from live state after a LegacyIAccessible default action.
    #: Weaker targeting semantics than LIVE_STATE, and never presented as it.
    LEGACY_LIVE_STATE = "legacy_live_state"
    #: Inferred, or a raw-input action.
    INFERRED = "inferred"
    #: Nothing proven yet.
    NEUTRAL = "neutral"
    #: Refused or failed.
    REFUSED = "refused"

#: The overlay's transparent colour. Any cue painted in exactly this value
#: would be punched out of the window rather than drawn, so it is imported
#: here as a value to REFUSE, not as one to use. Kept as a literal rather
#: than imported from `window` so this module stays free of win32.
COLORKEY_RGB = (255, 0, 255)


class CueLayoutError(ValueError):
    """A cue that must not be presented."""


#: Trust class -> RGB. Chosen for hue separation, and none of them is the
#: colorkey: `LEGACY_LIVE_STATE` is the near miss, since the natural colour
#: for it is magenta and the colorkey IS magenta. It is pulled to a violet-red
#: that reads as its own hue and still renders.
TRUST_COLOURS: dict[TrustClass, tuple[int, int, int]] = {
    TrustClass.ARTIFACT: (0, 200, 255),  # cyan
    TrustClass.LIVE_STATE: (170, 120, 255),  # violet
    TrustClass.LEGACY_LIVE_STATE: (230, 60, 170),  # violet-red, NOT the key
    TrustClass.INFERRED: (255, 170, 0),  # amber, as Teach already uses
    TrustClass.NEUTRAL: (200, 200, 200),  # in flight, nothing proven
    TrustClass.REFUSED: (255, 70, 70),  # red
}


def cue_colour(trust: TrustClass) -> tuple[int, int, int]:
    """The one colour this trust class may be drawn in.

    Not a parameter anywhere upstream: a caller that could pass a colour could
    pass a stronger one than the node earned, which is the same failure
    `trust_for()` exists to prevent one level up.
    """

    if not isinstance(trust, TrustClass):
        raise CueLayoutError("a cue colour needs a TrustClass")
    try:
        colour = TRUST_COLOURS[trust]
    except KeyError:  # pragma: no cover - closed enum, kept to fail closed
        raise CueLayoutError(f"trust class {trust.value!r} has no cue colour") from None
    if colour == COLORKEY_RGB:  # pragma: no cover - guarded by test
        raise CueLayoutError("a cue colour may not be the overlay colorkey")
    return colour


#: The arrow-cursor outline, tip first, in glyph units. The tip is the
#: ORIGIN — every other point is an offset from it — so placing the glyph is
#: placing the tip, and no arithmetic stands between "where we point" and
#: "where we click".
POINTER_GLYPH: tuple[tuple[int, int], ...] = (
    (0, 0),
    (0, 16),
    (4, 12),
    (7, 19),
    (10, 18),
    (7, 11),
    (12, 11),
)


#: The hint ring "breathes" to draw the eye to the control (HeyClicky's
#: pulsing halo), without a timer: the live loop already repaints ~10x/s, so a
#: time-based radius delta animates for free. Pure and bounded for the test.
PULSE_PERIOD_S = 1.2
PULSE_AMPLITUDE_PX = 6


def pulse_delta(
    t: float, *, period: float = PULSE_PERIOD_S, amplitude: int = PULSE_AMPLITUDE_PX
) -> int:
    """Extra ring radius at time ``t``: 0 at the cycle start, ``amplitude`` at
    the half cycle, back to 0 -- a smooth breathe. Always in [0, amplitude], so
    the ring never shrinks below its base or wanders onto a neighbour."""

    import math

    if period <= 0:
        return 0
    return round(amplitude * (1 - math.cos(2 * math.pi * (t % period) / period)) / 2)


#: The Teach ring flies from where the user's cursor is to the control
#: (HeyClicky's spring flight) instead of appearing there. Short enough to
#: never delay a step; only a move this far is worth a flight.
FLY_S = 0.45
FLY_MIN_PX = 40
# No overshoot: the ring never passes the observed control (rule 3, strict
# reading from the 2026-11-11 tier-1 review), it only eases into it.
_OVERSHOOT = 0.0


def fly_position(
    start: tuple[int, int],
    end: tuple[int, int],
    elapsed: float,
    *,
    duration: float = FLY_S,
) -> tuple[int, int]:
    """Where the ring is ``elapsed`` seconds into a flight. Cubic ease-out,
    never past the control; exactly ``end`` (the observed control) from
    ``duration`` on, so a resting ring is always on the real control."""

    if duration <= 0 or elapsed >= duration:
        return end
    t = max(elapsed, 0.0) / duration - 1
    k = 1 + (_OVERSHOOT + 1) * t**3 + _OVERSHOOT * t**2
    return (
        round(start[0] + (end[0] - start[0]) * k),
        round(start[1] + (end[1] - start[1]) * k),
    )


def pointer_polygon(x: int, y: int, *, scale: int = 1) -> tuple[tuple[int, int], ...]:
    """The glyph outline with its tip at ``(x, y)``."""

    for label, value in (("x", x), ("y", y)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise CueLayoutError(f"{label} must be an integer")
    if isinstance(scale, bool) or not isinstance(scale, int) or scale <= 0:
        raise CueLayoutError("scale must be a positive integer")
    return tuple((x + dx * scale, y + dy * scale) for dx, dy in POINTER_GLYPH)


@dataclass(frozen=True)
class LabelMetrics:
    """How big the text will be, measured by whoever owns the font.

    Passed in rather than assumed. This module cannot measure a string
    without a device context, and a guessed character width is how a label
    that "fits" clips its last word on the machine that matters.
    """

    char_width: int
    line_height: int
    padding: int = 6
    gap: int = 14

    def __post_init__(self) -> None:
        for label in ("char_width", "line_height", "padding", "gap"):
            value = getattr(self, label)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CueLayoutError(f"{label} must be a non-negative integer")
        for label in ("char_width", "line_height"):
            if getattr(self, label) == 0:
                raise CueLayoutError(f"{label} must be positive")


def label_box(
    pointer: tuple[int, int],
    text: str,
    metrics: LabelMetrics,
    *,
    bounds: tuple[int, int, int, int],
    avoid: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int, int]:
    """Where the callout goes, as (left, top, right, bottom) screen pixels.

    Below-right of the tip by default, which is where a real cursor's tooltip
    sits and therefore where the eye already looks. It flips horizontally,
    then vertically, to stay inside ``bounds``, and flips again to stop
    covering ``avoid`` — the control the cue is pointing at. A label over its
    own target is worse than no label: it names something it has hidden.

    If no placement satisfies both, the label is clamped into ``bounds`` and
    overlap is accepted. Refusing outright would drop the text entirely, and a
    partly-covered button the user can still see beside the words is the
    better failure.
    """

    if not isinstance(text, str) or not text.strip():
        raise CueLayoutError("a cue label needs text")
    if not isinstance(metrics, LabelMetrics):
        raise CueLayoutError("a cue label needs LabelMetrics")
    px, py = _point(pointer, "pointer")
    left_bound, top_bound, right_bound, bottom_bound = _rect(bounds, "bounds")
    target = None if avoid is None else _rect(avoid, "avoid")

    width = len(text) * metrics.char_width + metrics.padding * 2
    height = metrics.line_height + metrics.padding * 2

    # Two tiers. Near the tip first, because that is where the eye already
    # is. Then clear of the whole control, because the tip sits at the
    # control's CENTRE -- so for any control wider than twice the gap, every
    # tip-anchored placement lands on top of the thing being named. That is
    # the common case, not the edge case: a ribbon button is 120px wide and
    # the gap is 14.
    candidates = [
        (px + metrics.gap, py + metrics.gap),  # below-right, preferred
        (px - metrics.gap - width, py + metrics.gap),  # below-left
        (px + metrics.gap, py - metrics.gap - height),  # above-right
        (px - metrics.gap - width, py - metrics.gap - height),  # above-left
    ]
    if target is not None:
        t_left, t_top, t_right, t_bottom = target
        candidates += [
            (t_right + metrics.gap, t_top),  # beside it, top-aligned
            (t_left - metrics.gap - width, t_top),
            (t_left, t_bottom + metrics.gap),  # under it, left-aligned
            (t_left, t_top - metrics.gap - height),
        ]

    fallback = None
    for left, top in candidates:
        box = (left, top, left + width, top + height)
        inside = (
            left >= left_bound
            and top >= top_bound
            and box[2] <= right_bound
            and box[3] <= bottom_bound
        )
        if not inside:
            continue
        if fallback is None:
            fallback = box
        if target is None or not _overlaps(box, target):
            return box

    if fallback is not None:
        # Every in-bounds placement covers the target. Take the first one:
        # clamping would move it somewhere the eye is not looking, for a
        # collision it cannot avoid anyway.
        return fallback

    # Floor last, so a label WIDER than the bounds anchors at the left edge
    # and overflows right rather than starting off-screen to the left. The
    # start of "Insert > New Slide Layout" is the part worth keeping.
    left = max(left_bound, min(px + metrics.gap, right_bound - width))
    top = max(top_bound, min(py + metrics.gap, bottom_bound - height))
    return (left, top, left + width, top + height)


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    """Do two (left, top, right, bottom) rectangles share any area?

    Touching edges do not count: a label whose left edge sits exactly on the
    button's right edge covers no pixel of it.
    """

    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _point(value: object, label: str) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise CueLayoutError(f"{label} is two integers")
    for part in value:
        if isinstance(part, bool) or not isinstance(part, int):
            raise CueLayoutError(f"{label} coordinates must be integers")
    return (value[0], value[1])


def _rect(value: object, label: str) -> tuple[int, int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise CueLayoutError(f"{label} is four integers")
    for part in value:
        if isinstance(part, bool) or not isinstance(part, int):
            raise CueLayoutError(f"{label} coordinates must be integers")
    left, top, right, bottom = value
    if right <= left or bottom <= top:
        raise CueLayoutError(f"{label} has no positive area")
    return (left, top, right, bottom)


@dataclass(frozen=True)
class CueScene:
    """One painted moment: everything `window.py` needs and nothing else.

    Frozen and made of primitives, for the same reason `Element` is: it
    crosses from the worker that decided the cue to the UI thread that paints
    it, and a mutable scene could be edited between the two.
    """

    pointer: tuple[int, int] | None
    target: tuple[int, int, int, int] | None
    label: str
    trust: TrustClass
    final: bool
    #: Where the label plate goes, already laid out by `label_box`. Carried
    #: rather than computed at paint time: placement needs the screen bounds
    #: and the measured font, and WM_PAINT is the one place that must stay
    #: cheap. None means the caller wants the cue without its callout.
    label_rect: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        if self.pointer is not None:
            _point(self.pointer, "pointer")
        if self.target is not None:
            _rect(self.target, "target")
        if self.label_rect is not None:
            _rect(self.label_rect, "label_rect")
        if self.pointer is None and self.target is None:
            raise CueLayoutError("a cue with neither pointer nor target shows nothing")
        if not isinstance(self.label, str) or not self.label.strip():
            raise CueLayoutError("a cue label needs text")
        if not isinstance(self.trust, TrustClass):
            raise CueLayoutError("a cue needs a TrustClass")
        if not isinstance(self.final, bool):
            raise CueLayoutError("final must be a boolean")

    @property
    def colour(self) -> tuple[int, int, int]:
        return cue_colour(self.trust)


__all__ = [
    "COLORKEY_RGB",
    "CueLayoutError",
    "CueScene",
    "LabelMetrics",
    "POINTER_GLYPH",
    "PULSE_AMPLITUDE_PX",
    "PULSE_PERIOD_S",
    "TRUST_COLOURS",
    "FLY_MIN_PX",
    "FLY_S",
    "cue_colour",
    "fly_position",
    "label_box",
    "pointer_polygon",
    "pulse_delta",
]
