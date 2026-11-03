"""Hand-drawn marks (harness/sketch.py): the model names observed controls,
never positions; strokes follow the control and vanish when it is lost."""

from __future__ import annotations

import pytest

from ghostcursor.harness import sketch
from tests.test_harness_frame import _control, _frame


def _two():
    return _frame(
        [
            _control(1, "Save", rect=(100, 100, 160, 130)),
            _control(2, "Open", rect=(300, 100, 360, 130)),
        ]
    )


def _ids(frame):
    return frame.ids[0], frame.ids[1]


def _inside(points, rect, margin):
    left, top, right, bottom = rect
    return all(
        left - margin <= x <= right + margin and top - margin <= y <= bottom + margin
        for x, y in points
    )


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {"marks": []},
        {"marks": [{"kind": "circle", "cid": "c99"}]},
        {"marks": [{"kind": "circle", "cid": "c1", "x": 10, "y": 10}]},
        {"marks": [{"kind": "spiral", "cid": "c1"}]},
        {"marks": [{"kind": "circle", "cid": "c1", "to": "c2"}]},
        {"marks": [{"kind": "arrow", "cid": "c1", "to": "c1"}]},
        {"marks": [{"kind": "arrow", "cid": "c1", "to": "c99"}]},
        {"marks": [{"kind": "circle", "cid": "c1"}] * (sketch.MAX_MARKS + 1)},
        {
            "marks": [
                {"kind": "circle", "cid": "c1", "note": "x" * (sketch.MAX_NOTE + 1)}
            ]
        },
        {"marks": [{"kind": "circle", "cid": "c1"}], "at": [5, 5]},
    ],
)
def test_anything_but_observed_ids_is_refused(raw):
    frame = _two()
    if isinstance(raw, dict):  # write the frame's real ids in
        for mark in raw.get("marks", []):
            mark.update(
                {
                    k: {"c1": frame.ids[0], "c2": frame.ids[1]}.get(v, v)
                    for k, v in mark.items()
                    if k in ("cid", "to")
                }
            )
    with pytest.raises(sketch.SketchError):
        sketch.parse_marks(raw, frame)


def test_strokes_hug_the_observed_control_and_draw_in():
    frame = _two()
    a, b = _ids(frame)
    sk = sketch.start(
        {"marks": [{"kind": "circle", "cid": a}, {"kind": "underline", "cid": b}]},
        frame,
        0.0,
    )
    assert sketch.strokes(sk, 0.0) == ()
    half = sketch.strokes(sk, sketch.DRAW_S / 2)
    full = sketch.strokes(sk, sketch.DRAW_S * 2)
    assert len(half) == 1 and len(full) == 2
    assert len(half[0]) < len(full[0])
    assert _inside(full[0], (100, 100, 160, 130), 16)
    assert _inside(full[1], (300, 100, 360, 130), 12)
    assert full == sketch.strokes(sk, sketch.DRAW_S * 2)  # same wobble every frame


def test_arrow_runs_between_the_two_controls():
    frame = _two()
    a, b = _ids(frame)
    sk = sketch.start(
        {"marks": [{"kind": "arrow", "cid": a, "to": b, "note": "then"}]}, frame, 0.0
    )
    shaft, *head = sketch.strokes(sk, 5.0)
    assert len(head) == 2
    assert shaft[0][0] <= 170 and shaft[-1][0] >= 290
    assert sketch.notes(sk, 5.0) == (("then", (300, 100, 360, 130)),)


def test_marks_follow_a_moved_control_and_vanish_when_it_is_lost():
    frame = _two()
    a, _ = _ids(frame)
    sk = sketch.start({"marks": [{"kind": "box", "cid": a}]}, frame, 0.0)
    moved = _frame(
        [
            _control(1, "Save", rect=(110, 105, 170, 135)),
            _control(2, "Open", rect=(300, 100, 360, 130)),
        ],
        frame_id=2,
    )
    followed = sketch.follow(sk, moved)
    assert followed is not None
    assert all(
        _inside(s, (110, 105, 170, 135), 12) for s in sketch.strokes(followed, 5.0)
    )
    gone = _frame([_control(2, "Open", rect=(300, 100, 360, 130))], frame_id=3)
    assert sketch.follow(followed, gone) is None


def test_a_sketch_expires():
    frame = _two()
    sk = sketch.start(
        {"marks": [{"kind": "circle", "cid": frame.ids[0], "note": "here"}]}, frame, 0.0
    )
    assert (
        sketch.strokes(sk, sketch.TTL_S) == () and sketch.notes(sk, sketch.TTL_S) == ()
    )


def test_start_places_marks_on_the_latest_frame():
    asked = _two()
    a = asked.ids[0]
    latest = _frame([_control(1, "Save", rect=(120, 100, 180, 130)), _control(2, "Open", rect=(300, 100, 360, 130))], frame_id=2)
    sk = sketch.start({"marks": [{"kind": "box", "cid": a}]}, asked, 0.0, latest=latest)
    assert sk.control(a).rect == (120, 100, 180, 130)
    gone = _frame([_control(2, "Open", rect=(300, 100, 360, 130))], frame_id=3)
    assert sketch.start({"marks": [{"kind": "box", "cid": a}]}, asked, 0.0, latest=gone) is None
