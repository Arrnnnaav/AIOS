"""Redacted pictures of the bound windows for Jev (D179).

Sent only when the user turned it on, and only when the text-only choice
failed for a step (Jev abstained, was unsure, or two controls look alike).
What leaves the machine is not a screenshot: each picture starts grey, and
only the pixels of observed controls that are interface chrome (buttons,
menu items, tabs, check boxes...) are copied in. Text fields, lists, tree
items, document names, title bars and everything between controls stay
grey. Every option is outlined and tagged with its id, so Jev answers with an
id -- the pointer is still drawn only at an observed control (rule 3).

Nothing here is written to disk.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from ghostcursor.harness.frame import ObservationFrame, Rect, reveals_document

#: Only these keep their pixels; the rest of the window is grey.
CHROME_TYPES = frozenset(
    {
        "Button",
        "SplitButton",
        "MenuItem",
        "TabItem",
        "CheckBox",
        "RadioButton",
        "Hyperlink",
    }
)
#: A control bigger than this share of its window stays grey: it may hold content.
MAX_SHOWN_SHARE = 0.15
GREY = (128, 128, 128)
MARK = (255, 64, 160)
#: TypeSafe image limits (docs.typesafe.ai/images): each side 280..1568 px.
MAX_SIDE, MIN_SIDE = 1568, 280
JPEG_QUALITY = 85


def grab_screen(rect: Rect) -> Image.Image:
    import mss

    left, top, right, bottom = rect
    with mss.mss() as screen:  # one per call: mss is not shared across threads
        shot = screen.grab(
            {"left": left, "top": top, "width": right - left, "height": bottom - top}
        )
    return Image.frombytes("RGB", shot.size, shot.rgb)


def shown(candidate, window: Rect, title: str) -> bool:
    """Whether this control's own pixels may appear in the picture."""

    left, top, right, bottom = candidate.rect
    area = max(1, (window[2] - window[0]) * (window[3] - window[1]))
    return (
        candidate.control_type in CHROME_TYPES
        and not reveals_document(candidate.name, candidate.control_type, title)
        and (right - left) * (bottom - top) <= MAX_SHOWN_SHARE * area
    )


def redact(frame: ObservationFrame, label: str, screen: Image.Image) -> Image.Image:
    """``screen`` is the window's pixels; the result is grey but for chrome
    controls, with every candidate outlined and tagged."""

    window = dict(frame.window_rects)[label]
    title = next((t for lab, t, _ in frame.facts if lab == label), "")
    ox, oy = window[0], window[1]
    picture = Image.new("RGB", screen.size, GREY)
    mine = [c for c in frame.candidates if c.window == label]
    for c in mine:
        if shown(c, window, title):
            box = (  # clipped to the window: nothing outside it is copied
                max(0, c.rect[0] - ox),
                max(0, c.rect[1] - oy),
                min(screen.width, c.rect[2] - ox),
                min(screen.height, c.rect[3] - oy),
            )
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            picture.paste(screen.crop(box), box[:2])
    picture = _fit(picture)
    scale = picture.width / screen.width
    draw = ImageDraw.Draw(picture)
    font = ImageFont.load_default(size=13)
    for c in mine:
        box = [
            round((c.rect[0] - ox) * scale),
            round((c.rect[1] - oy) * scale),
            round((c.rect[2] - ox) * scale),
            round((c.rect[3] - oy) * scale),
        ]
        draw.rectangle(box, outline=MARK, width=2)
        tag = draw.textbbox((box[0], box[1]), c.cid, font=font)
        draw.rectangle(tag, fill=MARK)
        draw.text((box[0], box[1]), c.cid, fill=(255, 255, 255), font=font)
    return picture


def _fit(picture: Image.Image) -> Image.Image:
    longest = max(picture.size)
    if longest > MAX_SIDE:
        ratio = MAX_SIDE / longest
        picture = picture.resize(
            (
                max(1, round(picture.width * ratio)),
                max(1, round(picture.height * ratio)),
            ),
            Image.LANCZOS,
        )
    if min(picture.size) < MIN_SIDE:  # pad, never stretch
        padded = Image.new(
            "RGB", (max(MIN_SIDE, picture.width), max(MIN_SIDE, picture.height)), GREY
        )
        padded.paste(picture, (0, 0))
        picture = padded
    return picture


def pictures(frame: ObservationFrame, grab=grab_screen) -> dict[str, bytes]:
    """One redacted JPEG per bound, open window that has candidates."""

    out = {}
    for label, window in frame.window_rects:
        if label in frame.minimized or not any(
            c.window == label for c in frame.candidates
        ):
            continue
        buffer = io.BytesIO()
        redact(frame, label, grab(window)).save(
            buffer, "JPEG", quality=JPEG_QUALITY, progressive=False
        )
        out[label] = buffer.getvalue()
    return out
