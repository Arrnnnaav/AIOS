"""Hand-drawn marks on observed controls: a cheap take on HeyClicky's
real-time graphics (1.1.1 "circles, points and sketches while it talks";
Excalidraw-style strokes since 1.0.40).

The model names WHAT to mark by candidate id from ``frame.model_view()``;
it never supplies a position (CLAUDE.md rule 3). Every stroke is computed
here from the observed rectangle, re-resolved against each new frame, and the
whole sketch disappears the moment any marked control can no longer be found
exactly once. Pure geometry: no Win32, so it runs anywhere and tests fast.

Skipped from HeyClicky: free-form polygons, photo cards and 3D models -- none
of them is anchored to an observed control.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace

from ghostcursor.harness.frame import Candidate, ObservationFrame, resolve

KINDS = ("circle", "underline", "box", "arrow")
MAX_MARKS = 6
MAX_NOTE = 60
#: Seconds each mark takes to draw in; marks draw one after another.
DRAW_S = 0.45
#: How long a sketch stays up unless cleared first (speech ending clears it).
TTL_S = 8.0
#: Wobble of a hand-drawn stroke, in pixels.
WOBBLE_PX = 3.0

Point = tuple[int, int]
Stroke = tuple[Point, ...]


class SketchError(ValueError):
    pass


@dataclass(frozen=True)
class Mark:
    kind: str
    cid: str
    to: str | None = None  # arrow only: the control it points at
    note: str = ""


@dataclass(frozen=True)
class Sketch:
    marks: tuple[Mark, ...]
    #: The observed controls, by cid, as of the last frame that found them.
    controls: tuple[tuple[str, Candidate], ...]
    started: float
    seed: int = 0
    ttl_s: float = TTL_S

    def control(self, cid: str) -> Candidate:
        return dict(self.controls)[cid]

    def expired(self, now: float) -> bool:
        return now - self.started >= self.ttl_s


def parse_marks(raw: object, frame: ObservationFrame) -> tuple[Mark, ...]:
    """The model's ``{"marks": [...]}`` as Marks, or SketchError. Closed
    schema: an unknown key, kind or candidate id refuses the whole sketch."""

    if not isinstance(raw, dict) or set(raw) != {"marks"}:
        raise SketchError('expected exactly {"marks": [...]}')
    items = raw["marks"]
    if not isinstance(items, list) or not 0 < len(items) <= MAX_MARKS:
        raise SketchError(f"between 1 and {MAX_MARKS} marks")
    known = set(frame.ids)
    marks = []
    for item in items:
        if not isinstance(item, dict) or not set(item) <= {"kind", "cid", "to", "note"}:
            raise SketchError("a mark has only kind, cid, to and note")
        kind, cid = item.get("kind"), item.get("cid")
        to, note = item.get("to"), item.get("note", "")
        if kind not in KINDS:
            raise SketchError(f"unknown mark kind {kind!r}")
        if not isinstance(cid, str) or cid not in known:
            raise SketchError("a mark must name an observed control")
        if to is not None and (
            kind != "arrow" or not isinstance(to, str) or to not in known or to == cid
        ):
            raise SketchError(
                "only an arrow has a 'to', and it names another observed control"
            )
        if not isinstance(note, str) or len(note) > MAX_NOTE:
            raise SketchError(f"a note is text of at most {MAX_NOTE} characters")
        marks.append(Mark(kind, cid, to, note.strip()))
    return tuple(marks)


def start(
    raw: object,
    frame: ObservationFrame,
    now: float,
    *,
    latest: ObservationFrame | None = None,
    seed: int = 0,
) -> Sketch | None:
    """Marks named against ``frame`` (the one the model was shown), placed on
    ``latest`` when given: a model answer takes seconds, and its frame's
    rectangles may be old. None if a marked control did not survive."""

    marks = parse_marks(raw, frame)
    cids = {m.cid for m in marks} | {m.to for m in marks if m.to}
    sketch = Sketch(
        marks, tuple((cid, frame.get(cid)) for cid in sorted(cids)), now, seed
    )
    return sketch if latest is None else follow(sketch, latest)


def follow(sketch: Sketch, latest: ObservationFrame) -> Sketch | None:
    """The sketch moved onto the latest frame, or None if any marked control
    is gone, ambiguous or jumped: never draw at an old rectangle."""

    moved = []
    for cid, chosen in sketch.controls:
        current = resolve(chosen, latest)
        if current is None:
            return None
        moved.append((cid, current))
    return replace(sketch, controls=tuple(moved))


def _wobble(rng: random.Random):
    """A smooth, low-frequency offset: two sines with random phases."""

    a, b = rng.uniform(0, math.tau), rng.uniform(0, math.tau)
    return lambda t: (
        WOBBLE_PX * (0.6 * math.sin(t * 2.0 + a) + 0.4 * math.sin(t * 5.0 + b))
    )


def _line(p: tuple[float, float], q: tuple[float, float], rng, steps: int = 16) -> list:
    """A slightly bowed line, the way a hand draws a straight one."""

    w = _wobble(rng)
    (x0, y0), (x1, y1) = p, q
    length = math.hypot(x1 - x0, y1 - y0) or 1.0
    nx, ny = -(y1 - y0) / length, (x1 - x0) / length
    out = []
    for i in range(steps + 1):
        t = i / steps
        off = w(t * 3) + math.sin(t * math.pi) * min(6.0, length * 0.03)
        out.append((x0 + (x1 - x0) * t + nx * off, y0 + (y1 - y0) * t + ny * off))
    return out


def _edge(rect, toward: tuple[float, float]) -> tuple[float, float]:
    """Where the line from the rectangle's centre toward a point leaves it."""

    left, top, right, bottom = rect
    cx, cy = (left + right) / 2, (top + bottom) / 2
    dx, dy = toward[0] - cx, toward[1] - cy
    if dx == dy == 0:
        return cx, cy
    sx = (right - left) / 2 / abs(dx) if dx else math.inf
    sy = (bottom - top) / 2 / abs(dy) if dy else math.inf
    s = min(sx, sy)
    return cx + dx * s, cy + dy * s


def _strokes_for(mark: Mark, sketch: Sketch, rng: random.Random) -> list[list]:
    left, top, right, bottom = sketch.control(mark.cid).rect
    cx, cy = (left + right) / 2, (top + bottom) / 2
    if mark.kind == "circle":
        rx, ry = (right - left) / 2 + 10, (bottom - top) / 2 + 8
        w, begin = _wobble(rng), rng.uniform(0, math.tau)
        sweep = math.tau * 1.08  # overshoot past the start, like a pen
        return [
            [
                (
                    cx + (rx + w(t)) * math.cos(begin + t),
                    cy + (ry + w(t)) * math.sin(begin + t),
                )
                for t in (sweep * i / 40 for i in range(41))
            ]
        ]
    if mark.kind == "underline":
        return [_line((left - 4, bottom + 5), (right + 6, bottom + 4), rng)]
    if mark.kind == "box":
        l, t, r, b = left - 6, top - 6, right + 6, bottom + 6
        corners = [(l, t), (r, t), (r, b), (l, b), (l, t)]
        return [_line(corners[i], corners[i + 1], rng, 8) for i in range(4)]
    # arrow: from the other control (or from up-left) to this one's edge
    if mark.to is None:
        origin = (left - 70, top - 50)
        tip = _edge((left, top, right, bottom), origin)
    else:
        tl, tt, tr, tb = sketch.control(mark.to).rect
        origin = _edge((left, top, right, bottom), ((tl + tr) / 2, (tt + tb) / 2))
        tip = _edge((tl, tt, tr, tb), (cx, cy))
    shaft = _line(origin, tip, rng)
    angle = math.atan2(tip[1] - shaft[-3][1], tip[0] - shaft[-3][0])
    head = [
        [(tip[0] - 14 * math.cos(angle + s), tip[1] - 14 * math.sin(angle + s)), tip]
        for s in (0.45, -0.45)
    ]
    return [shaft, *head]


def strokes(sketch: Sketch, now: float) -> tuple[Stroke, ...]:
    """Every polyline visible at ``now``: marks draw in one after another over
    DRAW_S each, and nothing is visible once the sketch has expired."""

    if sketch.expired(now):
        return ()
    elapsed = now - sketch.started
    out = []
    for index, mark in enumerate(sketch.marks):
        progress = (elapsed - index * DRAW_S) / DRAW_S
        if progress <= 0:
            break
        rng = random.Random(f"{sketch.seed}:{index}")  # same wobble every frame
        parts = _strokes_for(mark, sketch, rng)
        total = sum(len(p) for p in parts)
        budget = total if progress >= 1 else max(2, int(total * progress))
        for part in parts:
            if budget < 2:
                break
            shown = part[:budget]
            budget -= len(shown)
            out.append(tuple((round(x), round(y)) for x, y in shown))
    return tuple(out)


def notes(
    sketch: Sketch, now: float
) -> tuple[tuple[str, tuple[int, int, int, int]], ...]:
    """(text, anchor rectangle) for each fully drawn mark that has a note."""

    if sketch.expired(now):
        return ()
    elapsed = now - sketch.started
    return tuple(
        (mark.note, sketch.control(mark.to or mark.cid).rect)
        for index, mark in enumerate(sketch.marks)
        if mark.note and elapsed >= (index + 1) * DRAW_S
    )
