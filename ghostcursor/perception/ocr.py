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
                break
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
