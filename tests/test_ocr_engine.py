"""The engine wrapper. Availability must degrade, never explode: a machine
with no OCR language pack still runs Ghost Cursor on UIA alone."""

import numpy as np
import pytest

from ghostcursor.perception.ocr import OcrRead, WindowsOcr, ocr_available


def _load_ui_sized_font():
    """A TrueType font at a size real UI text uses (~40pt).

    `Windows.Media.Ocr` cannot reliably detect PIL's bitmap default font
    (~10px cap height), and a fixture that doesn't resemble real UI labels
    (Acrobat's tool list, Canva's tool grid) isn't evidence anyway. If no
    TrueType font resolves, callers must skip rather than silently falling
    back to the tiny default font — a fallback would just reintroduce the
    same false failure.
    """
    from PIL import ImageFont

    for name in ("segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, 40)
        except Exception:
            continue
    return None


def test_ocr_read_is_frozen_primitives_only():
    """It crosses the worker boundary, so D021 applies."""
    read = OcrRead(text="Export", bbox=(10, 20, 60, 40))
    assert read.text == "Export"
    assert read.bbox == (10, 20, 60, 40)
    assert len({read, OcrRead(text="Export", bbox=(10, 20, 60, 40))}) == 1


@pytest.mark.skipif(not ocr_available(), reason="no OCR language pack")
def test_reads_text_off_a_synthetic_frame():
    from PIL import Image, ImageDraw

    font = _load_ui_sized_font()
    if font is None:
        pytest.skip(
            "no TrueType font resolved (segoeui.ttf/arial.ttf) to render UI-sized text"
        )

    image = Image.new("RGB", (400, 120), "white")
    ImageDraw.Draw(image).text((20, 40), "Export", fill="black", font=font)
    frame = np.array(image)[:, :, ::-1]  # RGB -> BGR, as mss produces

    reads = WindowsOcr().read(frame)

    assert any("export" in r.text.lower() for r in reads), (
        f"the engine read nothing resembling 'Export': {[r.text for r in reads]}"
    )


@pytest.mark.skipif(not ocr_available(), reason="no OCR language pack")
def test_every_read_carries_a_non_degenerate_bbox():
    from PIL import Image, ImageDraw

    font = _load_ui_sized_font()
    if font is None:
        pytest.skip(
            "no TrueType font resolved (segoeui.ttf/arial.ttf) to render UI-sized text"
        )

    image = Image.new("RGB", (400, 120), "white")
    ImageDraw.Draw(image).text((20, 40), "Export", fill="black", font=font)
    frame = np.array(image)[:, :, ::-1]

    for read in WindowsOcr().read(frame):
        left, top, right, bottom = read.bbox
        assert right > left and bottom > top, f"degenerate bbox {read.bbox}"


def test_availability_never_raises():
    """Called at startup on machines we do not control."""
    assert isinstance(ocr_available(), bool)
