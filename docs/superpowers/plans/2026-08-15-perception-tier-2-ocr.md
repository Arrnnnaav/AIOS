# Perception Tier 2 — OCR Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When UIA cannot locate the element a step names, read the screen with OCR and ground against the text — showing the user a visibly distinct hint so a pixel-read guess is never mistaken for a confirmed control.

**Architecture:** OCR runs on the existing perception worker thread, triggered per-step by grounding failure (never by an empty walk). Reads join the same `Element` list carrying `source="ocr"`, reach grounding only through a new rung 4 with a measured fuzzy floor of 95, and render as a third overlay state `INFERRED`. Nothing OCR produces is ever persisted.

**Tech Stack:** Python 3.12, `winsdk` (`Windows.Media.Ocr`), `mss`, `numpy`, `rapidfuzz`, `pywin32`.

**Spec:** `docs/superpowers/specs/2026-08-15-perception-tier-2-ocr-design.md`
**Measurements:** `docs/superpowers/specs/2026-08-15-ocr-tier-spike-findings.md`

## Global Constraints

- Python: `/c/Users/user/AppData/Local/Programs/Python/Python312/python` (no venv). Always run with `-B`.
- All **168 fast** + **13 hung-target** pytest tests keep passing UNCHANGED. Editing an existing test means the contract was not preserved — stop and reconsider.
- Fast suite: `python -B -m pytest tests/ -q --ignore=tests/test_hung_window.py --ignore=tests/test_perception_service_hung.py --ignore=tests/test_run_threaded.py` (~16 s).
- **D025: never run two pytest sessions concurrently, and never run the hung-window tests alongside anything else.** A hung window taxes UIA enumeration 16× process-wide (measured 6.28 s vs 100.13 s). Run everything FOREGROUND, sequentially.
- **D006:** never act for the user. No `SendInput`, `SetCursorPos`, `keybd_event`, `mouse_event`.
- **D009:** all drawing inside `WM_PAINT`. Never draw from the polling loop via `GetDC`.
- **D010:** import `ghostcursor.overlay.dpi` before any window is created; capture via `dpi.capture_region()`, never `mss.monitors[1]`, never from a separate process.
- **D017:** no network, no telemetry.
- **D018:** mutation-verify the safety-critical properties. **Commit before mutating** — `git checkout --` on uncommitted work has destroyed work in this project twice.
- **D026:** stateful/time-based behaviour gets an ordered-sequence test on an injected clock, never end-state assertions.
- Rung-4 floor is **95**. Frame diff **2%**. Min OCR interval **1.0 s**. Max OCR runs per step **20**.
- Test fixtures use the spike's REAL measured reads, never invented strings.

---

## File Structure

| File | Responsibility |
|---|---|
| `ghostcursor/perception/ocr.py` (create) | `OcrRead`, `WindowsOcr` engine wrapper, availability probe, multi-line reassembly |
| `ghostcursor/perception/capture.py` (create) | DPI-correct window capture + frame differencing |
| `ghostcursor/perception/tier2.py` (create) | `Tier2Controller` — per-step stickiness, both caps, cap-exhaustion |
| `ghostcursor/perception/uia.py` (modify) | `Element` gains `source: str = "uia"` LAST |
| `ghostcursor/reasoning/grounding.py` (modify) | rung 3 filters to UIA; rung 4 fuzzy OCR-only |
| `ghostcursor/reasoning/staleness.py` (modify) | `Freshness.INFERRED` + precedence |
| `ghostcursor/overlay/window.py` (modify) | `INFERRED_RING_COLOR` |
| `ghostcursor/run.py` (modify) | wiring, cap-exhaustion reason |

---

### Task 1: HUMAN HAND-OFF GATE — OCR language pack on a clean machine

**This task is not implementable. It is a real gate, and nothing after it may start until it passes.**

The spike verified `Windows.Media.Ocr` works on the development machine, where `en-GB` and `en-US` recognizers were already present. That is evidence about **one machine**. Installing a missing OCR language pack requires administrator rights, and "end users need admin to use a fallback tier" is a distribution blocker independent of accuracy — the one risk in this milestone that data already in hand does not resolve.

**Owner:** the human partner. Not the implementer, not the controller.

**Where:** a clean **non-development** Windows machine. A fresh Windows VM is sufficient. It must NOT be the development machine, and must not have had developer tooling or language packs added.

- [ ] **Step 1: Install only the binding, nothing else**

```
pip install winsdk
```

- [ ] **Step 2: Run the three checks verbatim**

```python
from winsdk.windows.globalization import Language
from winsdk.windows.media.ocr import OcrEngine

langs = list(OcrEngine.available_recognizer_languages)
print("CHECK 1 languages:", [l.language_tag for l in langs])

engine_profile = OcrEngine.try_create_from_user_profile_languages()
print("CHECK 2 from_user_profile:", engine_profile)

engine_en = OcrEngine.try_create_from_language(Language("en-US"))
print("CHECK 3 from_en_US:", engine_en)
```

- [ ] **Step 3: Record the result against these criteria**

| Check | PASS | FAIL |
|---|---|---|
| 1 | the printed list is **non-empty** | empty list `[]` |
| 2 | prints an object, **not** `None` | prints `None` |
| 3 | prints an object, **not** `None` | prints `None` |
| elevation | the script ran in a **normal, non-admin** shell and none of the above raised | any step required an administrator shell, or raised `PermissionError`/`OSError` |

"Looks fine" is not a result. Record the literal printed output.

- [ ] **Step 4: Act on the outcome**

- **All four PASS** → tier 2 is viable. Resume at Task 2.
- **Any FAIL** → **STOP. Do not begin Task 2.** Tier 2 halts and the engine decision reopens: the spec's §5 engine choice must be revisited (RapidOCR was measured at 39–66 s per full frame and is disqualified on latency, so a genuine alternative must be found or the milestone rescoped). Report which check failed and its literal output.

- [ ] **Step 5: Record the outcome in the plan's workspace ledger**

Write the literal output and the verdict. This gate's result is evidence, not a memory.

---

### Task 2: `Element.source` — provenance across the worker boundary

**Files:**
- Modify: `ghostcursor/perception/uia.py` (the `Element` dataclass)
- Test: `tests/test_element_source.py` (create)

**Interfaces:**
- Produces: `Element(name, control_type, automation_id, bbox, path=(), source="uia")` — `source` is `"uia"` or `"ocr"`, defaults to `"uia"`, and is the LAST field so every existing positional construction keeps working.

- [ ] **Step 1: Write the failing test**

```python
"""`source` is how the system knows a pixel guess from a confirmed control."""

from ghostcursor.perception.uia import Element


def _el(**kw):
    base = dict(name="Export", control_type="Button", automation_id="1001",
                bbox=(0, 0, 10, 10))
    base.update(kw)
    return Element(**base)


def test_source_defaults_to_uia():
    assert _el().source == "uia"


def test_positional_construction_still_works():
    """`source` must be LAST: every existing call site builds Elements
    positionally, and inserting a field earlier would silently shift them."""
    element = Element("Export", "Button", "1001", (0, 0, 10, 10))
    assert element.source == "uia"


def test_an_ocr_element_is_marked_as_such():
    assert _el(source="ocr", automation_id="", control_type="").source == "ocr"


def test_element_stays_frozen_and_hashable():
    """Only frozen dataclasses of primitives cross the worker boundary (D021)."""
    assert len({_el(), _el()}) == 1
    import dataclasses
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        _el().source = "ocr"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python -B -m pytest tests/test_element_source.py -v`
Expected: FAIL — `Element` has no attribute `source`.

- [ ] **Step 3: Add the field**

In `ghostcursor/perception/uia.py`, in the `Element` dataclass, after `path`:

```python
    #: Which perception tier produced this element. "uia" is a confirmed
    #: control; "ocr" is text read off pixels, which carries no AutomationId,
    #: no control_type, and no structural context. Everything downstream that
    #: decides how much to trust an element keys off THIS, not off which
    #: grounding rung matched it.
    #:
    #: Last field on purpose: existing call sites construct Element
    #: positionally, so an earlier insertion would silently shift them.
    source: str = field(default="uia")
```

- [ ] **Step 4: Run the test**

Run: `python -B -m pytest tests/test_element_source.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the fast suite unchanged**

Run: `python -B -m pytest tests/ -q --ignore=tests/test_hung_window.py --ignore=tests/test_perception_service_hung.py --ignore=tests/test_run_threaded.py`
Expected: 172 passed (168 existing + 4 new), zero existing tests edited.

- [ ] **Step 6: Commit**

```bash
git add ghostcursor/perception/uia.py tests/test_element_source.py
git commit -m "feat: mark elements with the perception tier that produced them"
```

---

### Task 3: OCR engine wrapper

**Files:**
- Create: `ghostcursor/perception/ocr.py`
- Test: `tests/test_ocr_engine.py`

**Interfaces:**
- Produces: `OcrRead(text: str, bbox: tuple[int,int,int,int])`; `WindowsOcr()` with `.read(frame_bgr) -> list[OcrRead]`; `ocr_available() -> bool`.
- Consumes: nothing from earlier tasks.

- [ ] **Step 1: Write the failing test**

```python
"""The engine wrapper. Availability must degrade, never explode: a machine
with no OCR language pack still runs Ghost Cursor on UIA alone."""

import numpy as np
import pytest

from ghostcursor.perception.ocr import OcrRead, WindowsOcr, ocr_available


def test_ocr_read_is_frozen_primitives_only():
    """It crosses the worker boundary, so D021 applies."""
    read = OcrRead(text="Export", bbox=(10, 20, 60, 40))
    assert read.text == "Export"
    assert read.bbox == (10, 20, 60, 40)
    assert len({read, OcrRead(text="Export", bbox=(10, 20, 60, 40))}) == 1


@pytest.mark.skipif(not ocr_available(), reason="no OCR language pack")
def test_reads_text_off_a_synthetic_frame():
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (400, 120), "white")
    ImageDraw.Draw(image).text((20, 40), "Export", fill="black")
    frame = np.array(image)[:, :, ::-1]  # RGB -> BGR, as mss produces

    reads = WindowsOcr().read(frame)

    assert any("export" in r.text.lower() for r in reads), (
        f"the engine read nothing resembling 'Export': {[r.text for r in reads]}"
    )


@pytest.mark.skipif(not ocr_available(), reason="no OCR language pack")
def test_every_read_carries_a_non_degenerate_bbox():
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (400, 120), "white")
    ImageDraw.Draw(image).text((20, 40), "Export", fill="black")
    frame = np.array(image)[:, :, ::-1]

    for read in WindowsOcr().read(frame):
        left, top, right, bottom = read.bbox
        assert right > left and bottom > top, f"degenerate bbox {read.bbox}"


def test_availability_never_raises():
    """Called at startup on machines we do not control."""
    assert isinstance(ocr_available(), bool)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python -B -m pytest tests/test_ocr_engine.py -v`
Expected: FAIL — no module named `ghostcursor.perception.ocr`.

- [ ] **Step 3: Write the engine**

```python
"""Tier 2 perception: read text off pixels when UIA cannot see the control.

Engine is `Windows.Media.Ocr`, chosen by measurement (spike findings §3):
0.17-0.23s on a full 1938x1038 window against RapidOCR's 39-66s, 22/23 recall
against 16/23, and 0.01s cold start. It ships with the OS, so there is no
model download and no network (D017).

It exposes no per-word confidence. That is why the fuzzy-match floor in
grounding is set conservatively at 95: one bar is doing the job the design
wanted two bars for.
"""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass


@dataclass(frozen=True)
class OcrRead:
    """One piece of text found on screen, in SCREEN coordinates.

    Frozen primitives only: this crosses the worker thread boundary (D021).
    """

    text: str
    bbox: tuple[int, int, int, int]


def ocr_available() -> bool:
    """True if this machine can OCR at all.

    Never raises. A machine with no OCR language pack must still run Ghost
    Cursor on UIA alone rather than failing at import.
    """
    try:
        from winsdk.windows.media.ocr import OcrEngine

        return OcrEngine.try_create_from_user_profile_languages() is not None
    except Exception:
        return False


class WindowsOcr:
    """Thin wrapper over Windows.Media.Ocr.

    The engine is created once and reused; creation measured at 0.01s, so
    there is no lazy-loading ceremony to justify.
    """

    def __init__(self) -> None:
        from winsdk.windows.media.ocr import OcrEngine

        self._engine = OcrEngine.try_create_from_user_profile_languages()
        if self._engine is None:
            raise RuntimeError(
                "no Windows OCR engine available — the OCR language pack is "
                "not installed on this machine"
            )

    def read(self, frame_bgr) -> list[OcrRead]:
        """Every word found in a BGR frame, with screen-relative boxes.

        Words rather than lines: a wrapped label arrives as separate reads,
        and reassembling them is `reassemble()`'s job, which needs the parts.
        """
        from PIL import Image
        from winsdk.windows.graphics.imaging import BitmapDecoder
        from winsdk.windows.storage.streams import (
            DataWriter,
            InMemoryRandomAccessStream,
        )

        buffer = io.BytesIO()
        Image.fromarray(frame_bgr[:, :, ::-1]).save(buffer, format="PNG")
        png = buffer.getvalue()

        async def recognise():
            stream = InMemoryRandomAccessStream()
            writer = DataWriter(stream.get_output_stream_at(0))
            writer.write_bytes(png)
            await writer.store_async()
            decoder = await BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()
            return await self._engine.recognize_async(bitmap)

        result = asyncio.run(recognise())

        reads: list[OcrRead] = []
        for line in result.lines:
            for word in line.words:
                rect = word.bounding_rect
                reads.append(
                    OcrRead(
                        text=word.text,
                        bbox=(
                            int(rect.x),
                            int(rect.y),
                            int(rect.x + rect.width),
                            int(rect.y + rect.height),
                        ),
                    )
                )
        return reads
```

- [ ] **Step 4: Run the test**

Run: `python -B -m pytest tests/test_ocr_engine.py -v`
Expected: PASS (4 tests; 3 skip if no language pack — but Task 1 established there is one).

- [ ] **Step 5: Commit**

```bash
git add ghostcursor/perception/ocr.py tests/test_ocr_engine.py
git commit -m "feat: add the Windows.Media.Ocr engine wrapper"
```

---

### Task 4: Multi-line label reassembly — both directions

**Files:**
- Modify: `ghostcursor/perception/ocr.py` (add `reassemble`)
- Test: `tests/test_ocr_reassembly.py`

**Interfaces:**
- Consumes: `OcrRead` from Task 3.
- Produces: `reassemble(reads: list[OcrRead]) -> list[OcrRead]` — returns the originals PLUS merged candidates, never fewer.

**Why this ships now and not later:** wrapped labels produced the one genuinely dangerous result in the spike. `Magic Expand` was read as its parts and fuzzy-matched **`Magic Edit`** at 72.7 — a different real tool in the same grid. A user following that hint applies the wrong operation to their image. The floor of 95 excludes that particular pair only incidentally; a different adjacent pair could clear it. This removes the mechanism rather than thresholding above its symptom.

- [ ] **Step 1: Write the failing test — BOTH directions**

```python
"""Wrapped labels, and the merge that fixes them without inventing new ones.

Fixtures are the spike's REAL reads, not invented strings.
"""

from ghostcursor.perception.ocr import OcrRead, reassemble
from rapidfuzz import fuzz


def _texts(reads):
    return [r.text for r in reads]


def _best(reads, target):
    return max((fuzz.ratio(r.text.lower(), target.lower()) for r in reads), default=0)


# Real Canva editor geometry: a two-line tool label, ~60px wide, 16px lines.
MAGIC = [
    OcrRead(text="Magic", bbox=(100, 200, 160, 216)),
    OcrRead(text="Expand", bbox=(98, 218, 168, 234)),
]
# A different real tool, one grid cell to the left.
MAGIC_EDIT = [OcrRead(text="Magic Edit", bbox=(10, 200, 90, 216))]


def test_recall_a_wrapped_label_is_reassembled():
    """The false-NEGATIVE direction: the feature's whole purpose."""
    merged = reassemble(MAGIC)
    assert _best(merged, "Magic Expand") >= 95, (
        f"'Magic Expand' was not recovered from its parts: {_texts(merged)}"
    )


def test_the_original_parts_are_still_offered():
    """A merge that guesses wrong must not LOSE a match the parts would make."""
    merged = reassemble(MAGIC)
    assert "Magic" in _texts(merged) and "Expand" in _texts(merged)


def test_reassembly_does_not_manufacture_a_match_across_unrelated_labels():
    """The false-POSITIVE direction — as load-bearing as recall.

    Acrobat's tool list stacks unrelated operations vertically at exactly the
    spacing a wrapped label uses. Merging them must not invent a target.
    """
    acrobat = [
        OcrRead(text="Redact a PDF", bbox=(40, 700, 180, 718)),
        OcrRead(text="Compress a PDF", bbox=(40, 750, 200, 768)),
    ]
    merged = reassemble(acrobat)
    for invented in ("Redact a PDF Compress", "Compress a PDF Redact"):
        assert _best(merged, invented) < 95, (
            f"reassembly manufactured {invented!r}: {_texts(merged)}"
        )


def test_reassembly_does_not_merge_across_a_panel_boundary():
    """Canva editor: 'Crop' and 'Pixel Eraser' are adjacent rows, unrelated."""
    canva = [
        OcrRead(text="Crop", bbox=(160, 460, 210, 484)),
        OcrRead(text="Pixel Eraser", bbox=(160, 540, 275, 564)),
    ]
    merged = reassemble(canva)
    assert _best(merged, "Crop Pixel Eraser") < 95, (
        f"unrelated rows were merged: {_texts(merged)}"
    )


def test_a_wrapped_label_does_not_match_its_neighbour():
    """The exact dangerous case from the spike, end to end."""
    merged = reassemble(MAGIC + MAGIC_EDIT)
    expand = [r for r in merged if fuzz.ratio(r.text.lower(), "magic expand") >= 95]
    assert expand, "Magic Expand still unrecoverable"
    for read in expand:
        assert fuzz.ratio(read.text.lower(), "magic edit") < 95


def test_at_most_three_reads_merge_into_one_candidate():
    stack = [OcrRead(text=f"w{i}", bbox=(100, 200 + i * 18, 140, 214 + i * 18))
             for i in range(6)]
    for read in reassemble(stack):
        assert len(read.text.split()) <= 3
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python -B -m pytest tests/test_ocr_reassembly.py -v`
Expected: FAIL — cannot import `reassemble`.

- [ ] **Step 3: Implement reassembly**

Append to `ghostcursor/perception/ocr.py`:

```python
#: Geometry for deciding two reads are one wrapped label. Judgement informed
#: by one machine and four screens (spike findings §5); tunable, and expected
#: to be revisited against a second native application.
MERGE_CENTRE_TOLERANCE = 0.40  # of the wider box's width
MERGE_VERTICAL_GAP = 0.75  # of the taller box's height
MERGE_MAX_PARTS = 3


def _mergeable(a: OcrRead, b: OcrRead) -> bool:
    a_left, a_top, a_right, a_bottom = a.bbox
    b_left, b_top, b_right, b_bottom = b.bbox

    a_width, b_width = a_right - a_left, b_right - b_left
    a_height, b_height = a_bottom - a_top, b_bottom - b_top
    if min(a_width, b_width) <= 0 or min(a_height, b_height) <= 0:
        return False

    a_centre = (a_left + a_right) / 2
    b_centre = (b_left + b_right) / 2
    if abs(a_centre - b_centre) > MERGE_CENTRE_TOLERANCE * max(a_width, b_width):
        return False

    gap = b_top - a_bottom
    return 0 <= gap <= MERGE_VERTICAL_GAP * max(a_height, b_height)


def reassemble(reads: list[OcrRead]) -> list[OcrRead]:
    """Originals PLUS merged candidates for labels that wrapped onto lines.

    Never returns fewer reads than it was given. Both the merged candidate and
    its parts go to grounding, so a merge that guesses wrong cannot lose a
    match an unmerged read would have made.

    The inverse risk — merging two unrelated adjacent labels into a string
    that matches something neither part would — is why the geometry is
    deliberately tight and why the false-positive direction is tested.
    """
    ordered = sorted(reads, key=lambda r: (r.bbox[1], r.bbox[0]))
    merged: list[OcrRead] = list(reads)

    for i, first in enumerate(ordered):
        parts = [first]
        for candidate in ordered[i + 1 :]:
            if len(parts) >= MERGE_MAX_PARTS:
                break
            if not _mergeable(parts[-1], candidate):
                continue
            parts.append(candidate)
            merged.append(
                OcrRead(
                    text=" ".join(p.text for p in parts),
                    bbox=(
                        min(p.bbox[0] for p in parts),
                        min(p.bbox[1] for p in parts),
                        max(p.bbox[2] for p in parts),
                        max(p.bbox[3] for p in parts),
                    ),
                )
            )
    return merged
```

- [ ] **Step 4: Run the test**

Run: `python -B -m pytest tests/test_ocr_reassembly.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit, THEN mutate (D018)**

```bash
git add ghostcursor/perception/ocr.py tests/test_ocr_reassembly.py
git commit -m "feat: reassemble wrapped OCR labels without inventing new ones"
```

- [ ] **Step 6: Mutation — prove BOTH directions bite**

Mutation A (recall): set `MERGE_VERTICAL_GAP = 0.0`.
Run: `python -B -m pytest tests/test_ocr_reassembly.py -v`
Expected: `test_recall_a_wrapped_label_is_reassembled` FAILS. Restore.

Mutation B (false positive): set `MERGE_VERTICAL_GAP = 5.0` and `MERGE_CENTRE_TOLERANCE = 5.0`.
Expected: `test_reassembly_does_not_merge_across_a_panel_boundary` FAILS. Restore.

Report both failure messages. If either survives, that is the finding — say so plainly rather than adjusting the test until it looks right.

---

### Task 5: DPI-correct capture and frame differencing

**Files:**
- Create: `ghostcursor/perception/capture.py`
- Test: `tests/test_capture.py`

**Interfaces:**
- Produces: `capture_window(title_re: str) -> tuple[numpy.ndarray, tuple[int,int,int,int]] | None` returning `(frame_bgr, window_rect)`; `frames_differ(previous, current, threshold=FRAME_DIFF_THRESHOLD) -> bool`; `FRAME_DIFF_THRESHOLD = 0.02`.

- [ ] **Step 1: Write the failing test**

```python
"""Capture and diffing. The diff is what stops OCR running every tick."""

import numpy as np

from ghostcursor.overlay import dpi  # noqa: F401  DPI awareness at import (D010)
from ghostcursor.perception.capture import (
    FRAME_DIFF_THRESHOLD,
    capture_window,
    frames_differ,
)


def _frame(value=0):
    return np.full((100, 200, 3), value, dtype=np.uint8)


def test_no_previous_frame_counts_as_changed():
    """The first observation must never be skipped."""
    assert frames_differ(None, _frame()) is True


def test_identical_frames_do_not_differ():
    assert frames_differ(_frame(10), _frame(10)) is False


def test_a_fully_repainted_frame_differs():
    assert frames_differ(_frame(0), _frame(255)) is True


def test_a_tiny_change_is_below_the_threshold():
    """A blinking cursor must not trigger a re-read."""
    current = _frame(0)
    current[0:2, 0:2] = 255  # 4 of 20000 pixels = 0.02%
    assert frames_differ(_frame(0), current) is False


def test_a_change_just_over_the_threshold_is_detected():
    current = _frame(0)
    rows = int(100 * (FRAME_DIFF_THRESHOLD * 2))
    current[0:rows, :] = 255
    assert frames_differ(_frame(0), current) is True


def test_mismatched_shapes_count_as_changed():
    """A resized window is a change, not a crash."""
    assert frames_differ(_frame(), np.zeros((50, 50, 3), dtype=np.uint8)) is True


def test_capturing_an_absent_window_returns_none():
    assert capture_window("NoSuchWindowTitleAnywhere12345") is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python -B -m pytest tests/test_capture.py -v`
Expected: FAIL — no module named `ghostcursor.perception.capture`.

- [ ] **Step 3: Implement**

```python
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
```

- [ ] **Step 4: Run the test**

Run: `python -B -m pytest tests/test_capture.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostcursor/perception/capture.py tests/test_capture.py
git commit -m "feat: add DPI-correct window capture and frame differencing"
```

---

### Task 6: Grounding — rung 3 guard and rung 4

**Files:**
- Modify: `ghostcursor/reasoning/grounding.py`
- Test: `tests/test_grounding_rung4.py`

**Interfaces:**
- Consumes: `Element.source` (Task 2).
- Produces: `RUNG_OCR_TEXT = 4`; `OCR_MATCH_FLOOR = 95`. `ground()` signature unchanged.

**The two changes are one safety property.** Rung 3 is a case-insensitive **substring** test inherited from the UIA-era ladder, and it runs BEFORE rung 4. Left unfiltered, an OCR element would match there with no score threshold at all and the measured floor of 95 would be decorative — `Edit` substring-matches OCR reads of `Edit a PDF`, `Magic Edit` and `Editor` alike. OCR text gets exactly one route into grounding.

- [ ] **Step 1: Write the failing test**

```python
"""Rung 4, and the guard that stops rung 3 bypassing its floor.

Every fixture below is a REAL read from the spike, with its real score.
"""

from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.grounding import (
    OCR_MATCH_FLOOR,
    RUNG_OCR_TEXT,
    ground,
)
from ghostcursor.reasoning.schema import Recipe


def _step(name, synonyms=()):
    recipe = Recipe.from_dict({
        "app_id": "test", "intent": "t",
        "steps": [{
            "user_action": "click",
            "target_descriptor": {
                "claimed": {"name": name, "name_synonyms": list(synonyms)},
                "confirmed": [],
            },
            "instruction_text": "x",
            "verification_rule": {"kind": "user_confirms", "args": {}},
            "risk": "normal",
        }],
    })
    return recipe.steps[0]


def _ocr(text, bbox=(10, 20, 110, 44)):
    return Element(name=text, control_type="", automation_id="", bbox=bbox,
                   path=(), source="ocr")


def test_an_exact_ocr_read_grounds_at_rung_4():
    target = ground(_step("BG Remover"), ".*", elements=[_ocr("BG Remover")])
    assert target is not None and target.rung == RUNG_OCR_TEXT


def test_uploads_does_not_match_upload():
    """The binding case. Both are real Canva surfaces; the spike measured 92.3,
    and 0.85 -- the value the OCR doc suggests -- would have pointed wrong."""
    assert ground(_step("Uploads"), ".*", elements=[_ocr("upload")]) is None


def test_magic_expand_does_not_match_magic_edit():
    """The dangerous case: a different real tool in the same grid (72.7)."""
    assert ground(_step("Magic Expand"), ".*", elements=[_ocr("Magic Edit")]) is None


def test_rung_3_never_sees_an_ocr_element():
    """Rung 3 is a SUBSTRING test. Unfiltered it would match 'Edit' against
    'Edit a PDF' with no floor at all, making 95 decorative."""
    assert ground(_step("Edit"), ".*", elements=[_ocr("Edit a PDF")]) is None


def test_rung_3_still_works_for_uia_elements():
    """The guard must not break the existing ladder."""
    uia = Element(name="Edit a PDF", control_type="Button", automation_id="",
                  bbox=(0, 0, 10, 10))
    target = ground(_step("Edit"), ".*", elements=[uia])
    assert target is not None and target.rung == 3


def test_ocr_elements_may_still_match_exactly_at_rung_2():
    """Exact equality is a strictly higher bar than a 95 fuzzy score."""
    target = ground(_step("Upscale"), ".*", elements=[_ocr("Upscale")])
    assert target is not None and target.rung in (2, RUNG_OCR_TEXT)


def test_the_floor_is_95():
    assert OCR_MATCH_FLOOR == 95
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python -B -m pytest tests/test_grounding_rung4.py -v`
Expected: FAIL — cannot import `RUNG_OCR_TEXT`.

- [ ] **Step 3: Implement both changes**

Add near the other rung constants in `ghostcursor/reasoning/grounding.py`:

```python
RUNG_OCR_TEXT = 4

#: Fuzzy-match floor for OCR text, measured across four real screens (spike
#: findings §4). 95 is forced by `Uploads` vs the read `upload` at 92.3 — two
#: real Canva surfaces one character apart.
#:
#: Deliberately conservative because it is doing TWO jobs. The design called
#: for two independent floors, read confidence AND match score, neither
#: borrowing slack from the other. Windows.Media.Ocr exposes no per-word
#: confidence, so the match score carries both.
OCR_MATCH_FLOOR = 95
```

In `ground()`, change rung 3's comprehension to exclude OCR:

```python
    # Rung 3 — synonyms and case-insensitive substring.
    #
    # UIA ONLY. This is a substring test, and it runs before rung 4, so an OCR
    # element reaching it would match with no score threshold whatsoever and
    # OCR_MATCH_FLOOR would be decorative: 'Edit' is a substring of 'Edit a
    # PDF', 'Magic Edit' and 'Editor' alike. OCR text gets exactly one route
    # into grounding, and it is rung 4.
    candidates = [claimed.name, *claimed.name_synonyms]
    for candidate in filter(None, candidates):
        needle = candidate.casefold()
        matches = [
            e
            for e in elements
            if e.source == "uia" and e.name and needle in e.name.casefold()
        ]
        if matches:
            return _as_target(_disambiguate(matches, step), RUNG_FUZZY_NAME)
```

Then add rung 4 immediately before the final `return None`:

```python
    # Rung 4 — fuzzy text, OCR elements only, at a measured floor.
    ocr_elements = [e for e in elements if e.source == "ocr" and e.name]
    if ocr_elements:
        from rapidfuzz import fuzz

        best_score, best_element = 0.0, None
        for candidate in filter(None, candidates):
            for element in ocr_elements:
                score = fuzz.ratio(element.name.casefold(), candidate.casefold())
                if score > best_score:
                    best_score, best_element = score, element
        if best_element is not None and best_score >= OCR_MATCH_FLOOR:
            return _as_target(best_element, RUNG_OCR_TEXT)

    return None
```

- [ ] **Step 4: Run the test**

Run: `python -B -m pytest tests/test_grounding_rung4.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Run the fast suite**

Expected: 179 passed. Zero existing tests edited.

- [ ] **Step 6: Commit, then mutate (D018)**

```bash
git add ghostcursor/reasoning/grounding.py tests/test_grounding_rung4.py
git commit -m "feat: ground OCR text at rung 4, and stop rung 3 bypassing its floor"
```

Mutation A: `OCR_MATCH_FLOOR = 85`.
Expected: `test_uploads_does_not_match_upload` FAILS (92.3 clears 85). Restore.

Mutation B: drop `e.source == "uia"` from rung 3's comprehension.
Expected: `test_rung_3_never_sees_an_ocr_element` FAILS. Restore.

Report both failure messages.

---

### Task 7: `Freshness.INFERRED` and the no-laundering rule

**Files:**
- Modify: `ghostcursor/reasoning/staleness.py`
- Test: `tests/test_freshness_inferred.py`

**Interfaces:**
- Produces: `Freshness.INFERRED`; `display_freshness(ladder_state: Freshness, source: str) -> Freshness`.

- [ ] **Step 1: Write the failing test**

```python
"""INFERRED, and the rule that stops a pixel guess laundering into a fact."""

from ghostcursor.reasoning.staleness import Freshness, display_freshness


def test_a_uia_hint_that_is_current_is_fresh():
    assert display_freshness(Freshness.FRESH, "uia") is Freshness.FRESH


def test_a_current_ocr_hint_is_inferred_not_fresh():
    assert display_freshness(Freshness.FRESH, "ocr") is Freshness.INFERRED


def test_staleness_dominates_source():
    """'Possibly outdated' subsumes 'possibly misread'."""
    assert display_freshness(Freshness.DIMMED, "ocr") is Freshness.DIMMED
    assert display_freshness(Freshness.DIMMED, "uia") is Freshness.DIMMED


def test_hidden_dominates_everything():
    assert display_freshness(Freshness.HIDDEN, "ocr") is Freshness.HIDDEN
    assert display_freshness(Freshness.HIDDEN, "uia") is Freshness.HIDDEN


def test_a_recovered_ocr_hint_returns_to_inferred_never_to_fresh():
    """The laundering guard.

    A tier-2 hint that goes stale shows DIMMED. If recovery returned FRESH, a
    round trip through staleness would silently convert a pixel guess into a
    confirmed control -- the same shape as the verification-baseline
    laundering bug found in the previous milestone.
    """
    assert display_freshness(Freshness.FRESH, "ocr") is Freshness.INFERRED
    assert display_freshness(Freshness.DIMMED, "ocr") is Freshness.DIMMED
    assert display_freshness(Freshness.FRESH, "ocr") is Freshness.INFERRED


def test_precedence_is_total():
    """HIDDEN > DIMMED > INFERRED > FRESH, for every combination."""
    expected = {
        (Freshness.HIDDEN, "uia"): Freshness.HIDDEN,
        (Freshness.HIDDEN, "ocr"): Freshness.HIDDEN,
        (Freshness.DIMMED, "uia"): Freshness.DIMMED,
        (Freshness.DIMMED, "ocr"): Freshness.DIMMED,
        (Freshness.FRESH, "uia"): Freshness.FRESH,
        (Freshness.FRESH, "ocr"): Freshness.INFERRED,
    }
    for (state, source), want in expected.items():
        assert display_freshness(state, source) is want, (state, source)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python -B -m pytest tests/test_freshness_inferred.py -v`
Expected: FAIL — cannot import `display_freshness`.

- [ ] **Step 3: Implement**

Add `INFERRED` to the enum in `ghostcursor/reasoning/staleness.py`:

```python
    INFERRED = auto()  # draw it, but it was read off pixels, not confirmed
```

And add the function at module level:

```python
def display_freshness(ladder_state: Freshness, source: str) -> Freshness:
    """Combine the staleness axis with the source axis into what is drawn.

    Two independent doubts: DIMMED is about TIME ("was this true a moment
    ago"), INFERRED is about SOURCE ("I matched text on pixels rather than
    confirming the control"). Collapsing them would tell the user to be
    careful without telling them what kind of caution applies.

    Precedence is strict: HIDDEN > DIMMED > INFERRED > FRESH. Staleness
    dominates, because "possibly outdated" subsumes "possibly misread".

    The source axis PERSISTS underneath the display: a stale OCR hint shows
    DIMMED, and when perception recovers this returns INFERRED, never FRESH.
    Otherwise a round trip through staleness would launder a pixel guess into
    a confirmed control.
    """
    if ladder_state in (Freshness.HIDDEN, Freshness.DIMMED):
        return ladder_state
    return Freshness.INFERRED if source == "ocr" else Freshness.FRESH
```

- [ ] **Step 4: Run the test**

Run: `python -B -m pytest tests/test_freshness_inferred.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit, then mutate (D018)**

```bash
git add ghostcursor/reasoning/staleness.py tests/test_freshness_inferred.py
git commit -m "feat: add INFERRED and the no-laundering display rule"
```

Mutation: make the last line `return Freshness.FRESH` unconditionally.
Expected: `test_a_current_ocr_hint_is_inferred_not_fresh` and `test_a_recovered_ocr_hint_returns_to_inferred_never_to_fresh` FAIL. Restore and report.

---

### Task 8: The INFERRED ring on real pixels

**Files:**
- Modify: `ghostcursor/overlay/window.py`
- Modify: `tests/test_overlay.py` (ADD a 16th check; do not alter existing checks)
- Test: `tests/test_overlay_inferred.py`

**Interfaces:**
- Consumes: `Freshness.INFERRED` (Task 7).
- Produces: `INFERRED_RING_COLOR`.

**This is the one task that can break something pytest does not cover.** It must run both pixel harnesses.

- [ ] **Step 1: Write the failing unit test**

```python
"""The third ring state must be distinguishable from the other two."""

from ghostcursor.overlay import window as ov
from ghostcursor.reasoning.staleness import Freshness


def _rgb(colorref):
    return (colorref & 0xFF, (colorref >> 8) & 0xFF, (colorref >> 16) & 0xFF)


def test_three_distinct_ring_colours_exist():
    colours = {ov.RING_COLOR, ov.DIMMED_RING_COLOR, ov.INFERRED_RING_COLOR}
    assert len(colours) == 3


def test_inferred_is_not_merely_a_shade_of_the_others():
    """It signals a different KIND of doubt, so it must not read as 'dim'."""
    inferred, fresh, dimmed = (
        _rgb(ov.INFERRED_RING_COLOR), _rgb(ov.RING_COLOR), _rgb(ov.DIMMED_RING_COLOR)
    )
    assert sum(abs(a - b) for a, b in zip(inferred, fresh)) > 90
    assert sum(abs(a - b) for a, b in zip(inferred, dimmed)) > 90


def test_the_painter_picks_a_colour_for_every_drawable_state():
    for state in (Freshness.FRESH, Freshness.DIMMED, Freshness.INFERRED):
        assert ov.ring_colour_for(state) in (
            ov.RING_COLOR, ov.DIMMED_RING_COLOR, ov.INFERRED_RING_COLOR
        )
    assert ov.ring_colour_for(Freshness.FRESH) == ov.RING_COLOR
    assert ov.ring_colour_for(Freshness.INFERRED) == ov.INFERRED_RING_COLOR
    assert ov.ring_colour_for(Freshness.DIMMED) == ov.DIMMED_RING_COLOR
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python -B -m pytest tests/test_overlay_inferred.py -v`
Expected: FAIL — no `INFERRED_RING_COLOR`.

- [ ] **Step 3: Implement**

In `ghostcursor/overlay/window.py`, beside the other colours:

```python
#: Amber. Deliberately a different HUE from the cyan family, not a dimmer
#: shade of it: DIMMED already means "possibly out of date", and INFERRED means
#: "possibly misread". A user who cannot tell those apart cannot calibrate
#: trust, which is what D006 depends on.
INFERRED_RING_COLOR = win32api.RGB(255, 170, 0)


def ring_colour_for(freshness) -> int:
    """The ring colour for a drawable freshness state.

    HIDDEN never reaches here: the caller clears the hint instead, because
    this function must always return a colour and a hidden hint has none.
    """
    from ghostcursor.reasoning.staleness import Freshness

    if freshness is Freshness.INFERRED:
        return INFERRED_RING_COLOR
    if freshness is Freshness.DIMMED:
        return DIMMED_RING_COLOR
    return RING_COLOR
```

Replace the colour choice inside `_paint_ring`:

```python
    colour = ring_colour_for(freshness)
```

- [ ] **Step 4: Run the unit test and the fast suite**

Run: `python -B -m pytest tests/test_overlay_inferred.py -v`, then the fast suite.
Expected: PASS; 185 passed overall.

- [ ] **Step 5: Add the 16th pixel check**

In `tests/test_overlay.py`, alongside the existing dimmed-ring check, add a check that renders a hint with `freshness=Freshness.INFERRED` through the real `WM_PAINT` path and asserts the ring pixels are `INFERRED_RING_COLOR` — and that **zero** pixels fall in either the fresh or the dimmed colour band. Reuse the existing controlled backdrop (`tests/backdrop.py`) and `dpi.capture_region()`; never the live desktop, never `mss.monitors[1]`, never a separate process. Update the harness's announced check count from 15 to 16.

- [ ] **Step 6: Run BOTH pixel harnesses**

```
python -B -m tests.test_overlay        # expect 16/16
python -B -m tests.test_end_to_end     # expect 8/8
```

Run them FOREGROUND, sequentially, with nothing else running. They open real full-screen windows briefly. If one refuses with `EnvironmentUnavailable` because another window occludes the backdrop, close the offending window and re-run — that refusal is the harness protecting you from a meaningless result, not a failure.

- [ ] **Step 7: Commit, then mutate (D018)**

```bash
git add ghostcursor/overlay/window.py tests/test_overlay_inferred.py tests/test_overlay.py
git commit -m "feat: draw INFERRED hints in their own colour"
```

Mutation: make `ring_colour_for` return `DIMMED_RING_COLOR` for `INFERRED`.
Expected: the new pixel check in `tests.test_overlay` FAILS with a non-zero dimmed-coloured pixel count. Restore and report the literal failure line.

---

### Task 9: `Tier2Controller` — stickiness, both caps, terminal exhaustion

**Files:**
- Create: `ghostcursor/perception/tier2.py`
- Test: `tests/test_tier2_controller.py`

**Interfaces:**
- Consumes: `frames_differ` (Task 5), `reassemble`, `OcrRead` (Tasks 3–4), `Element` (Task 2).
- Produces: `Tier2Controller(ocr, capture, clock, min_interval_s=1.0, max_runs_per_step=20)` with `.elements_for(step_index, title_re) -> list[Element]`, `.exhausted(step_index) -> bool`, `.reset(step_index)`.

- [ ] **Step 1: Write the failing test**

```python
"""Cadence, caps, and what happens when the cap runs out.

Everything is driven by an injected clock. No sleeping (D026).
"""

import numpy as np

from ghostcursor.perception.ocr import OcrRead
from ghostcursor.perception.tier2 import Tier2Controller


class FakeClock:
    def __init__(self):
        self.t = 1000.0  # never 0.0: that is the untimestamped sentinel (D023)

    def __call__(self):
        return self.t


class FakeOcr:
    def __init__(self):
        self.calls = 0

    def read(self, frame):
        self.calls += 1
        return [OcrRead(text="BG Remover", bbox=(10, 20, 110, 44))]


def _controller(clock, ocr, frames=None):
    frames = frames or [np.zeros((10, 10, 3), dtype=np.uint8)]
    state = {"i": 0}

    def capture(_title_re):
        frame = frames[min(state["i"], len(frames) - 1)]
        state["i"] += 1
        return frame, (0, 0, 10, 10)

    return Tier2Controller(ocr=ocr, capture=capture, clock=clock)


def test_it_reads_on_first_use():
    clock, ocr = FakeClock(), FakeOcr()
    elements = _controller(clock, ocr).elements_for(0, ".*")
    assert ocr.calls == 1
    assert elements and elements[0].source == "ocr"
    assert elements[0].name == "BG Remover"


def test_an_unchanged_region_is_not_re_read():
    clock, ocr = FakeClock(), FakeOcr()
    controller = _controller(clock, ocr)
    controller.elements_for(0, ".*")
    clock.t += 10.0
    controller.elements_for(0, ".*")
    assert ocr.calls == 1, "an unchanged region was re-read"


def test_the_minimum_interval_holds_even_when_the_region_changes():
    """A loading spinner must not turn 're-run on change' into every tick."""
    clock, ocr = FakeClock(), FakeOcr()
    frames = [np.full((10, 10, 3), v, dtype=np.uint8) for v in (0, 255, 0, 255)]
    controller = _controller(clock, ocr, frames)
    for _ in range(4):
        clock.t += 0.1
        controller.elements_for(0, ".*")
    assert ocr.calls == 1, f"re-read {ocr.calls}x inside the 1.0s floor"


def test_a_changed_region_is_re_read_after_the_interval():
    clock, ocr = FakeClock(), FakeOcr()
    frames = [np.full((10, 10, 3), v, dtype=np.uint8) for v in (0, 255)]
    controller = _controller(clock, ocr, frames)
    controller.elements_for(0, ".*")
    clock.t += 1.5
    controller.elements_for(0, ".*")
    assert ocr.calls == 2


def test_the_run_cap_stops_a_continuously_animating_region():
    clock, ocr = FakeClock(), FakeOcr()
    frames = [np.full((10, 10, 3), (i * 40) % 256, dtype=np.uint8) for i in range(60)]
    controller = _controller(clock, ocr, frames)
    for _ in range(60):
        clock.t += 2.0
        controller.elements_for(0, ".*")
    assert ocr.calls == 20, f"cap breached: {ocr.calls} runs"
    assert controller.exhausted(0) is True


def test_exhaustion_is_terminal_and_stops_reading():
    clock, ocr = FakeClock(), FakeOcr()
    frames = [np.full((10, 10, 3), (i * 40) % 256, dtype=np.uint8) for i in range(60)]
    controller = _controller(clock, ocr, frames)
    for _ in range(40):
        clock.t += 2.0
        controller.elements_for(0, ".*")
    before = ocr.calls
    clock.t += 100.0
    controller.elements_for(0, ".*")
    assert ocr.calls == before, "kept reading after exhaustion"


def test_stickiness_resets_at_the_step_boundary():
    """Otherwise this silently becomes app-wide always-on OCR."""
    clock, ocr = FakeClock(), FakeOcr()
    frames = [np.full((10, 10, 3), (i * 40) % 256, dtype=np.uint8) for i in range(60)]
    controller = _controller(clock, ocr, frames)
    for _ in range(40):
        clock.t += 2.0
        controller.elements_for(0, ".*")
    assert controller.exhausted(0) is True

    clock.t += 2.0
    controller.elements_for(1, ".*")
    assert controller.exhausted(1) is False, "step 1 inherited step 0's exhaustion"


def test_an_absent_window_yields_no_elements_and_costs_no_read():
    clock, ocr = FakeClock(), FakeOcr()
    controller = Tier2Controller(ocr=ocr, capture=lambda _t: None, clock=clock)
    assert controller.elements_for(0, ".*") == []
    assert ocr.calls == 0
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python -B -m pytest tests/test_tier2_controller.py -v`
Expected: FAIL — no module named `ghostcursor.perception.tier2`.

- [ ] **Step 3: Implement**

```python
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

#: Ceiling per step. Same reason, for a region that never stops changing.
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


class _StepState:
    __slots__ = ("runs", "last_run_at", "last_frame", "elements")

    def __init__(self) -> None:
        self.runs = 0
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
        """True once this step has spent its run budget.

        Terminal for the step: the caller treats it as ungroundable and lets
        the existing grounding grace end the tour with a reason. The rejected
        alternative -- let the last result stand and age -- leaves the ring
        pointing at a coordinate the system can no longer confirm AND makes
        the step incapable of ever failing.
        """
        return self._state(step_index).runs >= self.max_runs_per_step

    def reset(self, step_index: int) -> None:
        self._steps.pop(step_index, None)

    def elements_for(self, step_index: int, title_re: str) -> list[Element]:
        state = self._state(step_index)
        if self.exhausted(step_index):
            return []

        now = self.clock()
        if state.last_run_at is not None and now - state.last_run_at < self.min_interval_s:
            return state.elements

        captured = self.capture(title_re)
        if captured is None:
            return state.elements
        frame, rect = captured

        if not frames_differ(state.last_frame, frame):
            state.last_frame = frame
            return state.elements

        state.runs += 1
        state.last_run_at = now
        state.last_frame = frame
        state.elements = _to_elements(
            reassemble(self.ocr.read(frame)), (rect[0], rect[1])
        )
        return state.elements
```

- [ ] **Step 4: Run the test**

Run: `python -B -m pytest tests/test_tier2_controller.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit, then mutate (D018)**

```bash
git add ghostcursor/perception/tier2.py tests/test_tier2_controller.py
git commit -m "feat: add tier 2 cadence with per-step caps and terminal exhaustion"
```

Mutation A: `DEFAULT_MAX_RUNS_PER_STEP = 10_000`.
Expected: `test_the_run_cap_stops_a_continuously_animating_region` FAILS. Restore.

Mutation B: `DEFAULT_MIN_INTERVAL_S = 0.0`.
Expected: `test_the_minimum_interval_holds_even_when_the_region_changes` FAILS. Restore.

Mutation C: make `exhausted()` always return `False`.
Expected: `test_exhaustion_is_terminal_and_stops_reading` FAILS. Restore.

Report all three failure messages.

---

### Task 10: Wire tier 2 into the tour

**Files:**
- Modify: `ghostcursor/run.py` (`run_tour` only; the no-recipe static-hint path is untouched)
- Test: `tests/test_tier2_timeline.py`

**Interfaces:**
- Consumes: everything from Tasks 2–9.
- Produces: no new public names.

- [ ] **Step 1: Write the failing ordered-sequence test (D026)**

```python
"""Tier 2 end to end, as an ordered sequence on an injected clock.

Every component below is unit-tested already. This asserts they compose --
which is the class of bug that has bitten this project three times.
"""

import numpy as np

from ghostcursor.overlay import dpi  # noqa: F401
from ghostcursor.perception.ocr import OcrRead
from ghostcursor.perception.service import Observation
from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.staleness import Freshness
from ghostcursor.reasoning.verification import Snapshot
from tests.test_run_threaded import _fake_overlay, _recipe_file


class FakeClock:
    START = 1000.0

    def __init__(self):
        self.t = self.START

    def __call__(self):
        return self.t

    def sleeper(self, seconds):
        self.t += seconds


class UiaBlindService:
    """A worker that sees the window but never the control the step names."""

    def __init__(self, clock):
        self._clock = clock
        self.heartbeat = 0

    def start(self):
        pass

    def stop(self):
        pass

    def restart(self):
        pass

    def is_alive(self):
        return True

    def latest(self):
        now = self._clock()
        furniture = (Element("Minimise", "Button", "view_1", (0, 0, 20, 20)),)
        return Observation(
            snapshot=Snapshot(title="app", elements=furniture, observed_at=now),
            elements=furniture,
            observed_at=now,
            ok=True,
        )


def test_ocr_recovers_a_target_uia_cannot_see_and_it_renders_as_inferred(
    tmp_path, monkeypatch
):
    import ghostcursor.run as run_module
    from ghostcursor.perception import appinfo, service as service_module, tier2

    clock = FakeClock()
    calls = _fake_overlay(monkeypatch)
    monkeypatch.setattr(
        service_module, "PerceptionService", lambda *a, **k: UiaBlindService(clock)
    )
    monkeypatch.setattr(appinfo, "app_info_for_window", lambda _t: None)
    monkeypatch.setattr(run_module, "escape_pressed", lambda: False)
    monkeypatch.setattr(run_module, "key_was_pressed", lambda vk: False)

    class FakeOcr:
        def read(self, frame):
            return [OcrRead(text="Export", bbox=(10, 20, 110, 44))]

    monkeypatch.setattr(tier2, "_DEFAULT_OCR_FACTORY", lambda: FakeOcr())
    monkeypatch.setattr(
        tier2,
        "_DEFAULT_CAPTURE",
        lambda _t: (np.zeros((10, 10, 3), dtype=np.uint8), (0, 0, 10, 10)),
    )

    printed = []
    monkeypatch.setattr(
        "builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a)))
    )

    run_module.run_tour(
        _recipe_file(tmp_path), ".*app.*", seconds=8.0,
        clock=clock, sleeper=clock.sleeper,
    )

    states = [c[3] for c in calls if c[0] == "set_hint"]
    assert states, f"no hint was ever drawn: {printed}"
    assert Freshness.INFERRED in states, (
        f"an OCR-grounded hint was not drawn as INFERRED: {states}"
    )
    assert Freshness.FRESH not in states, (
        f"a pixel guess was drawn with the authority of a confirmed control: {states}"
    )
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python -B -m pytest tests/test_tier2_timeline.py -v`
Expected: FAIL — `tier2` has no `_DEFAULT_OCR_FACTORY`.

- [ ] **Step 3: Add the injection seams to `tier2.py`**

```python
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
```

- [ ] **Step 4: Wire it into `run_tour`**

After `ladder` and `health` are constructed:

```python
        tier2_controller = tier2.build_controller(clock)
        if tier2_controller is None:
            print("Ghost Cursor: OCR unavailable on this machine — UIA only.")
        #: Which source the LAST successful grounding came from. Drives the
        #: display, and persists across staleness so a recovered OCR hint
        #: returns to INFERRED and never launders into FRESH.
        grounded_source = "uia"
```

Replace `grounder_from_slot` with a version that falls back:

```python
            def grounder_from_slot(step, i, elements=None):
                nonlocal grounded_source
                if elements is None:
                    observation = service.latest()
                    elements = observation.elements if observation else ()

                target = live_grounder(step, i, elements)
                if target is not None:
                    grounded_source = "uia"
                    return target

                # Tier 2. Triggered by GROUNDING FAILURE for this step, never
                # by an empty walk: Chrome returned 43 elements containing zero
                # page content, so "UIA returned nothing" would never fire.
                if tier2_controller is None:
                    return None
                ocr_elements = tier2_controller.elements_for(i, title_re)
                if not ocr_elements:
                    return None
                target = live_grounder(step, i, list(elements) + ocr_elements)
                if target is not None:
                    grounded_source = "ocr"
                return target
```

In the freshness block, combine the two axes and honour exhaustion:

```python
                freshness = display_freshness(ladder.freshness(), grounded_source)
                showing = tour.renderer.last_instruction is not None
                if freshness is Freshness.HIDDEN:
                    window.clear_hint(hwnd)
                elif showing and tour._grounded is not None:
                    window.set_hint(hwnd, cx, cy, freshness=freshness)
```

And after the health check, before `tour.tick()`:

```python
                # Cap exhaustion is terminal for the step: it stops reading and
                # the step is treated as ungroundable, feeding the existing
                # grace. Naming the read failure matters -- telling the user
                # their element is missing, when we in fact gave up reading the
                # screen, points them at their own application instead of ours
                # (D024).
                if tier2_controller is not None and tier2_controller.exhausted(
                    tour.step_index
                ):
                    print(
                        f"Stopped: could not read "
                        f"'{tour.current_step.target_descriptor.claimed.name}' "
                        f"on screen after {tier2_controller.max_runs_per_step} attempts"
                    )
                    break
```

Import at the top of `run_tour`'s import block:

```python
    from ghostcursor.perception import tier2
    from ghostcursor.reasoning.staleness import Freshness, StalenessLadder, display_freshness
```

- [ ] **Step 5: Run the test, then the whole suite**

```
python -B -m pytest tests/test_tier2_timeline.py -v
python -B -m pytest tests/ -q --ignore=tests/test_hung_window.py --ignore=tests/test_perception_service_hung.py --ignore=tests/test_run_threaded.py
python -B -m pytest tests/test_run_threaded.py -q
python -B -m pytest tests/test_hung_window.py tests/test_perception_service_hung.py -q
```

Sequentially, FOREGROUND, nothing concurrent (D025). Expected: all pass; 168 pre-existing unchanged.

- [ ] **Step 6: Commit, then mutate (D018)**

```bash
git add ghostcursor/run.py ghostcursor/perception/tier2.py tests/test_tier2_timeline.py
git commit -m "feat: fall back to OCR when a step cannot be grounded via UIA"
```

Mutation: in the freshness block, use `ladder.freshness()` directly instead of `display_freshness(...)`.
Expected: `test_ocr_recovers_a_target_uia_cannot_see_and_it_renders_as_inferred` FAILS on the `Freshness.FRESH not in states` assertion — a pixel guess drawn with the authority of a confirmed control. Restore and report.

---

### Task 11: Documentation

**Files:**
- Modify: `DECISIONS.md`, `FLOW.md`, `CLAUDE.md`

- [ ] **Step 1: Add DECISIONS entries**

Append, matching the existing entries' depth — what was decided, what the alternatives were, and why:

- **D027 — Tier 2 triggers on grounding failure, never on an empty walk.** The measurement that forces it: Chrome returned 43 elements in 0.31 s containing zero page content, so "UIA returned nothing" would never have fired. Why stickiness resets at the step boundary (an app-wide flag silently becomes always-on OCR). Why both caps exist, and that exhausting the run cap is terminal for the step rather than freezing the last result — a frozen result leaves the ring on a coordinate the system can no longer confirm AND makes the step incapable of failing.
- **D028 — `Windows.Media.Ocr`, and the floor of 95.** The engine comparison (0.17–0.23 s vs 39–66 s; 22/23 vs 16/23 recall) and that RapidOCR is disqualified rather than merely slower. That stock PaddleOCR was ruled out on D017 grounds without measurement. That the floor is measured, forced by `Uploads` ← `upload` at 92.3, and that the doc's suggested 0.85 would have pointed wrong on the first real screen. **State plainly that the engine exposes no per-word confidence, so the two-independent-floors design could not be implemented and the match score carries both jobs — which is why 95 is conservative.** Record the language-pack risk and that Task 1 gated it on a clean machine.
- **D029 — OCR results are never promoted, and rung 3 excludes them.** Promotion is impossible by construction: `schema.py` recursively rejects stored coordinates, and the text is the claimed name the recipe already had. Rung 3 is a substring test that runs before rung 4, so unfiltered it would make the floor decorative. Cite the spike doc.

- [ ] **Step 2: Update FLOW.md**

Add `perception/ocr.py`, `perception/capture.py` and `perception/tier2.py` to the Files table with one-line roles. Extend the guided-tour call graph to show `grounder_from_slot` falling back to `tier2_controller.elements_for(...)` on grounding failure, and the freshness block combining the ladder state with `grounded_source` via `display_freshness`. Update the verification numbers to the real ones from the final run. Update "You are here".

- [ ] **Step 3: Update CLAUDE.md**

Add tier 2 to the perception bullet: OCR runs on the worker thread, triggered per-step by grounding failure, `Windows.Media.Ocr`, floor 95, never persisted. Refresh the test counts by running the suites rather than assuming. Note that `tests.test_overlay` is now 16 checks.

- [ ] **Step 4: Verify the documented commands actually work**

Run each command as written in CLAUDE.md and confirm the counts match. Documentation that confidently describes behaviour the code does not have is worse than none.

- [ ] **Step 5: Commit**

```bash
git add DECISIONS.md FLOW.md CLAUDE.md
git commit -m "docs: record the tier-2 decisions"
```

---

## Self-Review

**Spec coverage.** §1 why → Tasks 3–6 and 10. §2 scope (warm-up retry excluded) → not implemented anywhere, correct. §3 trigger + step-boundary stickiness → Tasks 9 and 10. §4 cadence, both caps, terminal exhaustion → Task 9 (caps) and Task 10 (the terminal reason). §4 threading → Task 9's docstring and Task 10's placement on the worker's element path. §5 engine + language-pack gate → Tasks 1 and 3. §6 `source` and never-promoted → Task 2 (field) and Task 11 (D029 records why promotion is impossible; no code is needed because nothing writes OCR to the store). §7 rungs 3 and 4 → Task 6. §8 reassembly both directions → Task 4. §9 display, precedence, no laundering → Tasks 7, 8, 10. §10 error handling → Task 3 (`ocr_available` never raises), Task 5 (absent window → None), Task 9 (absent window, exhaustion), Task 10 (`build_controller` returns None). §11 testing → distributed, with mutations named per task.

**Placeholder scan.** No TBD/TODO. Every code step carries real code. Task 8 Step 5 describes the pixel check in prose rather than code because it must be written against `tests/test_overlay.py`'s existing check-registration idiom, which the implementer reads in place; the assertion it must make is stated exactly.

**Type consistency.** `Element(..., source=)` matches across Tasks 2, 6, 9, 10. `OcrRead(text, bbox)` matches Tasks 3, 4, 9, 10. `reassemble(list[OcrRead]) -> list[OcrRead]` matches Tasks 4 and 9. `Freshness.INFERRED` and `display_freshness(state, source)` match Tasks 7, 8, 10. `Tier2Controller(ocr, capture, clock, ...)`, `.elements_for(step_index, title_re)`, `.exhausted(step_index)` match Tasks 9 and 10. `OCR_MATCH_FLOOR = 95` and `RUNG_OCR_TEXT = 4` are defined once in Task 6.

**One risk worth naming.** Task 8 changes the ring colour path, and both pixel harnesses assert on ring colour. It is the only task that can break something pytest does not cover, which is why its steps call the harnesses out explicitly and its mutation targets the new check.
