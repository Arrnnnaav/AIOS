"""Adapts the loop's Renderer protocol onto the Win32 overlay.

Kept separate from the loop so state transitions can be tested with no UI,
and so the overlay stays a pure rendering surface with no knowledge of
recipes or verification.

This is also the SINGLE write path to the hint (D027). At most one overlay
write happens per tick, at one display state, so there is no provisional paint
for a `WM_PAINT` to catch before its correction lands. That matters more than
it sounds: `overlay.set_hint` ends in `UpdateWindow`, which paints
SYNCHRONOUSLY, so a second corrective write was never a narrow race — it was a
second frame that definitely reached the screen.
"""

from __future__ import annotations

from dataclasses import dataclass

from ghostcursor.overlay import window as overlay_window
from ghostcursor.reasoning.grounding import GroundedTarget
from ghostcursor.reasoning.staleness import (
    CONFIRMED_SOURCE,
    Freshness,
    display_freshness,
)


@dataclass(frozen=True)
class _Hint:
    """A coordinate and the provenance it was created with, as ONE value.

    Frozen, and replaced wholesale rather than mutated, because the bug this
    exists to prevent is precisely a centre and a provenance that can be
    updated independently: repainting yesterday's coordinate at today's
    confidence is how a pixel guess ends up wearing the confirmed-control
    ring.
    """

    centre: tuple[int, int]
    source: str


class OverlayRenderer:
    """Draws the hint, at most once per tick, at one decided display state.

    `freshness_source` is the ONE mechanism for supplying the age half of that
    state, and it is a callable rather than an argument because of a split in
    who knows what: the caller that KNOWS how old the last observation is is
    run.py (it owns the staleness ladder), but the caller that DRIVES the
    renderer is the loop, which must stay ignorant of it. A second, explicit
    `show(freshness=...)` parameter was tried and deleted — nothing ever passed
    it, and two ways to decide what to draw is how the two-step render got
    here in the first place.

    `freshness_source` supplies the TIME axis only. The SOURCE axis belongs to
    the hint: `show()` binds the resolved provenance to the centre as one
    value, and every later repaint — including `settle()`'s — clamps against
    THAT, never against whatever the wider system's grounding source says now.

    This is the correction to an earlier claim in this file, which said the
    grounding source "is only ever changed by DECIDING, which does not paint".
    DECIDING's tick DOES paint: `GuidedTour.tick()` ends in `settle()`, and on
    a tick where nothing called `show()` that repaints the existing centre. So
    a step whose source flipped ocr -> uia in DECIDING repainted the OLD, OCR
    centre in FRESH cyan a full tick (~250ms, synchronously) before
    RENDERING_HINT moved the ring to the UIA rect. One write per tick was
    never the property that made this safe — a hint carrying its own
    provenance is.

    `freshness_source` is REQUIRED, and a source that answers None resolves to
    INFERRED. Between them there is no way to construct a renderer that draws
    a hint as a confirmed control without something explicitly saying it is
    one. That used to be a permissive default guarded by a package scan; a
    scan is a tripwire, not a guarantee — it passes the day someone adds a
    construction it does not match, and "unknown provenance resolves to the
    most trusting value" is the exact shape this file exists to remove.
    """

    def __init__(self, hwnd: int, *, freshness_source, overlay=overlay_window) -> None:
        self.hwnd = hwnd
        self.overlay = overlay
        self.freshness_source = freshness_source
        self.last_instruction: str | None = None
        #: Whether this tick has already written to the overlay. Reset by
        #: settle(), which is what marks the tick boundary.
        self._written = False
        #: This tick's display state, and whether it has been asked for yet.
        #: Resolved AT MOST ONCE per tick and cached — `ladder.freshness()` is
        #: a query with side effects (it arms D023's recovery debounce), so
        #: how many times it is called per tick is itself behaviour.
        self._freshness = None
        self._resolved = False
        #: Where the hint currently sits AND what produced it, so a
        #: staleness-only redraw does not require the loop to show() again and
        #: cannot repaint the old coordinate at a newer step's confidence.
        self._hint: _Hint | None = None

    def show(self, grounded: GroundedTarget, instruction_text: str) -> None:
        left, top, right, bottom = grounded.bbox
        # Coordinates are computed here, at render time, from the live
        # rectangle — never read from the recipe. The provenance is bound in
        # the same statement, from the same target: there is no window in
        # which the centre is this hint's and the source is another's.
        self._hint = _Hint(
            centre=((left + right) // 2, (top + bottom) // 2),
            source=grounded.source,
        )
        self.last_instruction = instruction_text
        self._paint()

    def clear(self) -> None:
        self.last_instruction = None
        self._hint = None
        self.overlay.clear_hint(self.hwnd)
        self._written = True

    def settle(self) -> None:
        """End the tick: emit its display state if the loop did not, then
        reopen for the next one.

        The loop calls `show()` only when it changes WHAT is displayed, but
        the display state also changes on its own as observations age — that
        is the entire point of the staleness ladder, and without this the
        ladder would be dead code. Emitting here rather than from a second
        `set_hint` in the tick loop is what keeps the count at one: this is a
        no-op on any tick that already wrote, so the caller never has to know
        which case it is in.
        """
        # Resolved even on a tick that already wrote, and even with no hint on
        # screen: exactly one resolution per tick, always. The ladder query is
        # stateful, so skipping it on quiet ticks would quietly change when
        # the recovery debounce arms.
        freshness = self._resolve()
        if not self._written:
            if freshness is Freshness.HIDDEN:
                # Idempotent, and issued even when nothing is showing. The
                # display state for this tick is "no hint", and saying so
                # costs one no-op write while making the overlay's state a
                # function of the tick rather than of history.
                self.overlay.clear_hint(self.hwnd)
            elif self.last_instruction is not None:
                self._paint()
        self._written = False
        self._resolved = False

    def _resolve(self):
        if not self._resolved:
            state = self.freshness_source()
            # A source that cannot answer is not evidence of confidence.
            # INFERRED is the fail-safe floor, matching display_freshness's
            # treatment of an unrecognised source: shown slightly cautious
            # costs nothing, shown fully trusted violates the safety rule.
            self._freshness = Freshness.INFERRED if state is None else state
            self._resolved = True
        return self._freshness

    def _paint(self) -> None:
        hint = self._hint
        if hint is None:
            return
        self._written = True
        freshness = self._resolve()
        # Fold in the hint's OWN provenance, not the system's current one.
        # Only ever applied for an unconfirmed source, so it can only LOWER
        # trust: `display_freshness` returns INFERRED for every source but
        # "uia", and passes HIDDEN and DIMMED straight through. That is what
        # makes a repaint reproduce the state its hint was created with
        # instead of borrowing a later step's confidence.
        if hint.source != CONFIRMED_SOURCE:
            freshness = display_freshness(freshness, hint.source)
        if freshness is Freshness.HIDDEN:
            # HIDDEN means draw nothing, and it must never reach set_hint: the
            # painter distinguishes only FRESH from everything-else, so handing
            # it down would draw a DIMMED ring instead of no ring.
            #
            # `last_instruction` and `_hint` are deliberately kept, so the
            # hint can come straight back when perception recovers without
            # re-running the step. Do not "fix" this by routing it through
            # clear().
            self.overlay.clear_hint(self.hwnd)
        else:
            # Always explicit. There is deliberately no branch that calls
            # set_hint without a freshness: that path would land on set_hint's
            # own default, which is FRESH.
            self.overlay.set_hint(self.hwnd, *hint.centre, freshness=freshness)
