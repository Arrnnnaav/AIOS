"""Note enhancement (D186): rough notes -> a structured summary, strictly
parsed and local. Granola's core value without recording.

Pins the closed parse (bad model output is refused, not shown as garbage) and
that enhancement is local + never auto-files: it files to the Brain only when
asked, as a reviewable candidate.
"""

from __future__ import annotations

import json

import pytest

from ghostcursor.providers.errors import FailureKind, ProviderError
from ghostcursor.providers.schemas import parse_notes
from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.notes import render_notes
from ghostcursor.workspace.session import Workspace

GOOD = {
    "title": "Weekly sync",
    "summary": "The team agreed to ship DLP this week.",
    "key_points": ["DLP is ready", "Three accounts are waiting"],
    "action_items": ["Email the three accounts", "Cut the release"],
}


def test_parse_notes_is_strict():
    ns = parse_notes(json.dumps(GOOD))
    assert ns.title == "Weekly sync" and len(ns.key_points) == 2
    for bad in (
        '{"title": "t", "summary": "s", "key_points": []}',  # missing action_items
        '{"title": "t", "summary": "s", "key_points": {}, "action_items": []}',  # wrong type
        '{"title": "t", "summary": "s", "key_points": [], "action_items": [], "x": 1}',  # extra
    ):
        with pytest.raises(ProviderError):
            parse_notes(bad)


def test_render_notes_has_summary_points_and_checkboxes():
    out = render_notes(parse_notes(json.dumps(GOOD)))
    assert "# Weekly sync" in out
    assert "- DLP is ready" in out
    assert "- [ ] Email the three accounts" in out


class NotesGateway:
    def __init__(self, fail=False):
        self.fail = fail

    def complete(self, envelope, system, schema, parse, **kw):
        if self.fail:
            raise ProviderError(FailureKind.UNAVAILABLE, "no model")
        return parse(json.dumps(GOOD))


def test_enhance_notes_is_local_and_files_only_when_asked(tmp_path):
    brain = Brain(tmp_path / "b.sqlite")
    from ghostcursor.workspace.knowledge import Knowledge

    kb = Knowledge(tmp_path / "k.sqlite")
    ws = Workspace(
        "notes", NotesGateway(), brain, knowledge=kb, root=tmp_path / "briefs"
    )

    summary, message = ws.enhance_notes("rough jumble of a meeting")
    assert summary.title == "Weekly sync" and "# Weekly sync" in message
    assert kb.list(scope="default", status="candidate") == []  # not filed by default

    _s, message2 = ws.enhance_notes("rough notes again", to_brain=True)
    cands = kb.list(scope="default", status="candidate")
    assert len(cands) == 1 and "candidate #" in message2
    kb.close()
    brain.close()


def test_enhance_notes_handles_empty_and_no_model(tmp_path):
    brain = Brain(tmp_path / "b.sqlite")
    ws = Workspace("notes", NotesGateway(fail=True), brain, root=tmp_path / "briefs")
    assert ws.enhance_notes("   ")[0] is None  # empty -> message, no crash
    summary, message = ws.enhance_notes("some notes")
    assert summary is None and "not available" in message
    brain.close()
