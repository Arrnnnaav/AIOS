"""Evidence files may not publish the raw values the audit keeps out.

D122 excludes HWND and PID from the retained transcript, and D125 replaced the
bare digest over the target binding with a keyed commitment precisely because
those two fields are guessable. An evidence document printing the handle and
process id defeats both at once: it hands a reader the values the transcript
withholds, and it supplies the plaintext that makes a commitment checkable.

An independent review found one such line. It was a pattern, not an instance --
five more sat in four other files.

Handles and process ids also have no evidentiary weight after the run: the
window is gone, the id is reused, and nothing about the finding depends on
them. Redacting them costs the record nothing.
"""

import re
from pathlib import Path

import pytest

EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "evidence"

#: `hwnd 264482`, `hwnd: 264482`, `hwnd `264482``, `pid 29768`. Three digits is
#: the floor because a real handle is never that short, and a shorter number in
#: prose ("pid 1") is far more likely to be an example than a real reading.
_RAW_TARGET = re.compile(r"\b(hwnd|pid)\b[\s:=]*`?\d{3,}", re.IGNORECASE)


#: Evidence whose BYTES are bound by digest into an adoption record. Editing
#: one breaks the content-addressed chain that makes an adoption trustworthy --
#: the tests that check installed bytes against their accepted candidate fail
#: immediately, which is the mechanism working. Redaction has to happen through
#: a new adoption, not by rewriting an accepted artifact, so these two are
#: exempted here and carried as a follow-up rather than silently edited.
#:
#: This exemption is a list, not a pattern: a new evidence file cannot land in
#: it by accident, and anything not named here is scanned.
_DIGEST_BOUND = {
    "add-slide-candidate-acceptance.md",
    "open-extensions-candidate-acceptance.md",
}


def _documents():
    return sorted(
        document
        for document in EVIDENCE.rglob("*.md")
        if document.name not in _DIGEST_BOUND
    )


def test_the_exempted_documents_still_exist_and_are_still_bound():
    """An exemption for a file that has been renamed or deleted is an
    exemption for nothing, and would quietly stop covering the case it was
    written for."""

    for name in _DIGEST_BOUND:
        assert (EVIDENCE / name).is_file(), name


def test_there_are_evidence_documents_to_check():
    """Non-vacuity: a glob that matches nothing would make the scan below pass
    while checking no files at all (D018)."""

    documents = _documents()
    assert len(documents) >= 10
    assert any(d.name.startswith("act-") for d in documents)


def test_no_evidence_document_publishes_a_raw_handle_or_process_id():
    offenders = []
    for document in _documents():
        for number, line in enumerate(
            document.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if _RAW_TARGET.search(line):
                offenders.append(f"{document.name}:{number}: {line.strip()}")
    assert not offenders, "raw target values in evidence:\n" + "\n".join(offenders)


@pytest.mark.parametrize(
    "line",
    [
        "**Target:** `powerpnt.exe`, hwnd `264482`, pid `29768`",
        "the approved window (hwnd 1706624)",
        "hwnd: 263404 was bound",
        "PID 17856 owned it",
    ],
)
def test_the_scan_catches_a_planted_handle(line):
    """Non-vacuity: a pattern that cannot fire proves nothing about the files
    it passed over."""

    assert _RAW_TARGET.search(line)


@pytest.mark.parametrize(
    "line",
    [
        "the exact HWND already bound into the displayed proposal",
        "hwnd [redacted 10 Sep 2026, D122]",
        "resolve the approved window's owning PID",
        "manifest c048e47b2ec066ae23aa62d1aa18471a1f0118c47a1320a086859731cd63925e",
    ],
)
def test_the_scan_leaves_prose_and_digests_alone(line):
    """A guard that fires on ordinary sentences gets suppressed, and then it
    guards nothing."""

    assert not _RAW_TARGET.search(line)
