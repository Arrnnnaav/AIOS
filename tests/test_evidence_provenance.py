"""A quoted transcript must describe a run that happened.

This is the one defect class every other test in this repository structurally
cannot see. A digest proves a file's bytes are what a document says they are; it
proves nothing about whether those bytes were captured or composed. Three
separate instances reached `main` before a third independent reviewer found the
second one (D139):

* `3e8ad17` replaced real handles inside quoted pytest SOURCE lines with
  symbolic names the tests did not use, in two files headed "verbatim";
* `301e86b` did the same to a third file, leaving the captured assertion output
  naming the original literal;
* `0ba67c8` claimed to repair that and re-captured only the traceback bodies,
  leaving August summary tallies under September tracebacks -- then a decision
  record asserted the timings differed, when they were byte-identical.

Each edit had a defensible motive: the evidence-hygiene scan objected to a value
inside a transcript, and the scan has no exemption mechanism by design. The
method was the problem. A scan objecting to a record is a claim that the record
is wrong OR that the scan is; deciding it is the record, and editing the record,
inverts the direction of evidence.

**This test narrows the class; it does not close it.** It detects the two
fingerprints those instances actually left. A sufficiently careful splice --
consistent literals, consistent tallies, plausible timings -- passes. That is
why `docs/evidence/falsified-transcripts-disclosure.md` exists as prose: a human
read is the only complete instrument, and a green test here must never be
mistaken for provenance.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_DISCLOSURE = "docs/evidence/falsified-transcripts-disclosure.md"

#: A fenced block that looks like pytest output.
_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)

#: `E       AssertionError: assert 'tree-item' == ''` -- the value the run
#: actually produced, as pytest printed it.
_ACTUAL = re.compile(r"^E\s+AssertionError: assert '([^']*)' ==", re.MULTILINE)

#: A pytest source echo line inside a traceback. FOUR OR MORE spaces, not
#: exactly four: pytest indents the echo by four and the code keeps its own
#: indentation, so the fixture call that matters most sits at eight. The first
#: draft required exactly four, missed every nested line, and therefore reported
#: a splice in a consistent block -- caught by this file's own planted case.
_SOURCE = re.compile(r"^(?:[ ]{4,}|>[ ]+)(\S.*)$", re.MULTILINE)


def _tracked_markdown():
    listed = subprocess.run(
        ["git", "ls-files", "-z", "*.md"], cwd=ROOT, capture_output=True, check=False
    )
    if listed.returncode != 0:
        pytest.skip("not a git work tree")
    return [n for n in listed.stdout.decode("utf-8").split(chr(0)) if n]


def _tracked_evidence_text():
    """Return every tracked text evidence file, including JSONL transcripts.

    The pytest-splice detector below has a more precise parser, but limiting
    the hygiene lane to Markdown would leave a second evidence format outside
    the review surface. JSONL is checked for the same known hand-edit
    fingerprint and for valid line structure; provenance still requires a
    human review of a captured run (D032/D139).
    """

    listed = subprocess.run(
        ["git", "ls-files", "-z", "*.md", "*.jsonl"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if listed.returncode != 0:
        pytest.skip("not a git work tree")
    names = [n for n in listed.stdout.decode("utf-8").split(chr(0)) if n]
    return [(name, _read(name)) for name in names]


def _pytest_blocks(text: str):
    """Every fenced block that carries a pytest assertion failure."""

    return [body for body in _FENCE.findall(text) if _ACTUAL.search(body)]


def spliced_literals(block: str, document: str = ""):
    """Values the run produced that appear nowhere it could have come from.

    The `301e86b` fingerprint. pytest echoes the failing test's source above the
    assertion, so a literal the run produced was visible at capture time -- in
    that echo, or in the mutated production code the surrounding ledger quotes.
    A value present in NEITHER means the two halves came from different runs, or
    from no run.

    Two corrections this function needed, both found by its own first draft:

    * It skipped values that were not alphabetic, to avoid flagging computed
      numbers. But `301e86b`'s spliced value was `'1001'` -- so the rule as
      written would have missed the exact instance it was written for. The
      asserted value is a quoted string literal in every case here, so it is
      checked whatever characters it contains.
    * It searched only the block's source echo, and flagged `'x'` in a genuine
      August transcript, where `x` came from the MUTATION (`return ... or "x"`)
      described in the ledger prose rather than from the test. The document
      outside its `E ` output lines is therefore searched too.
    """

    source = "\n".join(_SOURCE.findall(block))
    prose = "\n".join(
        line for line in document.splitlines() if not line.startswith("E ")
    )
    offenders = []
    for actual in _ACTUAL.findall(block):
        if not actual:
            continue
        if actual in source or actual in prose:
            continue
        offenders.append(actual)
    return offenders


def duplicated_substitutions(block: str):
    """`the real window (the real window)` -- the `3e8ad17` fingerprint.

    A redaction that replaced a value with a phrase already present in the same
    line. Nothing a program prints looks like this; it is the signature of a
    hand edit.
    """

    offenders = []
    for line in block.splitlines():
        for match in re.finditer(r"([a-z][a-z ]{4,40}?) \(\1\)", line, re.IGNORECASE):
            offenders.append(match.group(0))
    return offenders


def _known_unrepairable():
    """Blocks disclosed as redacted-and-unrecapturable, by file.

    NOT an exemption mechanism. These files carry a REDACTED notice at the top
    saying what was changed and why they cannot be re-captured -- the tests were
    deleted, so no run can regenerate them. The disclosure is the artifact; this
    tuple only stops the check failing on a defect it has already reported.

    A file may be listed here ONLY while it carries that notice, which
    `test_a_disclosed_file_actually_carries_its_notice` enforces. Removing the
    notice to quiet a failure re-fails here instead.
    """

    return (
        "docs/superpowers/ledgers/2026-08-20-chromium-warm-up-ledger.md",
        "docs/superpowers/plans/2026-08-20-chromium-warm-up.md",
    )


def test_there_are_transcripts_to_check():
    """Non-vacuity: a scan that finds no blocks passes while checking nothing."""

    blocks = [b for n in _tracked_markdown() for b in _pytest_blocks(_read(n))]

    # MEASURED, not a guessed floor: three assertion-bearing blocks are tracked
    # at this commit. A floor comfortably below reality is the pattern a
    # reviewer found in three other guards here -- it passes while the set it
    # guards silently shrinks (D139).
    assert len(blocks) == 3, len(blocks)
    assert any("tree-item" in b for b in blocks), "the re-captured blocks are gone"


def _read(name):
    return (ROOT / name).read_text(encoding="utf-8", errors="ignore")


def test_no_transcript_reports_a_value_absent_from_its_own_source():
    """The property: the two halves of a failure block came from one run."""

    offenders = []
    for name in _tracked_markdown():
        if name in _known_unrepairable() or name == _DISCLOSURE:
            continue
        document = _read(name)
        for index, block in enumerate(_pytest_blocks(document)):
            for literal in spliced_literals(block, document):
                offenders.append(f"{name} block {index}: reports {literal!r}")
    assert not offenders, (
        "a transcript reports a value its own quoted source never produces, "
        "which means the block was assembled rather than captured:\n"
        + "\n".join(offenders)
    )


def test_no_transcript_carries_a_duplicated_substitution():
    """Ordinary transcripts cannot carry the disclosed hand-edit fingerprint.

    The disclosure itself is checked separately and must retain the fingerprint
    as an honest account of what happened.
    """

    offenders = []
    for name in _tracked_markdown():
        if name in _known_unrepairable() or name == _DISCLOSURE:
            continue
        for index, block in enumerate(_FENCE.findall(_read(name))):
            for hit in duplicated_substitutions(block):
                offenders.append(f"{name} block {index}: {hit!r}")
    assert not offenders, "hand-edited substitution in a transcript:\n" + "\n".join(
        offenders
    )


def test_known_transcript_fingerprint_is_absent_from_jsonl_records():
    """The known hand-edit fingerprint is not allowed to hide in JSONL.

    This does not claim that a spelling scan proves provenance. It closes the
    narrower coverage hole where the same disclosed substitution could be
    moved out of Markdown and remain invisible to the hygiene lane.
    """

    offenders = []
    for name, text in _tracked_evidence_text():
        if not name.casefold().endswith(".jsonl"):
            continue
        if "the real window (the real window)" in text.casefold():
            offenders.append(name)
    assert not offenders, "known edited-transcript fingerprint found in: " + ", ".join(
        offenders
    )


def test_tracked_jsonl_evidence_is_line_valid():
    """Every tracked JSONL evidence file is independently parseable per line."""

    import json

    for name, text in _tracked_evidence_text():
        if not name.casefold().endswith(".jsonl"):
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                pytest.fail(f"{name}:{line_number} is not JSONL: {exc}")
            assert isinstance(value, dict), f"{name}:{line_number} is not a JSON object"


def test_the_disclosed_files_still_show_what_was_disclosed():
    """A disclosure is only worth something while the evidence is still there."""

    for name in _known_unrepairable():
        text = _read(name)
        assert "REDACTED" in text, f"{name} no longer carries its notice"
        assert "falsified-transcripts-disclosure" in text, name
        assert duplicated_substitutions(text), (
            f"{name} no longer contains the substitution it discloses; either it "
            "was quietly cleaned up, or the disclosure is now describing nothing"
        )


def test_a_disclosed_file_actually_carries_its_notice():
    """The listing above is not an exemption: a file may appear in it only while
    it carries the notice, so adding a name to silence a failure fails here."""

    for name in _known_unrepairable():
        assert (ROOT / name).is_file(), name
        assert "not verbatim" in _read(name), name


def test_the_disclosure_document_exists_and_names_every_commit():
    """D034: the account of what happened must be recorded, not remembered."""

    disclosure = ROOT / "docs" / "evidence" / "falsified-transcripts-disclosure.md"
    assert disclosure.is_file()
    text = disclosure.read_text(encoding="utf-8")
    for commit in ("3e8ad17", "301e86b", "0ba67c8", "3d4956f"):
        assert commit in text, commit


def test_the_scan_catches_both_planted_fingerprints():
    """A check that cannot fire proves nothing about the files it passed."""

    spliced = (
        "    def test_x(w):\n"
        '        w(_FakeElement(PID, "SAMPLE_ID"))\n'
        '>       assert read(H) == ""\n'
        "E       AssertionError: assert 'tree-item' == ''\n"
    )
    assert spliced_literals(spliced) == ["tree-item"]

    # The real `301e86b` shape: a NUMERIC spliced value. The first draft skipped
    # non-alphabetic values and would have missed the very instance this file
    # was written for.
    numeric = spliced.replace("'tree-item'", "'1001'")
    assert spliced_literals(numeric) == ["1001"]

    consistent = spliced.replace("SAMPLE_ID", "tree-item")
    assert spliced_literals(consistent) == []

    # A value introduced by the mutation the ledger describes, not by the test.
    from_mutation = (
        "    def test_y(w):\n"
        "        w(_FakeElement(PID, \"\"))\n"
        '>       assert read(H) == ""\n'
        "E       AssertionError: assert 'x' == ''\n"
    )
    assert spliced_literals(from_mutation) == ["x"]
    assert spliced_literals(from_mutation, 'return element.Id or "x"') == []

    assert duplicated_substitutions("then the real window (the real window) whose")
    assert not duplicated_substitutions("then the real window (hwnd redacted) whose")
