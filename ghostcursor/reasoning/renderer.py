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

from ghostcursor.overlay import window as overlay_window
from ghostcursor.reasoning.grounding import GroundedTarget
from ghostcursor.reasoning.staleness import Freshness


class OverlayRenderer:
    """Draws the hint, at most once per tick, at one decided display state.

    `freshness_source` is the ONE mechanism for supplying that state, and it
    is a callable rather than an argument because of a split in who knows
    what: the caller that KNOWS the display state is run.py (it owns the
    staleness ladder and the grounding source), but the caller that DRIVES the
    renderer is the loop, which must stay ignorant of both. A second, explicit
    `show(freshness=...)` parameter was tried and deleted — nothing ever passed
    it, and two ways to decide what to draw is how the two-step render got
    here in the first place.

    Because there is exactly one write per tick, "decided before the paint"
    and "read at the paint" are the same instant: the clock does not advance
    within a tick, the grounding source is only ever changed by DECIDING
    (which does not paint), and the only mid-tick change to the ladder is
    `observed()`, which can only make the hint fresher. Reading the source at
    the single write point is therefore never MORE trusting than the truth.

    `freshness_source=None` means "this caller does not track provenance",
    which leaves `set_hint` on its own default. That is a test-only
    affordance: `test_no_production_renderer_is_built_without_provenance`
    asserts that nothing inside the shipped package constructs one that way.
    """

    def __init__(
        self, hwnd: int, overlay=overlay_window, freshness_source=None
    ) -> None:
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
        #: Where the hint currently sits, so a staleness-only redraw does not
        #: require the loop to show() again.
        self._centre: tuple[int, int] | None = None

    def show(self, grounded: GroundedTarget, instruction_text: str) -> None:
        left, top, right, bottom = grounded.bbox
        # Coordinates are computed here, at render time, from the live
        # rectangle — never read from the recipe.
        self._centre = ((left + right) // 2, (top + bottom) // 2)
        self.last_instruction = instruction_text
        self._paint()

    def clear(self) -> None:
        self.last_instruction = None
        self._centre = None
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
            self._freshness = (
                self.freshness_source() if self.freshness_source is not None else None
            )
            self._resolved = True
        return self._freshness

    def _paint(self) -> None:
        if self._centre is None:
            return
        self._written = True
        freshness = self._resolve()
        if freshness is Freshness.HIDDEN:
            # HIDDEN means draw nothing, and it must never reach set_hint: the
            # painter distinguishes only FRESH from everything-else, so handing
            # it down would draw a DIMMED ring instead of no ring.
            #
            # `last_instruction` and `_centre` are deliberately kept, so the
            # hint can come straight back when perception recovers without
            # re-running the step. Do not "fix" this by routing it through
            # clear().
            self.overlay.clear_hint(self.hwnd)
        elif freshness is None:
            # No provenance tracked by this caller. Call set_hint exactly as
            # it was called before the source axis existed, rather than
            # inventing a confidence nobody chose.
            self.overlay.set_hint(self.hwnd, *self._centre)
        else:
            self.overlay.set_hint(self.hwnd, *self._centre, freshness=freshness)
