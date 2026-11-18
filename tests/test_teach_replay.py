"""Offline replay for model-driven Teach (D164 step 4, spec section 9).

Properties: a corpus record holds only what a model sees (never a handle, PID,
runtime id, rectangle or title); replay runs the real gate; a shown pointer
outside the labels counts as wrong; floor/margin are fitted on dev only.
"""

from __future__ import annotations

import json

import pytest

from ghostcursor.devtools.teach_capture import append_record, leaks_identity
from ghostcursor.evaluation.teach_replay import (
    cassette_chooser,
    evaluate,
    fit,
    lexical_chooser,
    load_corpus,
    parse_record,
    record_from_frame,
    score,
)
from ghostcursor.harness import (
    Identity,
    RawControl,
    WindowObservation,
    bind,
    build_frame,
)
from ghostcursor.providers import ABSTAIN, Choice

HWND, PID = 1311234, 48211
IDS = {HWND: Identity(PID, "notepad.exe", "11")}
(W1,) = bind([HWND], identify_window=IDS.get, own_pid=1)


def _frame():
    controls = (
        RawControl((42, HWND, 1), "File", "MenuItem", (10, 10, 50, 30), True, False),
        RawControl((42, HWND, 2), "Edit", "MenuItem", (60, 10, 100, 30), True, False),
        RawControl(
            (42, HWND, 3), "notes.txt", "TabItem", (10, 40, 90, 60), True, False
        ),
        RawControl((42, HWND, 4), "Delete", "Button", (10, 70, 90, 90), True, False),
    )
    return build_frame(
        1,
        0.0,
        [
            WindowObservation(
                W1, (0, 0, 800, 600), controls, title="notes.txt - Notepad"
            )
        ],
    )


def _record(
    step_id="s1", split="dev", instruction="Open the File menu", labels=("c1",)
):
    return record_from_frame(
        _frame(),
        step_id=step_id,
        split=split,
        goal="save a copy",
        instruction=instruction,
        labels=labels,
    )


def test_a_record_holds_no_handle_pid_runtime_id_rect_or_title():
    line = json.dumps(_record())
    assert str(HWND) not in line and str(PID) not in line
    assert "rect" not in line and "runtime" not in line
    assert "Notepad" not in line  # the window title
    assert "notes.txt" not in line  # a document name stays hidden (D168)
    assert not leaks_identity(line, (W1,))


def test_capture_refuses_a_line_that_carries_a_bound_handle(tmp_path):
    record = _record()
    record["goal"] = f"window {HWND}"
    with pytest.raises(ValueError, match="handle or PID"):
        append_record(tmp_path / "c.jsonl", record, (W1,))
    assert not (tmp_path / "c.jsonl").exists()


def test_parse_refuses_extra_fields_and_unknown_labels():
    record = _record()
    with pytest.raises(ValueError):
        parse_record({**record, "hwnd": 1})
    with pytest.raises(ValueError):
        parse_record({**record, "labels": ["c99"]})
    bad = json.loads(json.dumps(record))
    bad["candidates"][0]["rect"] = [0, 0, 1, 1]
    with pytest.raises(ValueError):
        parse_record(bad)
    with pytest.raises(ValueError):
        record_from_frame(
            _frame(), step_id="x", split="dev", goal="g", instruction="i", labels=["c9"]
        )


def test_round_trip_and_lexical_baseline_points_at_the_named_control(tmp_path):
    path = tmp_path / "corpus.jsonl"
    for r in (
        _record("s1"),
        _record("s2", instruction="Open the Edit menu", labels=("c2",)),
    ):
        append_record(path, r, (W1,))
    steps = load_corpus(path)
    report = evaluate(steps, lexical_chooser)
    assert report["dev"]["overall"]["pointer_shown"] == 2
    assert report["dev"]["overall"]["wrong_pointer"] == 0
    assert report["dev"]["by_application"]["notepad.exe"]["steps"] == 2


def test_a_confident_wrong_choice_counts_as_a_wrong_pointer_and_high_risk():
    step = parse_record(_record())
    report = score([step], {"s1": Choice("c4", {"c4": 0.95, ABSTAIN: 0.01})})
    overall = report["overall"]
    assert overall["wrong_pointer"] == 1 and overall["wrong_pointer_high_risk"] == 1
    assert overall["wrong_rate_upper_95"] is None


def test_abstention_on_a_step_where_nothing_fits_is_correct():
    step = parse_record(_record(labels=()))
    overall = score([step], {"s1": Choice(ABSTAIN, {})})["overall"]
    assert overall["correct_abstention"] == 1 and overall["pointer_shown"] == 0
    shown = score([step], {"s1": Choice("c1", {"c1": 0.99})})["overall"]
    assert shown["wrong_pointer"] == 1  # nothing fits, so any pointer is wrong


def test_low_confidence_is_withheld_by_the_real_gate():
    step = parse_record(_record())
    overall = score([step], {"s1": Choice("c1", {"c1": 0.5, "c2": 0.45})})["overall"]
    assert overall["pointer_shown"] == 0
    assert overall["withheld_reasons"] == {"not confident enough": 1}


def test_fit_uses_dev_only_and_reaches_zero_wrong_on_dev():
    steps = [
        parse_record(_record("d1")),
        parse_record(_record("d2", instruction="x", labels=("c2",))),
        parse_record(_record("t1", split="test", labels=("c2",))),
    ]
    answers = {
        "d1": Choice("c1", {"c1": 0.9}),
        "d2": Choice("c1", {"c1": 0.7}),  # wrong; floor must rise above 0.7
        "t1": Choice("c1", {"c1": 0.99}),  # wrong on test; must not move the fit
    }
    floor, margin = fit(steps, answers)
    assert 0.7 < floor <= 0.9
    assert (
        score(steps[:2], answers, floor=floor, margin=margin)["overall"][
            "wrong_pointer"
        ]
        == 0
    )


def test_cassette_replay_refuses_a_missing_step(tmp_path):
    tape = tmp_path / "tape.json"
    tape.write_text(json.dumps({"s1": {"choice": "c1", "probabilities": {"c1": 0.9}}}))
    chooser = cassette_chooser(tape)
    assert chooser(parse_record(_record())).choice == "c1"
    with pytest.raises(ValueError, match="no recording"):  # never a free "correct abstention"
        chooser(parse_record(_record("other")))

def test_capture_refuses_a_line_that_carries_a_bound_pid(tmp_path):
    record = _record()
    record["goal"] = f"process {PID}"
    with pytest.raises(ValueError, match="handle or PID"):
        append_record(tmp_path / "c.jsonl", record, (W1,))


def test_parse_refuses_an_extra_string_field_on_a_candidate():
    bad = json.loads(json.dumps(_record()))
    bad["candidates"][0]["title"] = "notes.txt - Notepad"
    with pytest.raises(ValueError):
        parse_record(bad)


def test_capture_refuses_a_typed_window_title(tmp_path):
    record = _record(instruction="Save notes.txt - Notepad as a copy")
    with pytest.raises(ValueError, match="window title"):
        append_record(tmp_path / "c.jsonl", record, (W1,), ["notes.txt - Notepad"])


def test_parse_refuses_non_string_windows_and_fields():
    record = _record()
    for bad in ({"w1": 12}, {"hwnd": "notepad.exe"}):
        with pytest.raises(ValueError):
            parse_record({**record, "windows": bad})
    with pytest.raises(ValueError):
        parse_record({**record, "goal": 5})


def test_replay_rehides_a_document_name_from_a_foreign_corpus():
    from ghostcursor.evaluation.teach_replay import step_frame

    record = _record()
    record["candidates"][0]["name"] = "budget.xlsx"
    frame = step_frame(parse_record(record))
    assert "budget.xlsx" not in json.dumps(
        {k: v["name"].text for k, v in frame.model_view()["candidates"].items()}
    )


def test_a_model_failure_is_recorded_as_a_failure_never_an_abstention(tmp_path):
    from ghostcursor.evaluation.teach_replay import gateway_chooser
    from ghostcursor.providers import FailureKind, ProviderError

    class Down:
        def choose(self, *a, **k):
            raise ProviderError(FailureKind.UNAVAILABLE, "timed out")

    tape = tmp_path / "tape.json"
    step = parse_record(_record())
    with pytest.raises(ProviderError):
        gateway_chooser(Down(), record_to=tape)(step)
    with pytest.raises(ValueError, match="model failed"):  # not a free "correct abstention"
        cassette_chooser(tape)(step)
