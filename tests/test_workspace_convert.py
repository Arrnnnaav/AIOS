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


def test_image_to_pdf_via_router(tmp_path):
    out = convert.convert(_png(tmp_path), "pdf", dest_dir=tmp_path)
    assert out.suffix == ".pdf" and out.exists()
    assert out.read_bytes().startswith(b"%PDF")  # Pillow writes but can't read PDF


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


SRT = "1\n00:00:01,000 --> 00:00:02,500\nHello world\n\n2\n00:00:03,000 --> 00:00:04,000\nSecond line\n"


def test_subtitle_srt_to_vtt_and_back_and_text(tmp_path):
    src = tmp_path / "s.srt"
    src.write_text(SRT, encoding="utf-8")
    vtt = convert.convert_subtitle(src, "vtt", dest_dir=tmp_path)
    body = vtt.read_text(encoding="utf-8")
    assert body.startswith("WEBVTT")
    assert "00:00:01.000 --> 00:00:02.500" in body  # dot ms, no index
    assert "Hello world" in body

    # VTT back to SRT restores index + comma ms
    back = convert.convert_subtitle(vtt, "srt", dest_dir=tmp_path / "b")
    srt = back.read_text(encoding="utf-8")
    assert "1\n00:00:01,000 --> 00:00:02,500\nHello world" in srt

    # to plain text = just the cue bodies, in order
    txt = convert.convert_subtitle(src, "txt", dest_dir=tmp_path / "t")
    assert txt.read_text(encoding="utf-8").strip() == "Hello world\nSecond line"


def test_convert_router_handles_subtitles_and_text_pdf(tmp_path):
    src = tmp_path / "s.srt"
    src.write_text(SRT, encoding="utf-8")
    assert convert.convert(src, "vtt", dest_dir=tmp_path).suffix == ".vtt"
    assert convert.convert(src, "txt", dest_dir=tmp_path).suffix == ".txt"  # srt->txt


def test_text_to_pdf_and_pdf_to_text_round_trip(tmp_path):
    pytest.importorskip("reportlab")
    pytest.importorskip("pypdf")
    txt = tmp_path / "note.txt"
    txt.write_text("Prod runs in us-east-1\nCache uses Redis\n", encoding="utf-8")
    pdf = convert.convert(txt, "pdf", dest_dir=tmp_path)
    assert pdf.suffix == ".pdf" and pdf.exists()
    back = convert.convert(pdf, "txt", dest_dir=tmp_path / "x")
    assert "us-east-1" in back.read_text(encoding="utf-8")


def test_pdf_lib_absent_gives_a_clear_error(tmp_path, monkeypatch):
    import builtins

    real = builtins.__import__

    def no_pypdf(name, *a, **k):
        if name == "pypdf":
            raise ImportError("blocked")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_pypdf)
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    with pytest.raises(RuntimeError, match="pypdf is not installed"):
        convert.pdf_to_text(tmp_path / "a.pdf", dest_dir=tmp_path)
