"""Spatial point reference and SayStride voice draft in model-Teach (D171).

Properties: a mark resolves locally, by identity, to observed candidates; a
model sees only their frame-local ids as tainted data, never a rectangle or the
screen point; the mark never chooses or draws (the gate is unchanged); voice
cleanup drops Whisper hallucinations and fillers.
"""

from __future__ import annotations

import json

import pytest

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
from ghostcursor.voice import (
    apply_numbers,
    apply_spoken_commands,
    filter_whisper,
    strip_fillers,
)

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


def test_spoken_numbers_become_digits_in_the_goal():
    """apply_numbers cleans a spoken GOAL (rule-safe string transform, ported
    from SayStride): spoken numbers -> digits, with % and $ units."""

    assert apply_numbers("resize to twenty five percent") == "resize to 25%"
    assert apply_numbers("charge twenty dollars") == "charge $20"
    assert apply_numbers("two thousand twenty four rows") == "2024 rows"
    assert apply_numbers("about fifty thousand users") == "about 50,000 users"
    # small bare numbers under ten are left as words (not every "one" is a digit)
    assert apply_numbers("click the one button") == "click the one button"


def test_spoken_punctuation_commands_become_symbols():
    """apply_spoken_commands: spoken punctuation/formatting -> symbols, the
    dictation-app convention (local, deterministic)."""

    assert apply_spoken_commands("hello comma world") == "hello, world"
    assert apply_spoken_commands("done period") == "done."
    assert apply_spoken_commands("line one new line line two") == "line one\nline two"
    assert (
        apply_spoken_commands("part one new paragraph part two")
        == "part one\n\npart two"
    )
    assert apply_spoken_commands("really question mark") == "really?"
    assert apply_spoken_commands("wow exclamation mark") == "wow!"
    # combines with number conversion in the transcribe path
    assert (
        apply_spoken_commands(apply_numbers("charge twenty dollars period"))
        == "charge $20."
    )


def test_a_mark_in_one_window_never_matches_a_twin_id_in_another():
    ids = {11: Identity(1, "powerpnt.exe", "16"), 22: Identity(2, "chrome.exe", "1")}
    w1, w2 = bind([11, 22], identify_window=ids.get, own_pid=999)
    same = (42, 1)
    frame = build_frame(
        1,
        0.0,
        [
            WindowObservation(
                w1,
                (0, 0, 400, 400),
                (RawControl(same, "Insert", "TabItem", (10, 10, 60, 40), True, False),),
            ),
            WindowObservation(
                w2,
                (500, 0, 900, 400),
                (
                    RawControl(
                        same, "Insert", "TabItem", (510, 10, 560, 40), True, False
                    ),
                ),
            ),
        ],
    )
    mark = SpatialReference.from_mark(point(30, 25), frame)
    assert [c.window for c in mark.current(frame)] == ["w1"]


# --- take_mark: the point prompt keeps ESC and --seconds (review of D171) ---


class _Observer:
    def __init__(self, frame):
        self.frame = frame

    def latest(self):
        return self.frame


def _ticks(step=1.0):
    now = [0.0]

    def clock():
        now[0] += step
        return now[0]

    return clock


def test_esc_during_the_point_prompt_aborts_the_session():
    from ghostcursor.harness.teach_live import ABORTED, take_mark

    result = take_mark(
        _Observer(_frame()),
        100.0,
        escape=lambda: True,
        enter=lambda: True,
        cursor=lambda: (100, 25),
        clock=_ticks(),
    )
    assert result is ABORTED


def test_the_session_deadline_bounds_the_point_prompt(monkeypatch):
    from ghostcursor.harness import teach_live

    monkeypatch.setattr(teach_live.time, "sleep", lambda _: None)
    result = teach_live.take_mark(
        _Observer(_frame()),
        5.0,
        escape=lambda: False,
        enter=lambda: False,
        cursor=lambda: (100, 25),
        clock=_ticks(),
    )
    assert result is teach_live.ABORTED


def test_enter_marks_the_control_under_the_cursor(monkeypatch):
    from ghostcursor.harness import teach_live
    from ghostcursor.harness.teach_live import take_mark

    monkeypatch.setattr(teach_live.time, "sleep", lambda _: None)

    frame = _frame()
    mark = take_mark(
        _Observer(frame),
        100.0,
        escape=lambda: False,
        enter=lambda: True,
        cursor=lambda: (100, 25),
        clock=_ticks(),
    )
    assert [c.name for c in mark.current(frame)] == ["Insert"]
    nothing = take_mark(
        _Observer(frame),
        100.0,
        escape=lambda: False,
        enter=lambda: True,
        cursor=lambda: (800, 500),
        clock=_ticks(),
    )
    assert nothing is teach_live.ABORTED  # asked again until the deadline


def test_run_model_teach_uses_one_deadline_and_stops_on_abort(monkeypatch):
    from ghostcursor.harness import teach_live

    seen = {}
    monkeypatch.setattr(teach_live, "bind", lambda hwnds: (W1,))
    monkeypatch.setattr(teach_live.Observer, "start", lambda self: None)

    def fake_take_mark(observer, deadline, **_hooks):
        seen["deadline"] = deadline
        return teach_live.ABORTED

    monkeypatch.setattr(teach_live, "take_mark", fake_take_mark)
    monkeypatch.setattr(
        teach_live.window,
        "create_overlay_window",
        lambda **k: (_ for _ in ()).throw(AssertionError("overlay after abort")),
    )
    monkeypatch.setattr(teach_live.time, "monotonic", lambda: 1000.0)
    assert (
        teach_live.run_model_teach("g", [11], seconds=60, gateway=object(), point=True)
        == 0
    )
    assert seen["deadline"] == 1060.0


def test_time_spent_pointing_counts_against_the_session(monkeypatch):
    from ghostcursor.harness import teach_live

    now = [1000.0]

    def clock():
        now[0] += 0.01
        return now[0]

    def fake_take_mark(observer, deadline, **_hooks):
        now[0] = deadline + 1  # the whole budget went on pointing
        return None

    drawn = []
    monkeypatch.setattr(teach_live, "bind", lambda hwnds: (W1,))
    monkeypatch.setattr(teach_live.Observer, "start", lambda self: None)
    monkeypatch.setattr(teach_live, "take_mark", fake_take_mark)
    monkeypatch.setattr(teach_live.time, "monotonic", clock)
    monkeypatch.setattr(teach_live.time, "sleep", lambda _: None)
    monkeypatch.setattr(teach_live, "_escape_pressed", lambda: False)
    monkeypatch.setattr(teach_live, "_console_enter", lambda: False)
    monkeypatch.setattr(
        teach_live.window, "create_overlay_window", lambda **k: "overlay"
    )
    monkeypatch.setattr(teach_live.window, "destroy_overlay_window", lambda o: None)
    monkeypatch.setattr(teach_live.window, "pump_messages_nonblocking", lambda: None)
    monkeypatch.setattr(teach_live.window, "clear_hint", lambda o: drawn.append(o))
    teach_live.run_model_teach("g", [11], seconds=60, gateway=object(), point=True)
    assert drawn == []  # no guidance tick ran after the deadline


@pytest.mark.parametrize(
    "esc, stop, late",
    [(True, False, False), (False, True, False), (False, False, True)],
)
def test_the_guidance_loop_ends_on_esc_its_stop_hook_or_the_deadline(
    monkeypatch, esc, stop, late
):
    """ESC and the deadline stop a session whatever the UI's ``stop`` hook
    says, and the hook alone stops it too (rule 4, review of D178)."""

    from ghostcursor.harness import teach_live

    class Session:
        completed = []

        def __init__(self, *a, **kw):
            pass

        def tick(self, *a, **kw):
            pytest.fail("guidance ticked after it should have stopped")

        def stop(self):
            pass

    times = iter([1000.0] + [2000.0 if late else 1000.0] * 10)
    monkeypatch.setattr(teach_live, "bind", lambda hwnds: (W1,))
    monkeypatch.setattr(teach_live.Observer, "start", lambda self: None)
    monkeypatch.setattr(teach_live, "ModelTeachSession", Session)
    monkeypatch.setattr(teach_live.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(teach_live, "_escape_pressed", lambda: esc)
    monkeypatch.setattr(
        teach_live.window, "create_overlay_window", lambda **k: "overlay"
    )
    monkeypatch.setattr(teach_live.window, "destroy_overlay_window", lambda o: None)
    said = []
    teach_live.run_model_teach(
        "g",
        [11],
        seconds=60,
        gateway=object(),
        say=said.append,
        confirm=lambda: False,
        stop=lambda: stop,
    )
    assert said[-1] in ("Stopped - exiting.", "Time limit reached - exiting.")


# --- voice respects ESC and the session deadline (D171 review follow-up) ---


def _voice(**kw):
    from ghostcursor.voice import dictate_goal

    defaults = dict(
        ask=lambda prompt: "",
        enter=lambda: True,
        escape=lambda: False,
        record=lambda stop: (stop(), [0.1])[1],
        transcribe=lambda samples: "add a slide",
        clock=lambda: 0.0,
    )
    defaults.update(kw)
    return dictate_goal(100.0, **defaults)


def test_voice_returns_the_confirmed_draft_or_the_correction():
    assert _voice() == "add a slide"
    assert _voice(ask=lambda p: "add two slides") == "add two slides"
    assert _voice(transcribe=lambda s: "") is None


def _enter_never(limit=5):
    """Never pressed; fails instead of hanging if the loop ignores its stop."""

    calls = iter(range(limit))
    return lambda: next(calls, None) is None and pytest.fail("dictation did not stop")


def test_esc_or_the_deadline_cancels_dictation():
    assert _voice(escape=lambda: True, enter=_enter_never()) is None  # before speaking
    assert (
        _voice(
            escape=lambda: True,
            record=lambda stop: (stop(), [0.1])[1],
            enter=iter([True, False, False]).__next__,
        )
        is None
    )  # while speaking
    assert _voice(clock=lambda: 200.0, enter=_enter_never()) is None
    now = [0.0]

    def slow_confirm(prompt):
        now[0] = 200.0
        return ""

    assert (
        _voice(clock=lambda: now[0], ask=slow_confirm) is None
    )  # passed while confirming


def test_the_confirm_prompt_stops_on_esc_or_deadline_without_input():
    from ghostcursor.voice import read_line

    keys = iter("ab\b\r")
    assert (
        read_line("p", lambda: False, getch=lambda: next(keys), kbhit=lambda: True)
        == "a"
    )
    assert (
        read_line("p", lambda: False, getch=lambda: "\x1b", kbhit=lambda: True) is None
    )
    assert (
        read_line("p", lambda: True, getch=_enter_never(), kbhit=_enter_never()) is None
    )


def test_dictation_uses_the_polling_prompt_by_default(monkeypatch):
    import ghostcursor.voice as voice

    monkeypatch.setattr(voice, "read_line", lambda prompt, stop: None if stop() else "")
    now = [0.0]

    def transcribe(samples):
        now[0] = 200.0  # transcription ran past the deadline
        return "add a slide"

    assert _voice(ask=None, clock=lambda: now[0], transcribe=transcribe) is None


def test_esc_at_the_confirm_prompt_cancels(monkeypatch):
    import ghostcursor.voice as voice

    monkeypatch.setattr(voice, "read_line", lambda prompt, stop: None)  # ESC typed
    assert _voice(ask=None) is None


def test_esc_during_a_hung_transcription_stops_dictation():
    import threading

    release = threading.Event()

    def hung(samples):
        release.wait(5)  # a model load that never finishes
        return "add a slide"

    escapes = iter([False, False, True])  # pressed only once transcription runs
    try:
        assert _voice(transcribe=hung, escape=lambda: next(escapes, True)) is None
    finally:
        release.set()
