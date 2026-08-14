"""Screen capture for tier 2, in the one coordinate space (D010/D012).

Captures go through `dpi.capture_region()`, never `mss.monitors[1]` and never
from a separate process: a process with different DPI awareness captures a
region that does not correspond to the desktop, producing convincing and
meaningless images. That mistake has cost this project real debugging time
twice.
"""

from __future__ import annotations

import numpy as np
import win32gui

from ghostcursor.overlay import dpi  # noqa: F401  declares DPI awareness at import
from ghostcursor.perception.uia import windows_matching

#: Fraction of pixels that must change before OCR is worth re-running. From
#: the mss doc's frames_differ pattern. Cheap capture plus diff, expensive
#: analysis only on change, is what keeps a real-time guide affordable.
FRAME_DIFF_THRESHOLD = 0.02

#: Per-pixel channel-sum delta counted as "this pixel changed". Below this is
#: anti-aliasing and compression shimmer.
_PIXEL_DELTA = 30


def capture_window(title_re: str):
    """`(frame_bgr, rect)` for the first window matching, or None if absent."""
    hwnds = windows_matching(title_re)
    if not hwnds:
        return None

    left, top, right, bottom = win32gui.GetWindowRect(hwnds[0])
    if right <= left or bottom <= top:
        return None

    import mss

    with mss.mss() as sct:
        raw = sct.grab(
            {"left": left, "top": top, "width": right - left, "height": bottom - top}
        )
    return np.array(raw)[:, :, :3], (left, top, right, bottom)


def frames_differ(previous, current, threshold: float = FRAME_DIFF_THRESHOLD) -> bool:
    """True if enough pixels changed to be worth re-reading the screen."""
    if previous is None or previous.shape != current.shape:
        return True

    delta = np.abs(previous.astype(np.int16) - current.astype(np.int16))
    changed = np.count_nonzero(delta.sum(axis=2) > _PIXEL_DELTA)
    return changed / delta[:, :, 0].size > threshold
