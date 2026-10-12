"""A spatial reference for model-driven Teach: "I mean this one" (D143, D171).

The user points at the screen; the harness resolves the mark LOCALLY to the
observed candidates under it and remembers them by identity (window + runtime
id), never by position. A model sees only the current frame-local ids of those
candidates, as tainted context. The mark is context, never authority: it does
not choose, it does not draw, and the deterministic gate is unchanged -- a
pointer is still shown only at an observed control the gate accepted.

Mark scoring is ported from Spatial (``D:\\PROJECTS\\Spatial``,
``server/app/resolver.py::resolve_marks``, same author), reduced to what a
desktop frame needs: one mark against UIA candidates. Rectangles and the
screen point never leave the machine.
"""

from __future__ import annotations

from dataclasses import dataclass

from ghostcursor.harness.frame import Candidate, ObservationFrame, Rect
from ghostcursor.providers.envelope import Tainted

#: Ranked candidates kept per mark (Spatial keeps 8).
MAX_RANKED = 8
#: Below this a candidate is not "under" the mark (Spatial's threshold).
MIN_SCORE = 0.10


def mark_score(mark: Rect, rect: Rect) -> float:
    """Spatial's anchor score: IoU, overlap either way, a point inside the
    control, or the control wholly inside the mark -- whichever is highest."""

    mx, my, mr, mb = mark
    ax, ay, ar, ab = rect
    mark_area = (mr - mx) * (mb - my)
    anchor_area = (ar - ax) * (ab - ay)
    inter = max(0, min(mr, ar) - max(mx, ax)) * max(0, min(mb, ab) - max(my, ay))
    union = mark_area + anchor_area - inter
    cx, cy = (mx + mr) / 2, (my + mb) / 2
    contains_center = ax <= cx <= ar and ay <= cy <= ab
    contains_anchor = mx <= ax and my <= ay and mr >= ar and mb >= ab and mark_area
    return max(
        inter / union if union else 0.0,
        min(0.94, (inter / mark_area) * 0.9) if mark_area else 0.0,
        min(0.95, (inter / anchor_area) * 0.95) if anchor_area else 0.0,
        0.95 if contains_center and not mark_area else 0.0,
        0.96 if contains_anchor else 0.0,
    )


@dataclass(frozen=True)
class SpatialReference:
    """The candidates a mark resolved to, by identity, best first."""

    under: tuple[tuple[str, tuple[int, ...]], ...]  # (window label, runtime id)

    @staticmethod
    def from_mark(mark: Rect, frame: ObservationFrame) -> "SpatialReference":
        """Rank the frame's candidates under ``mark`` (screen px; a point is a
        zero-size rect). Ties: higher score, then longer name (more specific),
        then smaller area -- Spatial's ranking rule."""

        scored = [(mark_score(mark, c.rect), c) for c in frame.candidates]
        ranked = sorted(
            ((s, c) for s, c in scored if s >= MIN_SCORE),
            key=lambda item: (
                -round(item[0], 6),
                -len(item[1].name),
                (item[1].rect[2] - item[1].rect[0])
                * (item[1].rect[3] - item[1].rect[1]),
            ),
        )
        return SpatialReference(
            tuple((c.window, c.runtime_id) for _, c in ranked[:MAX_RANKED])
        )

    def current(self, frame: ObservationFrame) -> tuple[Candidate, ...]:
        """The marked controls still present, by identity, in rank order."""

        present = {(c.window, c.runtime_id): c for c in frame.candidates}
        return tuple(present[key] for key in self.under if key in present)

    def model_view(self, frame: ObservationFrame) -> list[Tainted]:
        """Only frame-local ids, best first; tainted like all screen-derived data."""

        return [Tainted.of("user_mark", c.cid) for c in self.current(frame)]


def point(x: int, y: int) -> Rect:
    return (x, y, x, y)
