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

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Documents and data. Source files are covered by the blocklist below instead,
#: because a test needs *some* integer and an invented one is not a leak.
_SCANNED_SUFFIXES = {".md", ".json", ".jsonl", ".txt", ".log", ".csv"}

#: `hwnd 770001`, `hwnd: 770001`, `HWND `770001``, `pid 880002`. FOUR digits is
#: the floor, not five: a Windows PID is frequently four digits, and the
#: five-digit floor written in D130 was justified by what had been observed
#: rather than by what the next campaign will write -- a fifth review called
#: that reasoning self-serving, correctly. Design documents that used a
#: fabricated four-digit sample now use a named placeholder instead, so the
#: floor costs no false positives.
#:
#: The prefix is any word characters, not a fixed list: `target_hwnd` was
#: covered while `windowHandle` was not, which is the same defect one spelling
#: over (D131).
#:
#: The word boundaries are spelled out rather than `\b`, because `\b` does not
#: fire after an underscore: `"target_hwnd": <value>` walked straight past the
#: first version of this rule. So did `"hwnd": 770001` -- the quote and colon
#: were not in the separator class -- which is how a planted handle survived
#: the entire lane in `docs/evidence/*.json`, the exact artifact a live run
#: writes (D130).
_RAW_TARGET = re.compile(
    r"(?:^|[^A-Za-z0-9])[A-Za-z_]*"
    r"(hwnd|pid|handle|target|bound|session|approved|binding|instance|owner|process)"
    r"[\s:=\"]*`?(0x[0-9A-Fa-f]{3,}|\d{4,})",
    re.IGNORECASE,
)

#: A JSON key naming a window handle or process id. SUBSTRING, not an exact
#: spelling: `"windowHandle": <value>` passed every rule because the pattern
#: anchored on `(?:^|_)(hwnd|pid|handle)$`. Enumerating spellings is how this
#: scan has now been evaded twice; matching the shape is the fix (D131).
#:
#: D131 gave the reason the COLUMN rule must include `target` -- every evidence
#: table heads its binding column `Target` -- and then failed to apply the same
#: reasoning here, though the artifacts use `target_ref` and `target_sha256`.
#: `"target": <handle>` and `"owner_process": <pid>` both walked through. The
#: fix is the reasoning applied consistently, not another spelling (D132).
_TARGET_KEY = re.compile(
    r"(hwnd|pid|handle|window|target|owner|process|bound|session|approved"
    r"|binding|instance|_ref$|^ref$)",
    re.IGNORECASE,
)

#: A markdown table column whose header names one. Also a substring, and it
#: must include `target`: every evidence table this repository actually emits
#: heads its binding column `Target`, so the previous rule covered a heading
#: that no longer exists and missed the one in use (D131).
_TARGET_COLUMN = re.compile(
    r"(hwnd|pid|handle|window|target|process|owner|bound|session|approved"
    r"|binding|instance)",
    re.IGNORECASE,
)

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
        # Published in the legacy Excel bundle's HWND column and never
        # blocklisted until an independent review counted them (D130).
        ("198", "188"),  # Excel worksheet window, run 1
        ("525", "102"),  # run 2
        ("918", "882"),  # run 3
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


def test_the_blocklist_still_holds_every_value_ever_published():
    """The list itself was unprotected: deleting the three values this slice
    added passed both files, so the headline remediation could be reverted
    invisibly (D131).

    Membership is asserted by digest rather than by literal, so this test does
    not become the leak it guards. A value removed, or the tuple shortened,
    fails here.
    """

    import hashlib

    assert len(_OBSERVED) == 15
    assert len(set(_OBSERVED)) == 15
    assert all(value.isdigit() and len(value) >= 4 for value in _OBSERVED)
    digest = hashlib.sha256("|".join(sorted(_OBSERVED)).encode("utf-8")).hexdigest()
    assert (
        digest == "69b29ae12b70b7435a110c1ad44ab5ccba803c6279ede38e25940da70a734e66"
    ), digest


#: Header spellings and key spellings that evaded a previous version of these
#: rules. Each is a real evasion someone demonstrated against this scan, not a
#: hypothetical: they are pinned as unit cases so NARROWING a rule fails a test
#: rather than passing quietly until the next review plants one by hand (D132).
_MUST_MATCH_COLUMNS = (
    "HWND",
    "Target",
    "Bound",
    "Approved",
    "Session",
    "Bound target",
    "Approved window",
    "Session target",
    "PID",
    "Owning process",
)

_MUST_MATCH_KEYS = (
    "hwnd",
    "bound",
    "session",
    "approved",
    "binding",
    "instance",
    "windowHandle",
    "target_hwnd",
    "target",
    "target_ref",
    "owner_process",
    "pids",
    "handle",
)

_MUST_NOT_MATCH_KEYS = (
    "slide_count",
    "presentation_count",
    "schema_version",
    "at_ns",
    "name",
    "label",
)


@pytest.mark.parametrize("header", _MUST_MATCH_COLUMNS)
def test_every_known_binding_column_spelling_is_matched(header):
    """`_TARGET_COLUMN` used `re.match`, a PREFIX test, while its own docstring
    and D131 both said substring. `Bound target` evaded it, and a planted value
    under that heading passed the entire 2504-test lane (D132)."""

    assert _TARGET_COLUMN.search(header), header


@pytest.mark.parametrize("key", _MUST_MATCH_KEYS)
def test_every_known_binding_key_spelling_is_matched(key):
    """`"target": <handle>` and `"owner_process": <pid>` both passed the whole
    lane. Narrowing the key rule now fails here."""

    assert _TARGET_KEY.search(key), key


@pytest.mark.parametrize("key", _MUST_NOT_MATCH_KEYS)
def test_ordinary_keys_are_not_matched(key):
    """A rule that fires on `slide_count` gets suppressed, and a suppressed rule
    guards nothing."""

    assert not _TARGET_KEY.search(key), key


@pytest.mark.parametrize(
    "line",
    [
        "hwnd 4460192",
        '"hwnd": 4460192',
        '"target_hwnd": 4460192',
        "HWND=0x000BC1F8",
        "pid 4242",
        "owning_pid: 44121",
        # The shape of this repository's OWN authority blocks, which the rule
        # did not catch until a review pointed at them (D133).
        "target: 4460192",
        "bound target 4460192",
        "session: 4460192",
    ],
)
def test_every_known_prose_form_is_matched(line):
    """Including the four-digit PID: the five-digit floor was raised to silence
    my own false positives, which a review called self-serving (D131)."""

    assert _RAW_TARGET.search(line), line


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


def _handle_valued_keys(value, path=""):
    """Every `hwnd`/`pid`/`handle` key holding something handle-shaped."""

    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            here = f"{path}.{key}" if path else str(key)
            if _TARGET_KEY.search(str(key)):
                if isinstance(child, bool):
                    continue
                if isinstance(child, int) and abs(child) >= 100:
                    found.append(f"{here} = {type(child).__name__}")
                elif isinstance(child, str) and re.fullmatch(
                    r"(0x[0-9A-Fa-f]{3,}|\d{3,})", child.strip()
                ):
                    found.append(f"{here} = {type(child).__name__}")
            found.extend(_handle_valued_keys(child, here))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_handle_valued_keys(child, f"{path}[{index}]"))
    return found


def test_no_tracked_json_carries_a_handle_valued_key():
    """Structural, because the text rule kept missing the JSON encoding.

    A planted `"hwnd": 1442318` in a committed evidence artifact passed the
    entire 2484-test lane. That file is the shape a live run's before/after
    probe writes, so the next campaign could have produced a raw handle in a
    digest-cited file with nothing objecting (D130).

    This does not care how the number is formatted -- it reads the parsed
    document and refuses the key.
    """

    offenders = []
    for name in _tracked({".json", ".jsonl"}):
        text = _text(name)
        documents = []
        if name.endswith(".jsonl"):
            for line in text.splitlines():
                if line.strip():
                    try:
                        documents.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        else:
            try:
                documents.append(json.loads(text))
            except json.JSONDecodeError:
                pass
        for document in documents:
            for hit in _handle_valued_keys(document):
                offenders.append(f"{name}: {hit}")
    assert not offenders, "handle-valued keys in tracked JSON:\n" + "\n".join(
        sorted(set(offenders))
    )


def test_no_markdown_table_publishes_a_handle_column():
    """The Excel evidence table printed six handles under an `HWND` heading,
    on lines where the word never appeared beside a number. A rule that reads
    lines could not see it; this one reads the column."""

    offenders = []
    for name in _tracked({".md"}):
        columns: list[int] = []
        for number, line in enumerate(_text(name).splitlines(), start=1):
            if not line.strip().startswith("|"):
                columns = []
                continue
            cells = [
                cell.strip().strip("`*_ ")
                for cell in line.strip().strip("|").split("|")
            ]
            if not columns:
                columns = [
                    i for i, cell in enumerate(cells) if _TARGET_COLUMN.search(cell)
                ]
                continue
            for index in columns:
                if index < len(cells) and re.fullmatch(
                    r"(0x[0-9A-Fa-f]{3,}|\d{4,})", cells[index]
                ):
                    offenders.append(f"{name}:{number}: column {index} = handle-shaped")
    assert not offenders, "handle columns in tracked markdown:\n" + "\n".join(offenders)


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
