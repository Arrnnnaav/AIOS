"""Patience before escalating to tier 2, keyed by window handle.

A cold Chromium application populates its accessibility tree over a second or
so. `run.py` requests tier 2 the moment grounding fails, so a cold start
escalates straight to OCR: wasted reads, and -- worse -- a chance of drawing an
amber INFERRED ring off a pixel match when a cyan ring off a confirmed control
was half a second away. The ring colour is how the user calibrates trust (D006).

This does NOT try to detect readiness. Every attempt to do so was ruled out by
measurement: 'furniture but no content' is transient in VS Code and TERMINAL in
Acrobat, and the element count is non-monotonic even in steady state, so
comparing consecutive observations is unsound. The system already has a perfect
readiness signal -- grounding succeeded -- and what was missing was patience.

Keyed by HWND, not by the title regex. Discord's cold start puts up a window
titled 'Discord Updater' which fully matches windows_matching('.*Discord.*') and
lives about five seconds before the real window exists, as a separate handle. A
title-keyed warm-up spends its whole budget there and leaves the real window
with none.

Runs on the UI THREAD -- unlike perception/tier2.py, which is worker-side.
"""

import time
from typing import Callable

#: Swept, not guessed. VS Code grounded its targets 0.57s and 0.39s after the
#: window appeared; Discord grounded all six 0.92s after its real window. No
#: element was ever observed to ground slowly-but-eventually, so a larger budget
#: buys nothing -- it cannot rescue an element that is simply absent. Every
#: second here is a second a genuinely UIA-blind app (Acrobat) waits before OCR
#: engages, on every cold start, forever.
DEFAULT_WARMUP_BUDGET_S = 2.0


class WarmUp:
    """Per-window-handle grace period before tier 2 may be requested."""

    def __init__(
        self,
        budget_s: float = DEFAULT_WARMUP_BUDGET_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._budget_s = budget_s
        self._clock = clock
        #: hwnd -> the time its warm-up opened.
        self._opened: dict[int, float] = {}
        #: Handles that have grounded at least once. Their tree is proven, so
        #: they never need the allowance again -- a later step that fails to
        #: ground escalates immediately, as it does today.
        self._closed: set[int] = set()
        #: How many distinct handles have opened a warm-up. DIAGNOSTIC ONLY --
        #: never read by policy, exactly like the worker heartbeat under D024.
        #: The one unmeasured risk in this design is an application that
        #: destroys and recreates its top-level window faster than the budget,
        #: which would re-open warm-up forever and suppress tier 2 for good. It
        #: is invisible from the outside -- tier 2 simply never fires -- so this
        #: counter is what makes it legible. Every measured run saw 2 (Discord:
        #: its updater, then the app); dozens means window churn, and that is
        #: the FIRST thing to check if tier 2 ever seems not to fire.
        self.opens = 0

    def allows_tier2(self, hwnd: int) -> bool:
        """True when tier 2 may be requested for `hwnd` right now.

        Opens the warm-up as a side effect the first time a handle is seen,
        which is the only moment 'first observation of this window' is
        observable from here.
        """
        if hwnd <= 0:
            return True
        if hwnd in self._closed:
            return True
        opened = self._opened.get(hwnd)
        if opened is None:
            self._opened[hwnd] = self._clock()
            self.opens += 1
            return False
        return (self._clock() - opened) >= self._budget_s

    def note_grounded(self, hwnd: int) -> None:
        """Close `hwnd`'s warm-up permanently: its tree is demonstrably usable."""
        if hwnd > 0:
            self._closed.add(hwnd)
            self._opened.pop(hwnd, None)
