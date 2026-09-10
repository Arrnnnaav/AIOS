"""The retained deck observation observes, and does nothing else."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ghostcursor.devtools import act_deck_observation
from ghostcursor.devtools.act_deck_observation import (
    DeckObservationError,
    observe,
    render,
)


def _presentation(name, slides, saved=False):
    return SimpleNamespace(Name=name, Slides=SimpleNamespace(Count=slides), Saved=saved)


def _application(*presentations, version="16.0", build="16.0.20326.20112"):
    return SimpleNamespace(
        Presentations=list(presentations), Version=version, Build=build
    )


def test_a_reading_records_every_open_deck_and_its_slide_count():
    reading = observe(
        _application(_presentation("Presentation1", 1), _presentation("Deck.pptx", 12)),
        label="before",
        at_ns=1788947215630663400,
    )

    assert reading["label"] == "before"
    assert reading["at_ns"] == 1788947215630663400
    assert reading["application"]["build"] == "16.0.20326.20112"
    assert reading["presentation_count"] == 2
    # Sorted by name so a before/after pair is diffable without reordering.
    assert [row["name"] for row in reading["presentations"]] == [
        "Deck.pptx",
        "Presentation1",
    ]
    assert [row["slide_count"] for row in reading["presentations"]] == [12, 1]


def test_a_before_after_pair_shows_the_change_that_is_being_claimed():
    before = observe(_application(_presentation("Presentation1", 1)), label="before")
    after = observe(_application(_presentation("Presentation1", 2)), label="after")

    assert before["presentations"][0]["slide_count"] == 1
    assert after["presentations"][0]["slide_count"] == 2


def test_an_unlabelled_reading_is_refused():
    """A file that does not say which side of the run it came from is not
    evidence of a change."""

    with pytest.raises(ValueError):
        observe(_application(), label="midway")


def test_the_reading_is_json_serialisable_exactly_as_written():
    reading = observe(_application(_presentation("Presentation1", 1)), label="after")

    assert json.loads(json.dumps(reading, sort_keys=True))["presentations"][0] == {
        "name": "Presentation1",
        "slide_count": 1,
        "saved": False,
    }


def test_a_missing_powerpoint_is_an_error_not_a_launch(monkeypatch):
    """Dispatch would start PowerPoint, which is the same mistake as an
    adapter launching the process it claims to be verifying."""

    import sys

    fake = SimpleNamespace(
        GetActiveObject=lambda _name: (_ for _ in ()).throw(OSError("not running"))
    )
    monkeypatch.setitem(sys.modules, "win32com.client", fake)
    monkeypatch.setitem(sys.modules, "win32com", SimpleNamespace(client=fake))

    with pytest.raises(DeckObservationError, match="not running"):
        act_deck_observation._running_application()


def test_retained_bytes_are_lf_on_every_platform():
    r"""The artifact is cited by SHA-256, so its bytes may not depend on the
    machine that wrote it. `write_text` translates "\n" to "\r\n" on Windows,
    which is the D125 defect in miniature: a digest that reproduces only on
    the operating system that produced it. Found by writing the first real
    pair of readings and seeing CRLF in both.
    """

    raw = render(
        observe(_application(_presentation("Presentation1", 1)), label="after")
    )

    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")
    assert json.loads(raw.decode("utf-8"))["label"] == "after"


# --- the read-only guarantee ----------------------------------------------


#: Calling any of these changes a presentation, or starts an application.
_EFFECT_CALLS = {
    "Add",
    "AddSlide",
    "Delete",
    "Cut",
    "Copy",
    "Paste",
    "Insert",
    "Save",
    "SaveAs",
    "SaveCopyAs",
    "Close",
    "Quit",
    "Run",
    "Export",
    "Dispatch",
    "DispatchEx",
    "EnsureDispatch",
    "SetFocus",
    "Activate",
}


def _effect_calls_in(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in _EFFECT_CALLS:
                found.add(name)
    return found


def test_the_observation_probe_calls_nothing_that_acts_or_launches():
    source = Path(act_deck_observation.__file__).read_text(encoding="utf-8")

    assert _effect_calls_in(ast.parse(source)) == set()


@pytest.mark.parametrize(
    "snippet",
    [
        "application.Presentations.Add()",
        "presentation.SaveAs('x.pptx')",
        "win32com.client.Dispatch('PowerPoint.Application')",
        "presentation.Slides.Delete()",
        "application.Quit()",
    ],
)
def test_the_effect_scan_catches_a_planted_call(snippet):
    """Non-vacuity: a scan that cannot fail proves nothing about the file it
    passed."""

    assert _effect_calls_in(ast.parse(snippet))
