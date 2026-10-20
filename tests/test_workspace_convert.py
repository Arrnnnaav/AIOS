"""Local file conversion (D186), the Open-Tangerine core ported to Windows.
Images round-trip through Pillow; media needs FFmpeg (optional). Local only."""

from __future__ import annotations

import pytest

from ghostcursor.workspace import convert


def _png(tmp_path, name="src.png", mode="RGBA", color=(255, 0, 0, 128)):
    from PIL import Image

    p = tmp_path / name
    Image.new(mode, (8, 8), color).save(p)
    return p


def test_convert_image_png_to_jpeg_flattens_alpha(tmp_path):
    from PIL import Image

    out = convert.convert_image(_png(tmp_path), "jpeg", dest_dir=tmp_path)
    assert out.suffix == ".jpeg" and out.exists()
    with Image.open(out) as im:
        assert im.format == "JPEG" and im.mode == "RGB"  # alpha flattened


def test_convert_image_to_webp_and_png_keep_working(tmp_path):
    from PIL import Image

    src = _png(tmp_path)
    for fmt, pil in (("webp", "WEBP"), ("png", "PNG"), ("bmp", "BMP")):
        out = convert.convert_image(src, fmt, dest_dir=tmp_path)
        with Image.open(out) as im:
            assert im.format == pil


def test_output_never_clobbers_an_existing_file(tmp_path):
    src = _png(tmp_path)
    a = convert.convert_image(src, "png", dest_dir=tmp_path / "out")
    b = convert.convert_image(src, "png", dest_dir=tmp_path / "out")
    assert a != b and a.exists() and b.exists()  # second got a " (2)" suffix


def test_bad_target_is_refused(tmp_path):
    with pytest.raises(ValueError):
        convert.convert_image(_png(tmp_path), "exe", dest_dir=tmp_path)
    with pytest.raises(ValueError):
        convert.convert(_png(tmp_path), "docx", dest_dir=tmp_path)


def test_media_without_ffmpeg_gives_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(convert, "ffmpeg_available", lambda: False)
    with pytest.raises(RuntimeError, match="FFmpeg is not installed"):
        convert.convert_media(tmp_path / "a.wav", "mp3", dest_dir=tmp_path)


def test_convert_routes_images_to_pillow(tmp_path):
    out = convert.convert(_png(tmp_path), "jpeg", dest_dir=tmp_path)
    assert out.suffix == ".jpeg" and out.exists()
