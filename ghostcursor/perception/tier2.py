"""Tier 2's cadence: when to read the screen, and when to stop.

Runs on the perception worker thread, never the UI thread (D021). Blocking
here costs a later observation, which the staleness ladder already handles by
dimming; blocking the UI thread would cost the user their escape hatch.
"""

from __future__ import annotations

import time
from typing import Callable

from ghostcursor.perception.capture import frames_differ
from ghostcursor.perception.ocr import OcrRead, reassemble
from ghostcursor.perception.uia import Element

#: Floor between OCR runs. Without it, "re-run only when the region changed"
#: degrades to "re-run every tick" against an animating region -- a loading
#: spinner in frame, a window being resized -- and the cheapest-first tier
#: quietly becomes unconditional OCR.
DEFAULT_MIN_INTERVAL_S = 1.0

#: Ceiling of CONSECUTIVE FRUITLESS reads per step. Same reason, for a region
#: that never stops changing. Reads that produce a groundable target reset it
#: (`grounded()`): the budget is there to stop unproductive re-reading, and a
#: churning page that keeps re-grounding correctly is the tier doing its job.
DEFAULT_MAX_RUNS_PER_STEP = 20


def _to_elements(reads: list[OcrRead], origin: tuple[int, int]) -> list[Element]:
    """OCR reads as Elements in SCREEN coordinates.

    Reads are relative to the captured window; the hint is drawn in screen
    space, so the window origin is added here rather than at the call site
    where it would be easy to forget (D010: one coordinate space).
    """
    left, top = origin
    return [
        Element(
            name=read.text,
            control_type="",
            automation_id="",
            bbox=(
                read.bbox[0] + left,
                read.bbox[1] + top,
                read.bbox[2] + left,
                read.bbox[3] + top,
            ),
            path=(),
            source="ocr",
        )
        for read in reads
    ]


def _default_ocr():
    from ghostcursor.perception.ocr import WindowsOcr

    return WindowsOcr()


def _default_capture(title_re: str):
    from ghostcursor.perception.capture import capture_window

    return capture_window(title_re)


#: Seams, so a test can drive tier 2 without a real screen or a real engine.
_DEFAULT_OCR_FACTORY = _default_ocr
_DEFAULT_CAPTURE = _default_capture


def build_controller(clock) -> "Tier2Controller | None":
    """A controller, or None if this machine cannot OCR at all.

    Returning None rather than raising is deliberate: a machine with no OCR
    language pack must still run Ghost Cursor on UIA alone (spec §10).
    """
    from ghostcursor.perception.ocr import ocr_available

    if not ocr_available():
        return None
    try:
        return Tier2Controller(
            ocr=_DEFAULT_OCR_FACTORY(), capture=_DEFAULT_CAPTURE, clock=clock
        )
    except Exception:
        return None


class _StepState:
    __slots__ = ("runs", "engaged", "last_run_at", "last_frame", "elements")

    def __init__(self) -> None:
        #: CONSECUTIVE reads that did not yield a groundable target. Reset by
        #: `grounded()`, so the ceiling bounds fruitless work rather than
        #: total work.
        self.runs = 0
        #: Whether OCR has read for this step at all, ever. Survives the reset
        #: above, because it answers a different question: not "should we keep
        #: reading" but "if this step ends up ungroundable, was reading the
        #: screen part of why".
        self.engaged = False
        self.last_run_at: float | None = None
        self.last_frame = None
        self.elements: list[Element] = []


class Tier2Controller:
    def __init__(
        self,
        ocr,
        capture: Callable,
        clock: Callable[[], float] = time.monotonic,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        max_runs_per_step: int = DEFAULT_MAX_RUNS_PER_STEP,
    ) -> None:
        self.ocr = ocr
        self.capture = capture
        self.clock = clock
        self.min_interval_s = min_interval_s
        self.max_runs_per_step = max_runs_per_step
        self._steps: dict[int, _StepState] = {}

    def _state(self, step_index: int) -> _StepState:
        return self._steps.setdefault(step_index, _StepState())

    def exhausted(self, step_index: int) -> bool:
        """True once this step has spent its budget of FRUITLESS reads.

        Terminal for the step in the sense spec §4 means: reading stops and
        the step becomes ungroundable, which feeds the existing grounding
        grace. It does NOT end the tour on the spot -- until the grace
        expires the last observation keeps ageing through the staleness
        ladder, so the display degrades honestly instead of vanishing.

        The rejected alternative -- let the last OCR result stand and age
        forever -- leaves the ring pointing at a coordinate the system can no
        longer confirm AND makes the step incapable of ever failing.
        """
        state = self._steps.get(step_index)
        return state is not None and state.runs >= self.max_runs_per_step

    def engaged(self, step_index: int) -> bool:
        """True if OCR has read the screen for this step at all.

        What the failure reason keys off. Exhaustion cannot carry that job:
        the grace is 10s and the read floor 1.0s, so an unreadable screen
        gives up long before 20 reads, and a message keyed on exhaustion
        appeared only when reading intermittently worked -- exactly inverted.
        """
        state = self._steps.get(step_index)
        return state is not None and state.engaged

    def grounded(self, step_index: int) -> None:
        """Report that the last read produced a usable target.

        A productive read does not spend the budget. The caps exist to stop a
        never-settling region turning the cheapest-first tier into
        unconditional OCR (D028); a step that keeps RE-GROUNDING off OCR is
        the tier working, and counting those reads killed tours whose amber
        ring was sitting correctly on the target the whole time.
        """
        state = self._steps.get(step_index)
        if state is not None:
            state.runs = 0

    def elements_for(self, step_index: int, title_re: str) -> list[Element]:
        state = self._state(step_index)
        if self.exhausted(step_index):
            return []

        now = self.clock()
        if (
            state.last_run_at is not None
            and now - state.last_run_at < self.min_interval_s
        ):
            return state.elements

        captured = self.capture(title_re)
        if captured is None:
            return state.elements
        frame, rect = captured

        if not frames_differ(state.last_frame, frame):
            state.last_frame = frame
            return state.elements

        state.runs += 1
        state.engaged = True
        state.last_run_at = now
        state.last_frame = frame
        state.elements = _to_elements(
            reassemble(self.ocr.read(frame)), (rect[0], rect[1])
        )
        return state.elements
