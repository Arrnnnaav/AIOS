"""Adapts the loop's Renderer protocol onto the Win32 overlay.

Kept separate from the loop so state transitions can be tested with no UI,
and so the overlay stays a pure rendering surface with no knowledge of
recipes or verification.
"""

from __future__ import annotations

from ghostcursor.overlay import window as overlay_window
from ghostcursor.reasoning.grounding import GroundedTarget


class OverlayRenderer:
    def __init__(self, hwnd: int, overlay=overlay_window) -> None:
        self.hwnd = hwnd
        self.overlay = overlay
        self.last_instruction: str | None = None

    def show(self, grounded: GroundedTarget, instruction_text: str) -> None:
        left, top, right, bottom = grounded.bbox
        # Coordinates are computed here, at render time, from the live
        # rectangle — never read from the recipe.
        self.overlay.set_hint(self.hwnd, (left + right) // 2, (top + bottom) // 2)
        self.last_instruction = instruction_text

    def clear(self) -> None:
        self.overlay.clear_hint(self.hwnd)
        self.last_instruction = None
