"""Adapts the loop's Renderer protocol onto the Win32 overlay.

Kept separate from the loop so state transitions can be tested with no UI,
and so the overlay stays a pure rendering surface with no knowledge of
recipes or verification.
"""

from __future__ import annotations

from ghostcursor.overlay import window as overlay_window
from ghostcursor.reasoning.grounding import GroundedTarget


class OverlayRenderer:
    """Draws the hint, at the confidence it was told to draw it with.

    `freshness_source` exists because the caller that KNOWS the confidence
    (run.py, which owns the staleness ladder and the grounding source) is not
    the caller that drives the renderer (the loop, which must stay ignorant of
    both). Without it the first paint of every hint used `set_hint`'s default,
    and that default is FRESH — so an OCR-grounded target was drawn once in
    the confirmed-control colour before being corrected later in the same
    tick. "Usually too fast to notice" is not a safety argument.
    """

    def __init__(
        self, hwnd: int, overlay=overlay_window, freshness_source=None
    ) -> None:
        self.hwnd = hwnd
        self.overlay = overlay
        self.freshness_source = freshness_source
        self.last_instruction: str | None = None

    def show(
        self, grounded: GroundedTarget, instruction_text: str, freshness=None
    ) -> None:
        from ghostcursor.reasoning.staleness import Freshness

        left, top, right, bottom = grounded.bbox
        if freshness is None and self.freshness_source is not None:
            freshness = self.freshness_source()

        # Coordinates are computed here, at render time, from the live
        # rectangle — never read from the recipe.
        centre = ((left + right) // 2, (top + bottom) // 2)
        if freshness is Freshness.HIDDEN:
            # HIDDEN means draw nothing, and it must never reach set_hint:
            # the painter distinguishes only FRESH from everything-else, so
            # handing it down would draw a DIMMED ring instead of no ring.
            # `last_instruction` is still recorded, so the hint can come
            # straight back when perception recovers without re-running the
            # step — the same deliberate divergence run.py relies on.
            self.overlay.clear_hint(self.hwnd)
        elif freshness is None:
            # Unspecified stays unspecified: callers that predate the source
            # axis keep their exact previous call, rather than being handed a
            # confidence nobody chose.
            self.overlay.set_hint(self.hwnd, *centre)
        else:
            self.overlay.set_hint(self.hwnd, *centre, freshness=freshness)
        self.last_instruction = instruction_text

    def clear(self) -> None:
        self.overlay.clear_hint(self.hwnd)
        self.last_instruction = None
