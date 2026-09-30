"""A retained record is written once; any later edit is named here.

`test_retained_evidence_digests.py` compares a record with the digest its
citing document publishes. Editing a transcript and its citation in one commit
passes that check by construction (D149 review, finding I5). This test anchors
the records in git history instead: every commit that modified a record after
it was created must be listed below, exactly, with the disclosure that covers
it. A new edit fails here until someone writes down why it happened, in a diff
a reviewer will read.

History is taken at the literal path, since the file's last creation. A record
deleted and re-created from a fresh run starts a new history; `--follow` is not
used because its rename similarity guessed unrelated JSON files into one
lineage.
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

RECORD_GLOBS = (
    "docs/evidence/*.json",
    "docs/evidence/**/*.json",
    "docs/evidence/*.jsonl",
    "docs/evidence/**/*.jsonl",
    "plugins/sources/*/acceptance-records/**/*.json",
)

#: Pattern -> the exact abbreviated commits that edited matching records after
#: capture, oldest first, and where that is disclosed.
KNOWN_EDITS = {
    "docs/evidence/receipt-budget/run-*.json": (
        ("63c5ca5",),
        "whole records re-captured by new live runs and re-derived (ROADMAP "
        "Phase E receipt budget; independent review READY at 63c5ca5)",
    ),
    "plugins/sources/*/acceptance-records/**/*.json": (
        ("3e8ad17", "3d4956f"),
        "target_ref rewritten in place twice; falsified-transcripts-disclosure.md "
        "instance 4",
    ),
}


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        pytest.skip("not a git work tree")
    return result.stdout


def _records() -> list[str]:
    return sorted(set(_git("ls-files", *RECORD_GLOBS).split()))


def _edits_since_creation(path: str) -> tuple[str, ...]:
    """Commits that modified `path` after its most recent creation, oldest first."""

    log = _git("log", "--format=%h", "--name-status", "--", path)
    edits: list[str] = []
    commit = None
    for line in log.splitlines():
        if not line.strip():
            continue
        if "\t" not in line:
            commit = line.strip()[:7]
            continue
        status = line.split("\t", 1)[0]
        if status.startswith("A"):
            break
        if status.startswith("M"):
            edits.append(commit)
    return tuple(reversed(edits))


def _allowed(path: str) -> tuple[str, ...]:
    for pattern, (commits, _reason) in KNOWN_EDITS.items():
        if fnmatch.fnmatch(path, pattern):
            return commits
    return ()


def test_the_record_set_is_not_vacuous():
    records = _records()
    assert len(records) >= 40, len(records)
    assert any(r.endswith(".jsonl") for r in records)
    assert any("acceptance-records" in r for r in records)


def test_no_retained_record_was_edited_after_capture_without_disclosure():
    offenders = []
    for path in _records():
        edits = _edits_since_creation(path)
        if edits != _allowed(path):
            offenders.append(
                f"{path}: edited by {list(edits)}, disclosed {list(_allowed(path))}"
            )
    assert not offenders, "retained records edited after capture:\n" + "\n".join(
        offenders
    )


def test_every_disclosed_edit_still_matches_a_record():
    """An allowance that no longer matches anything is a stale exemption."""

    records = _records()
    for pattern, (commits, _reason) in KNOWN_EDITS.items():
        matched = [r for r in records if fnmatch.fnmatch(r, pattern)]
        assert matched, pattern
        assert all(_edits_since_creation(r) == commits for r in matched), pattern


def test_the_history_walk_sees_an_edit_and_stops_at_creation():
    """Planted against real history: an acceptance record is known to have
    two post-capture edits, and a single-commit transcript none."""

    edited = "plugins/sources/powerpoint/acceptance-records/add-slide/run-1.json"
    clean = "docs/evidence/act-live-manager-d131-r1.jsonl"
    assert _edits_since_creation(edited) == ("3e8ad17", "3d4956f")
    assert _edits_since_creation(clean) == ()
