"""Local file conversion (D186): the core of Open-Tangerine's toolbox
(sintaxerrorpvtltd/Open-Tangerine, GPL-3.0; macOS), ported to Windows the
local-first way. Converts files on THIS machine -- no account, no upload, no
item limit; output lands beside the source by default. Images use Pillow
(already an Orbyn dependency); media conversions are delegated to FFmpeg when the
user has it installed (optional, exactly as Open-Tangerine does), else a clear
error. Nothing leaves the device (rule 6).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

# target extension -> (Pillow format, needs an opaque RGB frame)
_IMAGE = {
    "png": ("PNG", False),
    "jpg": ("JPEG", True),
    "jpeg": ("JPEG", True),
    "webp": ("WEBP", False),
    "bmp": ("BMP", True),
    "tiff": ("TIFF", False),
    "gif": ("GIF", False),
}
_MEDIA = {"mp3", "wav", "m4a", "flac", "ogg", "mp4", "mov", "mkv", "webm"}
_SUBTITLE = {"srt", "vtt"}  # SRT/VTT; "txt" is a text target handled in convert()


def _dest(src: Path, ext: str, dest_dir: Path | None) -> Path:
    """Output beside the source (or in dest_dir), never clobbering an existing
    file. The name comes from the source stem + the target extension -- never
    from untrusted content, so no path traversal."""

    directory = dest_dir or src.parent
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{src.stem}.{ext}"
    n = 1
    while path.exists() and path.resolve() != src.resolve():
        n += 1
        path = directory / f"{src.stem} ({n}).{ext}"
    return path


def convert_image(src, to: str, *, dest_dir=None, quality: int | None = None) -> Path:
    """Convert an image to ``to`` (png/jpeg/webp/bmp/tiff/gif) with Pillow and
    return the output path. A format that can't hold transparency gets a white
    background flattened in. Local only."""

    from PIL import Image

    src = Path(src)
    to = to.lower().removeprefix(".")
    if to not in _IMAGE:
        raise ValueError(f"image target must be one of {sorted(_IMAGE)}")
    fmt, needs_rgb = _IMAGE[to]
    with Image.open(src) as im:
        if needs_rgb and im.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", im.size, (255, 255, 255))
            frame = im.convert("RGBA")
            background.paste(frame, mask=frame.split()[-1])
            im = background
        elif im.mode == "P":
            im = im.convert("RGB")
        out = _dest(src, to, Path(dest_dir) if dest_dir else None)
        kwargs = {}
        if fmt in ("JPEG", "WEBP"):
            kwargs["quality"] = quality if quality is not None else 90
        im.save(out, fmt, **kwargs)
    return out


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def convert_media(src, to: str, *, dest_dir=None) -> Path:
    """Convert audio/video via FFmpeg (optional, user-installed -- as in
    Open-Tangerine). Raises a clear error if FFmpeg is not on PATH. Local only."""

    src = Path(src)
    to = to.lower().removeprefix(".")
    if to not in _MEDIA:
        raise ValueError(f"media target must be one of {sorted(_MEDIA)}")
    if not ffmpeg_available():
        raise RuntimeError(
            "FFmpeg is not installed. Install it (e.g. winget install Gyan.FFmpeg) "
            "to convert audio/video; image conversion needs nothing extra."
        )
    out = _dest(src, to, Path(dest_dir) if dest_dir else None)
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), str(out)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr.strip().splitlines()[-1:]}")
    return out



#: One cue timestamp, either SRT ("," ms) or VTT ("." ms).
_CUE = re.compile(
    r"(\d{2}:\d{2}:\d{2})[.,](\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2})[.,](\d{3})"
)


def _parse_cues(text: str) -> list[tuple[str, str, str]]:
    """Parse SRT or VTT into (start, end, body) cues, ms held as ',' (SRT form).
    Pure Python -- no dependency. A WEBVTT header and SRT index lines are
    dropped; blocks without a valid timestamp line are skipped."""

    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"\AWEBVTT[^\n]*\n(?:[^\n]*\n)*?\n", "", text)  # drop VTT header
    cues = []
    for block in re.split(r"\n[ \t]*\n", text):
        lines = [ln for ln in block.strip().splitlines() if ln.strip()]
        if lines and lines[0].strip().isdigit():  # SRT index line
            lines = lines[1:]
        if not lines:
            continue
        m = _CUE.match(lines[0])
        if not m:
            continue
        start = f"{m.group(1)},{m.group(2)}"
        end = f"{m.group(3)},{m.group(4)}"
        cues.append((start, end, "\n".join(lines[1:]).strip()))
    return cues


def convert_subtitle(src, to: str, *, dest_dir=None) -> Path:
    """Convert a subtitle file between SRT, VTT and plain text. Pure Python,
    local only."""

    src = Path(src)
    to = to.lower().removeprefix(".")
    if to not in {"srt", "vtt", "txt"}:
        raise ValueError("subtitle target must be srt, vtt or txt")
    cues = _parse_cues(src.read_text(encoding="utf-8", errors="replace"))
    if to == "txt":
        body = "\n".join(c[2] for c in cues if c[2])
    elif to == "vtt":
        body = "WEBVTT\n\n" + "\n\n".join(
            f"{s.replace(',', '.')} --> {e.replace(',', '.')}\n{t}" for s, e, t in cues
        )
    else:  # srt
        body = "\n\n".join(
            f"{i}\n{s} --> {e}\n{t}" for i, (s, e, t) in enumerate(cues, 1)
        )
    out = _dest(src, to, Path(dest_dir) if dest_dir else None)
    out.write_text(body + "\n", encoding="utf-8", newline="\n")
    return out


def pdf_to_text(src, *, dest_dir=None) -> Path:
    """Extract a PDF's text to a .txt (optional dep: pypdf). Local only."""

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is not installed; pip install pypdf") from exc
    src = Path(src)
    reader = PdfReader(str(src))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    out = _dest(src, "txt", Path(dest_dir) if dest_dir else None)
    out.write_text(text, encoding="utf-8", newline="\n")
    return out


def text_to_pdf(src, *, dest_dir=None) -> Path:
    """Render a text/subtitle file to a simple PDF (optional dep: reportlab)."""

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError("reportlab is not installed; pip install reportlab") from exc
    src = Path(src)
    out = _dest(src, "pdf", Path(dest_dir) if dest_dir else None)
    pdf = canvas.Canvas(str(out), pagesize=letter)
    y = 750
    for line in src.read_text(encoding="utf-8", errors="replace").splitlines():
        pdf.drawString(40, y, line[:120])
        y -= 14
        if y < 40:
            pdf.showPage()
            y = 750
    pdf.save()
    return out


def convert(src, to: str, *, dest_dir=None) -> Path:
    """Convert ``src`` to format ``to``: images (Pillow), media (FFmpeg),
    subtitles (SRT/VTT/txt, pure Python), and PDF<->text (optional pypdf/
    reportlab). Returns the output path. Local only."""

    to = to.lower().removeprefix(".")
    src_ext = Path(src).suffix.lower().removeprefix(".")
    if to in _IMAGE:
        return convert_image(src, to, dest_dir=dest_dir)
    if to in _MEDIA:
        return convert_media(src, to, dest_dir=dest_dir)
    if to in _SUBTITLE:
        return convert_subtitle(src, to, dest_dir=dest_dir)
    if to == "pdf" and src_ext in ({"txt"} | _SUBTITLE):
        return text_to_pdf(src, dest_dir=dest_dir)
    if to == "txt":
        if src_ext == "pdf":
            return pdf_to_text(src, dest_dir=dest_dir)
        if src_ext in _SUBTITLE:
            return convert_subtitle(src, "txt", dest_dir=dest_dir)
    raise ValueError(f"unsupported conversion {src_ext or '?'} -> {to}")
