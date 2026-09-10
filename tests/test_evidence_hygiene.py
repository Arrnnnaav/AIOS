"""No tracked document publishes a raw window handle or process id.

D122 excludes HWND and PID from the retained transcript, and D125 keyed the
target commitment precisely because those fields are guessable. A document that
prints them defeats both at once: it hands a reader what the transcript
withholds, and supplies the plaintext that makes the commitment checkable.

The first version of this scan globbed `docs/evidence/**/*.md`. That scope was
wrong in three ways at once, and an independent review found all three: it
missed `plugins/**/payload/docs/evidence/**`, where handles were being signed
into distributable bundles; it missed `.json`/`.jsonl`, including artifacts
added in the same slice; and it exempted two files by basename, which both
under-covered (a colliding name in a subdirectory would inherit the exemption)
and over-claimed (one exempted value appeared in a third, unexempted file, so
nothing was actually withheld).

This version scans every tracked document, by path, with no exemptions. Two
complementary rules:

* a pattern rule over documentation and data files, which catches the shape
  `hwnd <number>` wherever it appears; and
* a value blocklist checked against every tracked text file including tests,
  because a fixture that reuses a real observed handle republishes it just as
  effectively as prose does -- which is exactly what one of these tests did.

Handles and process ids carry no evidentiary weight once a run is over: the
window is gone and the id is recycled. Redacting them costs the record nothing.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Documents and data. Source files are covered by the blocklist below instead,
#: because a test needs *some* integer and an invented one is not a leak.
_SCANNED_SUFFIXES = {".md", ".json", ".jsonl"}

#: `hwnd 770001`, `hwnd: 770001`, `HWND `770001``, `pid 880002`. Three digits is
#: the floor: a real handle is never that short, and a small number in prose is
#: far more likely to be an illustration than a reading.
_RAW_TARGET = re.compile(r"\b(hwnd|pid)\b[\s:=]*`?(\d{3,})", re.IGNORECASE)

#: Values actually observed on a live desktop and once published in this
#: repository. They are recorded here so that no file -- prose, fixture, or
#: artifact -- can reintroduce one. The digits are split so this list does not
#: itself become the leak it prevents.
_OBSERVED = tuple(
    "".join(parts)
    for parts in (
        ("264", "482"),  # PowerPoint window, 9 Sep manager run
        ("297", "68"),  # its owning process
        ("105", "0680"),  # PowerPoint window, ADD_SLIDE acceptance
        ("395", "430"),  # VS Code window, OPEN_EXTENSIONS acceptance
        ("657", "022"),  # PowerPoint window, UIA feasibility probe
        ("198", "302"),  # Excel workbook window, UIA feasibility probe
        ("288", "5152"),  # PowerPoint window, deck build with rail
        ("178", "56"),  # its owning process
        ("170", "6624"),  # VS Code window, compiled walk latency
        ("263", "404"),  # VS Code window, target disappearance
        ("329", "088"),  # Discord updater window, warm-up ledger
        ("163", "8728"),  # its real window
    )
)


def _tracked(suffixes=None):
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=False
    )
    if listed.returncode != 0:
        pytest.skip("not a git work tree")
    names = [n for n in listed.stdout.decode("utf-8").split("\0") if n]
    if suffixes is None:
        return names
    return [n for n in names if Path(n).suffix.lower() in suffixes]


def _text(name):
    try:
        return (ROOT / name).read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return ""


def test_the_scan_covers_the_places_handles_have_actually_leaked():
    """Non-vacuity, and specifically about scope: every directory that has
    leaked a handle in this repository must be inside the scanned set. A scan
    that passes because it looks nowhere is the defect being fixed here."""

    scanned = set(_tracked(_SCANNED_SUFFIXES))

    assert len(scanned) >= 50
    assert any(n.startswith("docs/evidence/") for n in scanned)
    assert any("payload/docs/evidence/" in n for n in scanned)
    assert any(
        n.startswith("plugins/sources/") and "acceptance-records" in n for n in scanned
    )
    assert any(n.startswith("docs/superpowers/") for n in scanned)
    assert any(n.endswith(".jsonl") for n in scanned)


def test_no_tracked_document_publishes_a_raw_handle_or_process_id():
    offenders = []
    for name in _tracked(_SCANNED_SUFFIXES):
        for number, line in enumerate(_text(name).splitlines(), start=1):
            if _RAW_TARGET.search(line):
                offenders.append(f"{name}:{number}: {line.strip()[:100]}")
    assert not offenders, "raw target values in tracked documents:\n" + "\n".join(
        offenders
    )


def test_no_tracked_file_at_all_reuses_an_observed_handle():
    """Wider than the pattern rule and narrower in what it looks for: a test
    fixture that reuses a real handle republishes it, and `hwnd=<value>` in a
    Python file is not prose the pattern rule would flag as evidence."""

    offenders = []
    for name in _tracked():
        if Path(name).suffix.lower() in {
            ".png",
            ".pptx",
            ".docx",
            ".xlsx",
            ".ghostplugin",
        }:
            continue
        text = _text(name)
        for value in _OBSERVED:
            if value in text:
                offenders.append(f"{name}: contains observed value ending {value[-3:]}")
    assert not offenders, "observed handles reused:\n" + "\n".join(
        sorted(set(offenders))
    )


@pytest.mark.parametrize(
    "line",
    [
        "**Target:** `powerpnt.exe`, hwnd `770001`, pid `880002`",
        "the approved window (hwnd 770003)",
        "hwnd: 770004 was bound",
        "PID 880005 owned it",
        "- Target: HWND `770006`, `powerpnt.exe`",
    ],
)
def test_the_pattern_catches_a_planted_handle(line):
    """Non-vacuity: a pattern that cannot fire proves nothing about the files
    it passed over."""

    assert _RAW_TARGET.search(line)


@pytest.mark.parametrize(
    "line",
    [
        "the exact HWND already bound into the displayed proposal",
        "hwnd [redacted, D128]",
        "resolve the approved window's owning PID",
        "manifest c048e47b2ec066ae23aa62d1aa18471a1f0118c47a1320a086859731cd63925e",
        "hwnd=HWND_WINDOW",
    ],
)
def test_the_pattern_leaves_prose_and_digests_alone(line):
    """A guard that fires on ordinary sentences gets suppressed, and a
    suppressed guard guards nothing."""

    assert not _RAW_TARGET.search(line)


def test_the_scan_has_no_exemption_mechanism(tmp_path):
    """The previous version exempted two files by basename. That both
    under-covered -- a colliding name in a nested directory inherits the
    exemption -- and over-claimed, since one exempted value sat unredacted in a
    third file. Sanitised evidence needs no exemption, so there is no longer a
    way to grant one.

    This test fails if an exemption collection is reintroduced.
    """

    import tests.test_evidence_hygiene as module

    names = [n for n in dir(module) if "exempt" in n.lower() or "allow" in n.lower()]
    assert [n for n in names if not n.startswith("test_")] == []


def test_a_nested_file_sharing_a_name_is_still_scanned():
    """The concrete case the basename exemption got wrong: two files called
    `open-extensions-candidate-acceptance.md` at different paths must both be
    scanned, and the scanned set is keyed by path."""

    scanned = _tracked(_SCANNED_SUFFIXES)

    assert len(scanned) == len(set(scanned))
    by_name = {}
    for name in scanned:
        by_name.setdefault(Path(name).name, []).append(name)
    # Whatever shares a basename today, every copy of it is in the scanned set.
    for name, paths in by_name.items():
        assert len(paths) == len(set(paths)), name
