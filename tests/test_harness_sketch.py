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


def test_teach_sketch_draws_the_step_and_an_arrow_only_from_where_the_last_one_is(monkeypatch):
    from ghostcursor.harness import teach_live

    drawn = []
    monkeypatch.setattr(teach_live.window, "set_sketch", lambda o, s, n=(): drawn.append(s))
    monkeypatch.setattr(teach_live.window, "clear_sketch", lambda o: drawn.append(None))
    frame = _two()
    save, open_ = frame.candidates
    marks, prev = teach_live._sketch_step(None, None, None, save, frame)
    assert [m.kind for m in marks.marks] == ["circle"]
    marks, prev = teach_live._sketch_step(None, marks, prev, open_, frame)
    assert [m.kind for m in marks.marks] == ["arrow", "circle"] and prev == save
    # The last step's control is gone: the next step gets no arrow tail.
    only_open = _frame([_control(2, "Open", rect=(300, 100, 360, 130))], frame_id=2)
    third = _frame([_control(3, "Close", rect=(500, 100, 560, 130))], frame_id=3)
    marks, prev = teach_live._sketch_step(None, marks, prev, third.candidates[0], only_open)
    assert [m.kind for m in marks.marks] == ["arrow", "circle"]  # tail: Open, still there
    marks, prev = teach_live._sketch_step(None, None, save, third.candidates[0], third)
    assert [m.kind for m in marks.marks] == ["circle"]  # Save is not in the frame
    assert teach_live._sketch_step(None, marks, prev, None, third)[0] is None and drawn[-1] is None


def test_teach_sketch_has_no_self_arrow_and_clears_when_its_control_is_lost(monkeypatch):
    from ghostcursor.harness import teach_live

    monkeypatch.setattr(teach_live.window, "set_sketch", lambda o, s, n=(): None)
    monkeypatch.setattr(teach_live.window, "clear_sketch", lambda o: None)
    frame = _two()
    save = frame.candidates[0]
    assert [m.kind for m in sketch.for_step(save, save, 0.0).marks] == ["circle"]
    marks, prev = teach_live._sketch_step(None, None, None, save, frame)
    lost = _frame([_control(2, "Open", rect=(300, 100, 360, 130))], frame_id=2)
    assert teach_live._sketch_step(None, marks, prev, save, lost)[0] is None
