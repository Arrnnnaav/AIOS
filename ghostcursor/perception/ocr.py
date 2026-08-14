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
