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


# --- freehand (D189): points are fractions of an observed control's box ------


@pytest.mark.parametrize(
    "path",
    [
        None,  # freehand needs a path
        [[0.5, 0.5]],  # one point is not a stroke
        [[0, 0]] * (sketch.MAX_PATH + 1),
        [[0, 0], [1.6, 0.5]],  # beyond the margin around the box
        [[0, 0], [-0.6, 0.5]],
        [[0, 0], [500, 300]],  # a screen position, not a fraction
        [[0, 0], [0.5]],
        [[0, 0], ["0.5", 0.5]],
        [[0, 0], [True, 0.5]],
        [[0, 0], {"u": 0.5, "v": 0.5}],
        [[0, 0], (0.5, 0.5)],  # JSON gives lists; anything else is refused
        [[0, 0], [0.5, 0.5, 0.5]],
    ],
)
def test_a_freehand_path_is_only_box_fractions(path):
    item = {"kind": "freehand", "cid": "c1"}
    if path is not None:
        item["path"] = path
    with pytest.raises(sketch.SketchError):
        sketch.parse_marks({"marks": [item]}, _two())


def test_only_a_freehand_mark_has_a_path():
    with pytest.raises(sketch.SketchError):
        sketch.parse_marks(
            {"marks": [{"kind": "circle", "cid": "c1", "path": [[0, 0], [1, 1]]}]}, _two()
        )


def test_freehand_strokes_stay_on_the_control_and_follow_it():
    frame = _two()
    raw = {"marks": [{"kind": "freehand", "cid": "c1", "path": [[-0.5, 1.2], [0.5, 1.5], [1.5, 1.1]]}]}
    s = sketch.start(raw, frame, 0.0)
    (stroke,) = sketch.strokes(s, 10.0 * sketch.DRAW_S)
    # box 100..160 x 100..130 widened by half its size, plus the wobble
    assert _inside(stroke, (70, 85, 190, 145), sketch.WOBBLE_PX + 7)
    moved = sketch.follow(
        s,
        _frame(
            [
                _control(1, "Save", rect=(112, 108, 172, 138)),
                _control(2, "Open", rect=(300, 100, 360, 130)),
            ]
        ),
    )
    (after,) = sketch.strokes(moved, 10.0 * sketch.DRAW_S)
    assert after != stroke
    assert _inside(after, (82, 93, 202, 153), sketch.WOBBLE_PX + 7)


# --- draws while it talks (D189) ----------------------------------------------


def test_speech_says_the_instruction_and_stops_cleanly():
    from ghostcursor import speech

    calls = []
    voice = type("V", (), {"Speak": lambda self, text, flags: calls.append((text, flags))})()
    speaker = speech.Speaker(voice)
    speaker.say("  Click   Save ")
    assert speaker.wait()
    speaker.say("")
    speaker.stop()
    assert speaker.wait()
    assert calls == [("Click Save", 3), ("", 3)]
    speaker.close()
    assert speech.spoken("Step 2/5 (suggested): Click Save -- typed 4 characters") == "Click Save"
    assert speech.spoken("all steps done") == "all steps done"


def test_a_pc_without_a_voice_still_draws():
    from ghostcursor import speech

    def broken(self, *a):
        raise OSError("no SAPI")

    speaker = speech.Speaker(type("V", (), {"Speak": broken})())
    speaker.say("Click Save")
    speaker.stop()
    assert speaker.wait()
    speaker.close()


def test_a_slow_voice_never_holds_the_teach_loop():
    # FOLLOWUPS (D189-D191 review): SAPI Speak ran on the Teach loop thread,
    # and a first call can block while the audio device starts.
    import threading
    import time

    from ghostcursor import speech

    release = threading.Event()
    voice = type("V", (), {"Speak": lambda self, text, flags: release.wait(5)})()
    speaker = speech.Speaker(voice)
    started = time.perf_counter()
    speaker.say("Click Save")
    speaker.say("Click Close")
    speaker.stop()
    assert time.perf_counter() - started < 0.05
    release.set()
    assert speaker.wait()
    speaker.close()
    speaker._thread.join(2)
    assert not speaker._thread.is_alive()


def test_esc_silences_the_voice(monkeypatch):
    from ghostcursor.harness import teach_live
    from tests.test_harness_spatial_voice import W1

    class Session:
        completed = []

        def __init__(self, *a, **kw):
            pass

        def stop(self):
            pass

    stopped = []
    speaker = type("S", (), {"say": lambda self, t: None, "stop": lambda self: stopped.append(1)})()
    monkeypatch.setattr(teach_live, "bind", lambda hwnds: (W1,))
    monkeypatch.setattr(teach_live.Observer, "start", lambda self: None)
    monkeypatch.setattr(teach_live, "ModelTeachSession", Session)
    monkeypatch.setattr(teach_live, "_escape_pressed", lambda: True)
    monkeypatch.setattr(teach_live.window, "create_overlay_window", lambda **k: "overlay")
    monkeypatch.setattr(teach_live.window, "destroy_overlay_window", lambda o: None)
    teach_live.run_model_teach(
        "g", [11], seconds=60, gateway=object(), say=lambda m: None, speak=True, speaker=speaker
    )
    assert stopped == [1]


def test_freehand_on_a_big_pane_stays_within_40_px_of_it():
    pane = _frame([_control(1, "Document", rect=(0, 0, 1600, 900))])
    raw = {"marks": [{"kind": "freehand", "cid": "c1", "path": [[-0.5, -0.5], [1.5, 1.5]]}]}
    (stroke,) = sketch.strokes(sketch.start(raw, pane, 0.0), 2.0)
    margin = 40 + sketch.WOBBLE_PX + 7  # the literal limit, not the constant under test
    assert all(-margin <= x <= 1600 + margin and -margin <= y <= 900 + margin for x, y in stroke)
