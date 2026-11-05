"""On-demand dictation (D186): explicit capture -> save. Rule 1: the module
never types into another app; it sinks the transcript to a file or the Brain.
Hermetic -- record/transcribe are injected, no microphone."""

from __future__ import annotations

from ghostcursor import dictation


def test_save_transcript_writes_a_timestamped_file_and_skips_empty(tmp_path):
    path = dictation.save_transcript("resize to 25%", dest_dir=tmp_path)
    assert path is not None and path.exists()
    assert path.read_text(encoding="utf-8") == "resize to 25%"
    assert path.parent == tmp_path and path.suffix == ".txt"
    # empty / whitespace -> nothing saved
    assert dictation.save_transcript("   ", dest_dir=tmp_path) is None


def test_save_transcript_never_clobbers_within_the_same_second(tmp_path):
    frozen = lambda: 1_700_000_000.0  # same timestamp both times
    a = dictation.save_transcript("first", dest_dir=tmp_path, clock=frozen)
    b = dictation.save_transcript("second", dest_dir=tmp_path, clock=frozen)
    assert a != b and a.read_text() == "first" and b.read_text() == "second"


def test_to_brain_files_a_reviewable_candidate(tmp_path):
    from ghostcursor.workspace.knowledge import Knowledge

    kb = Knowledge(tmp_path / "k.sqlite")
    fid = dictation.to_brain("prod runs in us-east-1", kb, "acme")
    fact = kb.get(fid)
    assert fact.status == "candidate" and fact.source == "dictation"
    assert dictation.to_brain("   ", kb, "acme") is None
    kb.close()


def test_dictate_records_transcribes_and_sinks(tmp_path):
    saved = {}
    text, result = dictation.dictate(
        stop=lambda: True,
        record=lambda stop: "AUDIO",  # stub: no mic
        transcribe=lambda samples: "twenty five percent" if samples == "AUDIO" else "",
        sink=lambda t: (saved.__setitem__("text", t), "ok")[1],
    )
    assert text == "twenty five percent"
    assert saved["text"] == "twenty five percent" and result == "ok"


def test_dictate_default_sink_saves_to_file(tmp_path, monkeypatch):
    monkeypatch.setattr(dictation, "_default_dir", lambda: tmp_path)
    text, path = dictation.dictate(
        stop=lambda: True,
        record=lambda stop: "AUDIO",
        transcribe=lambda samples: "note this down",
    )
    assert text == "note this down"
    assert path.exists() and path.read_text() == "note this down"


# --- typing into an app (D188) ------------------------------------------------

import pytest  # noqa: E402

from ghostcursor.harness import act  # noqa: E402
from ghostcursor.harness.binding import Identity  # noqa: E402
from ghostcursor.harness.frame import RawControl  # noqa: E402

FIELD = (42, 7)
APP, CONSOLE = 101, 202


def _raw(rid=FIELD, kind="Document", focused=True, password=False, enabled=True):
    return RawControl(
        rid,
        "Text editor",
        kind,
        (100, 100, 500, 400),
        enabled,
        False,
        password,
        "",
        focused,
    )


def _identity(exe="notepad.exe"):
    return lambda hwnd: Identity(5, exe, "11")


def _field(controls, exe="notepad.exe"):
    return lambda hwnd: dictation.field_in(
        hwnd,
        read=lambda h: ((0, 0, 900, 600), tuple(controls), False),
        identify_window=_identity(exe),
    )


def _type(
    text="hello world",
    *,
    front=APP,
    controls=(_raw(),),
    exe="notepad.exe",
    escape=lambda: False,
):
    typed = []
    clock = iter(range(100)).__next__
    said = dictation.type_into(
        text,
        before=CONSOLE,
        escape=escape,
        wait_s=3,
        clock=lambda: clock() * 1.0,
        pause=lambda s: None,
        foreground=lambda: front,
        field=_field(controls, exe),
        perform=lambda step, target, window: (
            typed.append((step.action, step.text, target.runtime_id, window)) or "typed"
        ),
    )
    return said, typed


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    from ghostcursor import audit

    monkeypatch.setattr(audit, "record", lambda *a, **k: True)


def test_approved_text_is_typed_into_the_focused_field_of_the_clicked_window():
    said, typed = _type("first line\nsecond line")
    assert said == "typed"
    # one line: a line break would press Enter, which can send a message
    assert typed == [("type_focused", "first line second line", FIELD, APP)]


@pytest.mark.parametrize(
    "kwargs, reason",
    [
        ({"front": CONSOLE}, "no other window"),
        ({"front": 0}, "no other window"),
        ({"escape": lambda: True}, "cancelled"),
        ({"exe": "windowsterminal.exe"}, "console"),
        ({"exe": "keepass.exe"}, "never bound"),
        ({"controls": (_raw(password=True),)}, "password"),
        ({"controls": (_raw(focused=False),)}, "no text field"),
        ({"controls": (_raw(kind="Button"),)}, "no text field"),
        ({"controls": (_raw(enabled=False),)}, "no text field"),
        ({"controls": (_raw(), _raw(rid=(42, 8)))}, "no text field"),
        ({"text": "   "}, "nothing to type"),
    ],
)
def test_nothing_is_typed_unless_one_safe_field_was_clicked(kwargs, reason):
    said, typed = _type(**kwargs)
    assert reason in said and not typed


def _perform_focused(text="hi", *, front=APP, focused=FIELD, blocked=None):
    from ghostcursor.harness.frame import Candidate

    sent = []
    target = Candidate(
        "c1", "w1", FIELD, "Text editor", "Document", (100, 100, 500, 400), ""
    )
    result = act.perform(
        type("S", (), {"action": "type_focused", "text": text})(),
        target,
        window=APP,
        send=sent.append,
        click=lambda x, y: pytest.fail("type_focused must never click"),
        pause=lambda s: None,
        check=lambda x, y, window: blocked,
        focus=lambda: front,
        focused_id=lambda: focused,
        held=lambda: False,
    )
    return result, sent


def test_type_focused_types_without_clicking(monkeypatch):
    monkeypatch.setattr(act, "_on_bound_window", lambda root, window: root == window)
    said, sent = _perform_focused("hi")
    assert said == "typed 2 characters" and len(sent[0]) == 4


@pytest.mark.parametrize(
    "kwargs, error",
    [
        ({"front": CONSOLE}, PermissionError),  # another window came to the front
        ({"focused": (42, 9)}, PermissionError),  # the caret moved to another field
        ({"focused": ()}, PermissionError),
        ({"blocked": "the screen is locked"}, PermissionError),
        ({"text": "a\nb"}, ValueError),
        ({"text": ""}, ValueError),
    ],
)
def test_type_focused_refuses_rather_than_type_into_the_wrong_place(
    monkeypatch, kwargs, error
):
    monkeypatch.setattr(act, "_on_bound_window", lambda root, window: root == window)
    with pytest.raises(error):
        _perform_focused(**kwargs)


def test_type_focused_obeys_an_organisation_that_disables_act(monkeypatch):
    from ghostcursor import policy

    monkeypatch.setattr(policy, "act_disabled", lambda: True)
    with pytest.raises(PermissionError):
        _perform_focused()


def test_a_model_plan_cannot_ask_for_type_focused():
    import json

    from ghostcursor.providers.schemas import (
        ACTIONS,
        TEACH_PLAN_SCHEMA,
        parse_teach_plan,
    )

    assert "type_focused" not in ACTIONS and "type_focused" not in str(
        TEACH_PLAN_SCHEMA
    )
    step = {
        "instruction": "x",
        "expected_change": "title_changes",
        "action": "type_focused",
        "text": "hi",
    }
    with pytest.raises(Exception):
        parse_teach_plan(json.dumps({"steps": [step]}))
