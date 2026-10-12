"""Spatial point reference and SayStride voice draft in model-Teach (D171).

Properties: a mark resolves locally, by identity, to observed candidates; a
model sees only their frame-local ids as tainted data, never a rectangle or the
screen point; the mark never chooses or draws (the gate is unchanged); voice
cleanup drops Whisper hallucinations and fillers.
"""

from __future__ import annotations

import json

from ghostcursor.harness import (
    Identity,
    RawControl,
    WindowObservation,
    bind,
    build_frame,
)
from ghostcursor.harness.spatial import SpatialReference, mark_score, point
from ghostcursor.harness.teach import ModelTeachSession, Verdict, gate
from ghostcursor.providers import ABSTAIN, Choice
from ghostcursor.voice import filter_whisper, strip_fillers

IDS = {11: Identity(1, "powerpnt.exe", "16")}
(W1,) = bind([11], identify_window=IDS.get, own_pid=999)


def _frame(shift=0, frame_id=1, with_insert=True):
    controls = [
        RawControl(
            (42, 2), "Home", "TabItem", (10 + shift, 10, 60 + shift, 40), True, False
        ),
    ]
    if with_insert:
        controls.append(
            RawControl(
                (42, 1),
                "Insert",
                "TabItem",
                (70 + shift, 10, 130 + shift, 40),
                True,
                False,
            )
        )
    return build_frame(
        frame_id, 0.0, [WindowObservation(W1, (0, 0, 900, 600), tuple(controls))]
    )


def test_a_point_resolves_to_the_control_under_it():
    frame = _frame()
    mark = SpatialReference.from_mark(point(100, 25), frame)
    assert [c.name for c in mark.current(frame)] == ["Insert"]
    assert SpatialReference.from_mark(point(500, 500), frame).current(frame) == ()


def test_scoring_matches_spatial_rules():
    assert mark_score(point(5, 5), (0, 0, 10, 10)) == 0.95  # point inside
    assert mark_score((0, 0, 100, 100), (10, 10, 20, 20)) == 0.96  # control inside mark
    assert mark_score(point(50, 50), (0, 0, 10, 10)) == 0.0


def test_the_mark_follows_identity_not_position():
    mark = SpatialReference.from_mark(point(100, 25), _frame())
    moved = _frame(shift=200, frame_id=2)
    assert [c.name for c in mark.current(moved)] == ["Insert"]
    assert mark.current(_frame(frame_id=3, with_insert=False)) == ()


def test_a_model_sees_only_ids_never_rectangles_or_the_point():
    frame = _frame()
    mark = SpatialReference.from_mark(point(100, 25), frame)
    session = ModelTeachSession("add a slide", gateway=None, mark=mark)
    envelope = session._envelope(frame)
    sent = envelope.tainted_json()
    assert [t.text for t in envelope.tainted["user_pointed_at"]] == [
        frame.candidates[1].cid
    ]
    assert "user_mark" in envelope.trusted
    for leaked in ("130", "[70", "(42", "runtime"):
        assert leaked not in sent
    assert "100" not in json.dumps(envelope.trusted)


def test_no_mark_or_a_vanished_mark_adds_nothing():
    frame = _frame()
    assert (
        "user_pointed_at" not in ModelTeachSession("g", None)._envelope(frame).tainted
    )
    mark = SpatialReference.from_mark(point(100, 25), frame)
    gone = _frame(frame_id=2, with_insert=False)
    envelope = ModelTeachSession("g", None, mark=mark)._envelope(gone)
    assert (
        "user_pointed_at" not in envelope.tainted
        and "user_mark" not in envelope.trusted
    )


def test_the_mark_never_lowers_the_gate():
    frame = _frame()
    marked = frame.candidates[1].cid
    verdict, _, _ = gate(Choice(marked, {marked: 0.5, ABSTAIN: 0.4}), frame, frame)
    assert verdict is Verdict.REASK


def test_voice_cleanup_drops_hallucinations_and_fillers():
    assert filter_whisper("Thank you.", None, 2.0) == ""
    segments = [
        {
            "text": " add a slide",
            "avg_logprob": -0.2,
            "no_speech_prob": 0.1,
            "compression_ratio": 1.1,
        },
        {"text": " thanks for watching", "avg_logprob": -0.2, "no_speech_prob": 0.1},
        {"text": " noise", "avg_logprob": -1.5},
    ]
    assert filter_whisper("", segments, 3.0) == "add a slide"
    assert filter_whisper("a " * 40, None, 2.0) == ""  # faster than anyone speaks
    assert strip_fillers("um, add add a uh slide") == "add a slide"


def test_a_mark_in_one_window_never_matches_a_twin_id_in_another():
    ids = {11: Identity(1, "powerpnt.exe", "16"), 22: Identity(2, "chrome.exe", "1")}
    w1, w2 = bind([11, 22], identify_window=ids.get, own_pid=999)
    same = (42, 1)
    frame = build_frame(
        1,
        0.0,
        [
            WindowObservation(w1, (0, 0, 400, 400), (RawControl(same, "Insert", "TabItem", (10, 10, 60, 40), True, False),)),
            WindowObservation(w2, (500, 0, 900, 400), (RawControl(same, "Insert", "TabItem", (510, 10, 560, 40), True, False),)),
        ],
    )
    mark = SpatialReference.from_mark(point(30, 25), frame)
    assert [c.window for c in mark.current(frame)] == ["w1"]
