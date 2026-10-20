"""Local file conversion (D186): the core of Open-Tangerine's toolbox
(sintaxerrorpvtltd/Open-Tangerine, GPL-3.0; macOS), ported to Windows the
local-first way. Converts files on THIS machine -- no account, no upload, no
item limit; output lands beside the source by default. Images use Pillow
(already an Orbyn dependency); media conversions are delegated to FFmpeg when the
user has it installed (optional, exactly as Open-Tangerine does), else a clear
error. Nothing leaves the device (rule 6).
"""

from __future__ import annotations

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


def convert(src, to: str, *, dest_dir=None) -> Path:
    """Convert ``src`` to format ``to``, routing images to Pillow and media to
    FFmpeg. Returns the output path."""

    to = to.lower().removeprefix(".")
    if to in _IMAGE:
        return convert_image(src, to, dest_dir=dest_dir)
    if to in _MEDIA:
        return convert_media(src, to, dest_dir=dest_dir)
    raise ValueError(f"unsupported target format '{to}'")
