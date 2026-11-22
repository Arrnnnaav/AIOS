"""A retained record is written once; any later edit is named here.

`test_retained_evidence_digests.py` compares a record with the digest its
citing document publishes. Editing a transcript and its citation in one commit
passes that check by construction (D149 review, finding I5). This test anchors
the records in git history instead: every commit that modified a record after
it was created must be listed below, exactly, with the disclosure that covers
it. A new edit fails here until someone writes down why it happened, in a diff
a reviewer will read.

History is taken at the literal path, from the file's FIRST creation: every
later modification, deletion or re-creation counts. An earlier version started
at the most recent creation, so deleting a record in one commit and re-adding
edited bytes in the next escaped entirely (D152, review m5). `--follow` is not
used because its rename similarity guessed unrelated JSON files into one
lineage. The campaign ledger lives outside `docs/evidence/` and has its own
append-only test.
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
    "docs/archive/retained-plugins/plugins/sources/*/acceptance-records/**/*.json",
)

#: Pattern -> the exact abbreviated commits that edited matching records after
#: capture, oldest first, and where that is disclosed.
KNOWN_EDITS = {
    # Checked first: fnmatch takes the first pattern that matches.
    "docs/archive/retained-plugins/plugins/sources/powerpoint/acceptance-records/add-slide/run-*.json": (
        ("1907006", "2e718f0", "3e8ad17", "3d4956f"),
        "withdrawn to excluded/ by 1907006 and replaced by three new stamped runs "
        "in 2e718f0 (both commits describe it); then the instance-4 rewrites",
    ),
    "docs/evidence/receipt-budget/run-*.json": (
        ("63c5ca5",),
        "whole records re-captured by new live runs and re-derived (ROADMAP "
        "Phase E receipt budget; independent review READY at 63c5ca5)",
    ),
    "docs/archive/retained-plugins/plugins/sources/*/acceptance-records/**/*.json": (
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


#: D193 moved the plugin acceptance records, byte for byte, from `plugins/`
#: into the evidence tree when the plugin system was retired. Their history is
#: still read at the ORIGINAL literal path (no rename guessing), so an edit
#: made before the move cannot escape by the move.
MOVED_FROM = "docs/archive/retained-plugins/"


def _touches(path: str, until: str | None = None) -> list[str]:
    revs = [until] if until else []
    log = _git("log", "--reverse", "--format=%h", "--name-status", *revs, "--", path)
    touched: list[str] = []
    commit = None
    for line in log.splitlines():
        if not line.strip():
            continue
        if "\t" not in line:
            commit = line.strip()[:7]
            continue
        touched.append(commit)
    return touched


def _edits_since_creation(path: str) -> tuple[str, ...]:
    """Every commit that touched `path` after its first creation, oldest first:
    modifications, deletions and re-creations alike."""

    if not path.startswith(MOVED_FROM):
        return tuple(_touches(path)[1:])
    here = _touches(path)
    if not here:
        return ()
    # The original path's history up to (not including) the move: its later
    # deletion, when the plugin tree was removed, is the move, not an edit.
    before = _touches(path[len(MOVED_FROM):], until=f"{here[0]}^")
    return tuple(before[1:] + here[1:])


def _governing(path: str) -> str | None:
    """The first KNOWN_EDITS pattern that matches `path`, which is the one
    that governs it."""

    return next((p for p in KNOWN_EDITS if fnmatch.fnmatch(path, p)), None)


def _allowed(path: str) -> tuple[str, ...]:
    pattern = _governing(path)
    return KNOWN_EDITS[pattern][0] if pattern else ()


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
        matched = [r for r in records if _governing(r) == pattern]
        assert matched, pattern
        assert all(_edits_since_creation(r) == commits for r in matched), pattern


def test_the_history_walk_sees_an_edit_and_stops_at_creation():
    """Planted against real history. The add-slide records were deleted in
    1907006 and re-created in 2e718f0 -- exactly the delete-then-re-add shape
    the earlier walk missed -- so all four later commits must be seen. An
    excluded record has only the two in-place rewrites, and a single-commit
    transcript none."""

    edited = "docs/archive/retained-plugins/plugins/sources/powerpoint/acceptance-records/add-slide/run-1.json"
    rewritten = "docs/archive/retained-plugins/plugins/sources/powerpoint/acceptance-records/excluded/attempt-set-01-run-01.json"
    clean = "docs/evidence/act-live-manager-d131-r1.jsonl"
    assert _edits_since_creation(edited) == ("1907006", "2e718f0", "3e8ad17", "3d4956f")
    assert _edits_since_creation(rewritten) == ("3e8ad17", "3d4956f")
    assert _edits_since_creation(clean) == ()
