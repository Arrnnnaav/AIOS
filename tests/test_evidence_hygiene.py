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
_SCANNED_SUFFIXES = {
    ".md",
    ".json",
    ".jsonl",
    ".txt",
    ".log",
    ".csv",
    ".ini",
    ".cfg",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
    ".html",
}

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

#: Geometry, not identity: `window.captured_bbox` is four coordinates, and a
#: rule that flags them is a rule someone switches off (D134).
#:
#: EXACT segment match, not substring. Measured across every tracked JSON, the
#: substring form rescued exactly four values -- one `captured_bbox` in one
#: fixture -- while opening `{"bound_window_size_hint": <handle>}`, which passed
#: every rule in this file. An exclusion whose reach exceeds its purpose is a
#: hole shaped like a feature (D138).
_GEOMETRY_WORDS = frozenset(
    (
        "bbox",
        "bounds",
        "rect",
        "region",
        "geometry",
        "size",
        "width",
        "height",
        "coord",
        "coords",
    )
)


def _is_geometry(key) -> bool:
    """True when the key's HEAD NOUN -- its last segment -- is a geometry word.

    Segment membership alone is not enough, and the fix caught its own first
    draft: `bound_window_size_hint` splits to `bound|window|size|hint`, so
    "contains a geometry segment" still rescued the hole this was meant to
    close. In these key names the last segment IS the thing and the earlier
    ones qualify it, so `captured_bbox` and `window.bounds` are geometry while
    `bound_window_size_hint` and `sizeable_window_handle` are not.
    """

    segments = [s for s in re.split(r"[^A-Za-z]+", str(key).lower()) if s]
    return bool(segments) and segments[-1] in _GEOMETRY_WORDS

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
#: Binding vocabulary. One list, used by all three rules, so widening the
#: vocabulary widens every rule at once instead of one of them (D134).
_BINDING_WORDS = (
    r"hwnd|pid|handle|window|target|bound|session|approved|binding|instance"
    r"|owner|process|winid"
)

#: A binding word and a handle-shaped number within 40 characters, in EITHER
#: order, whatever sits between them. The previous rule enumerated separators
#: (`[\s:="]*`), so `window (7734512)`, `hwnd [7734512]`, `hwnd **7734512**`
#: and `owner, 7734512` all walked through -- the seventh review evaded the
#: scan twice more that way. This is a proximity rule rather than a punctuation
#: rule: it cannot be defeated by inventing new punctuation, only by moving the
#: number far from any word that names a binding (D134).
#:
#: Known limit, stated rather than discovered later: the reverse direction
#: (`<number> ... <word>`) allows punctuation between them, not prose. "7734512
#: was the bound window" is not caught, because widening that branch to span
#: words makes every four-digit measurement in a sentence containing "window"
#: a hit. The blocklist covers real values regardless of phrasing; this rule
#: covers shape.
#: The number must stand alone: not part of a version (`16.0.20326.20112`), a
#: dimension (`976x1028`), a date (`2026-08-25`), a range (`39-66s`) or a
#: longer identifier. Without that the proximity rule fires on every measured
#: figure in the repository, and a rule that fires constantly is a rule someone
#: switches off.
_STANDALONE = (
    r"(?<![\w.\-×x])(?:0x[0-9A-Fa-f]{3,}|\d{4,})(?![\w.\-×x])"
)

_NEAR_TARGET = re.compile(
    rf"(?:{_BINDING_WORDS})[^A-Za-z0-9\n]{{0,24}}?{_STANDALONE}"
    rf"|{_STANDALONE}[^A-Za-z0-9\n]{{0,12}}?(?:{_BINDING_WORDS})",
    re.IGNORECASE,
)

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
        # Found by the proximity rule itself, in a spec no earlier rule read
        # (D134).
        ("659", "02"),  # foreground window, control-bar coexistence spike
    )
)


#: Digit-group separators, and the padded bare-hex rendering.
#:
#: Every rule below requires a run of four or more digits. `4 460 192` has no
#: such run -- the longest token is three digits -- so the pattern rule, the
#: proximity rule, the column rule AND the blocklist all miss it at once. The
#: activation review demonstrated exactly that, and the evasion is not
#: contrived: `act-acceptance-campaign-2026-09-11.md` already writes
#: "94 400 / 94 367 / 94 366 bytes", so this is the repository's own house
#: style. An honest author could leak a handle this way by accident.
#:
#: Seven rounds of widening all widened which WORDS name a binding and which
#: PUNCTUATION may sit between a word and a number. None addressed which
#: RENDERINGS of the number count as the number. That is the class, and
#: normalising before matching closes it for every rule at once rather than
#: for whichever rule the next reviewer happens to probe (D137).
_GROUPED = re.compile(r"(?<=[0-9])[    ,_'’](?=[0-9]{3}(?![0-9]))")

#: `000BC1F8` -- a handle as Spy++ and the Windows debuggers print it, with no
#: `0x`. The hex branch required the prefix, and a bare run of hex digits
#: contains no four-digit DECIMAL run, so it evaded the same four rules. The
#: leading zeros are what distinguish it from a commit or digest prefix, which
#: is why only the padded form is rewritten: `28dbaf2d` stays what it is.
_PADDED_HEX = re.compile(r"(?<![0-9A-Za-z_])(00[0-9A-Fa-f]{4,8})(?![0-9A-Za-z_])")


def _normalise(text: str) -> str:
    """One rendering of a number, for the SHAPE rules below.

    A best-effort normaliser, and stated as one. An activation re-review
    defeated its first version with `2,64,482` -- lakh grouping, entirely
    natural on an IST-anchored project -- and with figure spaces, group sizes
    other than three, line-break splits and HTML entities. Each could be added
    to the separator class, and that is the enumeration treadmill this scan has
    already ridden for seven rounds.

    So the two rules are now split by what each can honestly claim (D138):

    * `_blocklisted(..., prose=True)` is TOTAL for known values. It compares
      digits to digits with every other character removed, so no rendering of a
      real observed handle can hide from it. That invariant IMPLIES the
      property, for those values.
    * This normaliser plus the proximity rules is a heuristic for values nobody
      has observed yet. It CORRELATES with the property and cannot imply it: an
      unknown number in an unanticipated rendering is indistinguishable from
      prose. Widening it is worth doing and is not worth calling complete.

    Stating the weaker claim is the point. The previous version asserted that
    normalising "makes the invariant imply the property", which stopped being
    true the moment someone chose a different separator.
    """

    previous = None
    while previous != text:
        previous = text
        text = _GROUPED.sub("", text)
    return _PADDED_HEX.sub(lambda m: "0x" + m.group(1), text)


def _digits_only(text: str) -> str:
    """Every digit, in order, with everything else discarded.

    Rendering-independent by construction rather than by enumeration: spaces,
    commas, thin spaces, line breaks, markup and named entities all vanish
    because nothing but a digit survives.

    The cost is matches spanning two adjacent numbers, which is the right trade
    for sixteen values that must never reappear in a document, and the wrong one
    for a shape rule.
    """

    return "".join(c for c in text if c.isdigit())


#: A whole 40- or 64-character hex digest is removed before digits are
#: compared (D155): a handle is never rendered as one, and random digests matched
#: a 5-digit observed value often enough to fire on honest campaign records. A
#: JSON number that is a float with a non-zero fraction (a millisecond timing)
#: is skipped by TYPE in `_blocklisted`, not by text shape -- `264.482` written
#: as prose is a dot-grouped rendering and must still match.
_NOT_A_HANDLE = re.compile(r"(?<![0-9A-Za-z])(?:[0-9a-f]{64}|[0-9a-f]{40})(?![0-9A-Za-z])")


def _handle_digits(text: str) -> str:
    return _digits_only(_NOT_A_HANDLE.sub(" ", text))


def _blocklisted(text: str, *, prose: bool):
    """Observed values present in `text`.

    Two modes, because the two kinds of file differ in what an author can
    write, and one rule would be either leaky or unusable:

    * `prose=True` (documents) compares DIGITS ONLY -- total against any
      rendering that adds no digits of its own. Valid JSON is parsed first so
      digits in independent fields cannot concatenate into a fictitious value.
    * `prose=False` (source, fixtures, anything else) compares the normalised
      text. A Python literal cannot contain a space, `4_460_192` can and is
      covered, and digits-only here would flag THIS file: `_OBSERVED` splits
      each value across two string literals so the blocklist is not itself the
      leak, and concatenating every digit in the file puts them back together.
      A rule that always fails on its own source teaches nothing (D138).
    """

    if prose:
        try:
            document = json.loads(text)
        except json.JSONDecodeError:
            document = None
        if not isinstance(document, (dict, list)):
            # Not a JSON record (a bare `264.482` parses as a float): prose.
            haystack = _handle_digits(text)
            return [value for value in _OBSERVED if value in haystack]

        def scalars(value):
            if isinstance(value, dict):
                for child in value.values():
                    yield from scalars(child)
            elif isinstance(value, list):
                for child in value:
                    yield from scalars(child)
            elif isinstance(value, float) and not value.is_integer():
                return  # a measured fraction, never a handle (D155)
            elif value is not None:
                yield str(value)

        values = [_handle_digits(scalar) for scalar in scalars(document)]
        return [
            value for value in _OBSERVED if any(value in scalar for scalar in values)
        ]

    haystack = _normalise(text)
    return [value for value in _OBSERVED if value in haystack]


def test_json_blocklist_does_not_join_distinct_scalar_values():
    """Unrelated JSON fields must not concatenate into a fictitious handle."""

    value = _OBSERVED[0]
    record = json.dumps({"first_count": value[:3], "second_count": value[3:]})

    assert _blocklisted(record, prose=True) == []


def test_json_blocklist_still_finds_a_complete_handle_in_one_scalar():
    """A real observed value in a JSON string remains a leak."""

    value = _OBSERVED[0]
    record = json.dumps({"target_ref": value})
    numeric_record = json.dumps({"unrelated_numeric_field": int(value)})

    assert _blocklisted(record, prose=True) == [value]
    assert _blocklisted(numeric_record, prose=True) == [value]


def _file_blocklisted(name: str, text: str):
    """Apply the text/value blocklist with the file's record boundaries."""

    suffix = Path(name).suffix.lower()
    prose = suffix in _SCANNED_SUFFIXES
    if suffix != ".jsonl":
        return _blocklisted(text, prose=prose)

    records = [line for line in text.splitlines() if line.strip()]
    try:
        for record in records:
            json.loads(record)
    except json.JSONDecodeError:
        # A malformed record may split a blocked value across lines. Fall back
        # to the complete artifact rather than letting line boundaries hide it.
        return _blocklisted(text, prose=prose)
    return sorted(
        {
            value
            for record in records
            for value in _blocklisted(record, prose=prose)
        }
    )


def test_jsonl_does_not_join_distinct_valid_record_values():
    """Separate well-formed JSONL records remain separate scan units."""

    value = _OBSERVED[0]
    records = "\n".join(
        (
            json.dumps({"first_count": value[:3]}),
            json.dumps({"second_count": value[3:]}),
        )
    )

    assert _file_blocklisted("fixture.jsonl", records) == []


def test_malformed_jsonl_cannot_split_a_blocklisted_value_across_lines():
    """Malformed records fall back to scanning the complete artifact."""

    value = _OBSERVED[0]
    malformed = f'{{"first":"{value[:3]}"\nnot-json:"{value[3:]}"'

    assert _file_blocklisted("fixture.jsonl", malformed) == [value]


def _document_offenders(text: str):
    """Every line a shape rule objects to, as (line number, line).

    ONE function, used by the file scan below AND by the unit tests that pin the
    rules. The re-review found that the tests asserted on the regex OBJECTS
    while the scan applied them separately, so deleting `_NEAR_TARGET` from the
    scan left all 70 tests green -- the guard itself unguarded, one level above
    where that was last fixed (D138).
    """

    offenders = []
    for number, line in enumerate(_normalise(text).splitlines(), start=1):
        if _RAW_TARGET.search(line) or _NEAR_TARGET.search(line):
            offenders.append((number, line))
    return offenders


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

    assert len(_OBSERVED) == 16
    assert len(set(_OBSERVED)) == 16
    assert all(value.isdigit() and len(value) >= 4 for value in _OBSERVED)
    digest = hashlib.sha256("|".join(sorted(_OBSERVED)).encode("utf-8")).hexdigest()
    assert (
        digest == "2088e11befa43924512a2f82a5018348b648df4178b1ef78255b332293caec61"
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
        # The seventh review's evasions: punctuation the separator class did
        # not enumerate, which is why the rule is now proximity-based (D134).
        "The approved PowerPoint window (7734512) was owned",
        "hwnd [7734512]",
        "hwnd **7734512**",
        "owner, 7734512",
        "7734512 (bound window)",
    ],
)
def test_every_known_prose_form_is_matched(line):
    """Including the four-digit PID: the five-digit floor was raised to silence
    my own false positives, which a review called self-serving (D131)."""

    assert _RAW_TARGET.search(line) or _NEAR_TARGET.search(line), line


@pytest.mark.parametrize(
    "line",
    [
        # The activation review's evasion, in every separator this repository
        # or a plausible author could produce.
        # Synthetic values: 7 734 512 and 5 120 are not in `_OBSERVED`. The
        # first draft of this list wrote a real blocklisted pid in grouped
        # form, and the blocklist test below caught it -- the fifth time a test
        # written for this scan republished a value the scan exists to
        # suppress. The normalised blocklist is why it was caught this time.
        "The approved PowerPoint window (7 734 512) was bound.",
        "hwnd 7,734,512",
        "target: 7_734_512",
        "window 7 734 512",
        "pid 5 120",
        # The padded bare-hex rendering, as Spy++ prints it.
        "hwnd 000BC1F8",
        "bound window (000BC1F8)",
    ],
)
def test_every_known_rendering_of_a_handle_is_matched(line):
    """Renderings, not spellings. Seven rounds widened which words name a
    binding and which punctuation may separate them; none asked whether the
    number was written as a number. `4 460 192` contains no four-digit run, so
    it defeated all four rules simultaneously (D137)."""

    normalised = _normalise(line)

    assert _RAW_TARGET.search(normalised) or _NEAR_TARGET.search(normalised), normalised


def test_the_normaliser_leaves_real_numbers_and_digests_alone():
    """A normaliser that rewrote everything would make every rule fire on every
    measured figure, and a rule that fires constantly gets switched off."""

    # Separators only join a group of exactly three digits.
    assert _normalise("39-66s") == "39-66s"
    assert _normalise("16.0.20326.20112") == "16.0.20326.20112"
    assert _normalise("2026-08-25") == "2026-08-25"
    assert _normalise("976x1028") == "976x1028"
    # Two words that merely sit beside each other are not a grouped number.
    assert _normalise("Phase 2 runs") == "Phase 2 runs"
    # A digest or commit prefix is not a padded handle.
    assert _normalise("manifest 28dbaf2d") == "manifest 28dbaf2d"
    assert _normalise("READY at 45d1323") == "READY at 45d1323"
    # But the leading-zero form is.
    assert _normalise("000BC1F8") == "0x000BC1F8"


def test_no_rendering_of_a_blocklisted_value_survives_the_prose_check():
    """TOTAL for known values -- the one claim in this file that is an
    implication rather than a correlation.

    The enumerated normaliser was defeated by every rendering below. Comparing
    digits to digits cannot be defeated by any of them, because none of them
    changes which digits are present or their order (D138).
    """

    value = _OBSERVED[0]
    for rendering in (
        " ".join((value[:3], value[3:])),
        ",".join((value[:1], value[1:3], value[3:])),  # lakh grouping
        chr(0x2007).join((value[:2], value[2:])),  # FIGURE SPACE
        chr(10).join((value[:4], value[4:])),  # split across a line break
        "&nbsp;".join((value[:2], value[2:])),  # named HTML entity
        ".".join((value[:3], value[3:])),
        "**".join((value[:2], value[2:])),  # markdown emphasis mid-number
    ):
        assert value not in rendering, rendering
        assert _blocklisted(rendering, prose=True) == [value], rendering

    # The honest limit, found while writing this case rather than by the next
    # reviewer: a NUMERIC character reference injects digits of its own, so
    # `&#32;` both splits the value and adds `32` between the halves.
    # Digits-only is total against renderings that add no digits; it is not
    # total against an encoding that does. Nothing here emits numeric entities,
    # and the shape rules still see the surrounding binding word.
    assert _blocklisted("&#32;".join((value[:2], value[2:])), prose=True) == []


def test_the_document_scan_uses_both_shape_rules():
    """The unit tests pinned the REGEX OBJECTS while the file scan applied them
    separately, so deleting `_NEAR_TARGET` from the scan left all 70 tests
    green. Both now go through `_document_offenders`, and each case below is
    matched by exactly one rule -- so removing either from the shared function
    fails here (D138)."""

    # `_RAW_TARGET` only. The proximity rule requires the number to STAND
    # ALONE, so a trailing `x` -- the dimension guard that stops it firing on
    # `976x1028` -- takes it out while the enumerated rule still matches.
    raw_only = "hwnd: 7734512x"
    # `_NEAR_TARGET` only: punctuation the separator class does not enumerate.
    near_only = "hwnd **7734512**"

    assert _RAW_TARGET.search(raw_only) and not _NEAR_TARGET.search(raw_only)
    assert _NEAR_TARGET.search(near_only) and not _RAW_TARGET.search(near_only)

    assert _document_offenders(raw_only) == [(1, raw_only)]
    assert _document_offenders(near_only) == [(1, near_only)]


def test_the_document_scan_normalises_before_matching():
    """And that `_normalise` is applied INSIDE the shared function rather than
    by each caller: a caller that forgot it would scan raw text and miss every
    grouped rendering while every unit test here still passed."""

    grouped = "hwnd 7 734 512"

    assert not _RAW_TARGET.search(grouped) and not _NEAR_TARGET.search(grouped)
    assert _document_offenders(grouped)


def test_the_blocklist_scan_uses_the_shared_helper():
    """Same defect, same fix: the comparison lived inline in the file scan, so
    dropping rendering-independence there would have passed every unit test
    written about it."""

    value = _OBSERVED[0]
    grouped = " ".join((value[:2], value[2:]))

    assert _blocklisted(grouped, prose=True) == [value]
    # Source files keep the literal comparison, or this very file would fail.
    assert _blocklisted(grouped, prose=False) == []


def test_a_geometry_word_inside_a_binding_key_is_not_an_exclusion():
    """`bound_window_size_hint` contains `size`, so the substring exclusion
    rescued it and a handle under that key passed every rule. Segment equality
    keeps the real geometry keys excluded and closes the hole (D138)."""

    assert _is_geometry("captured_bbox")
    assert _is_geometry("window.bounds")
    assert _is_geometry("displayed_rect")
    assert not _is_geometry("bound_window_size_hint")
    assert not _is_geometry("target_hwnd")
    assert not _is_geometry("sizeable_window_handle")


def test_the_scan_covers_the_places_handles_have_actually_leaked():
    """Non-vacuity, and specifically about scope: every directory that has
    leaked a handle in this repository must be inside the scanned set. A scan
    that passes because it looks nowhere is the defect being fixed here."""

    scanned = set(_tracked(_SCANNED_SUFFIXES))

    assert len(scanned) >= 50
    assert any(n.startswith("docs/evidence/") for n in scanned)
    assert any("payload/docs/evidence/" in n for n in scanned)
    assert any(  # moved here byte for byte when plugins were retired (D193)
        n.startswith("docs/archive/retained-plugins/") and "acceptance-records" in n
        for n in scanned
    )
    assert any(n.startswith("docs/superpowers/") for n in scanned)
    assert any(n.endswith(".jsonl") for n in scanned)


def _string_scalars(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _string_scalars(child)
    elif isinstance(value, list):
        for child in value:
            yield from _string_scalars(child)


def _structured_offenders(name: str, text: str):
    """Shape rules applied to a JSON record's STRING VALUES, one at a time.

    The proximity rule reads adjacency, and adjacency between JSON keys is an
    accident of sort order: a real manager transcript of 1,000+ records put
    `"sequence":1000,` beside `"target_sha256"` and tripped it on every later
    line (D165). Handle-valued KEYS are covered by `_handle_valued_keys` and
    known values by the blocklist, both unchanged. Returns None when the file
    is not cleanly parseable JSON, so it is scanned as text instead.
    """

    suffix = Path(name).suffix.lower()
    if suffix not in {".json", ".jsonl"}:
        return None
    try:
        records = (
            [json.loads(line) for line in text.splitlines() if line.strip()]
            if suffix == ".jsonl"
            else [json.loads(text)]
        )
    except json.JSONDecodeError:
        return None
    found = []
    for number, record in enumerate(records, start=1):
        for scalar in _string_scalars(record):
            for _, line in _document_offenders(scalar):
                found.append((number, line))
    return found


def test_no_tracked_document_publishes_a_raw_handle_or_process_id():
    offenders = []
    for name in _tracked(_SCANNED_SUFFIXES):
        text = _text(name)
        structured = _structured_offenders(name, text)
        hits = structured if structured is not None else _document_offenders(text)
        for number, line in hits:
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
            if _TARGET_KEY.search(str(key)) and not _is_geometry(key):
                if isinstance(child, bool):
                    continue
                if isinstance(child, (int, float)) and abs(child) >= 100:
                    found.append(f"{here} = {type(child).__name__}")
                elif isinstance(child, str) and re.fullmatch(
                    r"(0x[0-9A-Fa-f]{3,}|\d{3,})", child.strip()
                ):
                    found.append(f"{here} = {type(child).__name__}")
            found.extend(_handle_valued_keys(child, here))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            here = f"{path}[{index}]"
            # A list under a binding key hides its scalars from the dict branch
            # above: `"bound_windows": [7734512]` passed every rule until the
            # seventh review planted it (D134).
            if (
                _TARGET_KEY.search(path)
                and not _is_geometry(path)
                and not isinstance(child, bool)
            ):
                if isinstance(child, (int, float)) and abs(child) >= 100:
                    found.append(f"{here} = {type(child).__name__}")
                elif isinstance(child, str) and re.fullmatch(
                    r"(0x[0-9A-Fa-f]{3,}|\d{3,})", child.strip()
                ):
                    found.append(f"{here} = {type(child).__name__}")
            found.extend(_handle_valued_keys(child, here))
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
        for number, line in enumerate(
            _normalise(_text(name)).splitlines(), start=1
        ):
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
        for value in _file_blocklisted(name, _text(name)):
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



def test_digests_and_fractional_timings_are_not_read_as_handles():
    """D155: honest campaign records carry digests and millisecond floats; the
    total scan must not fire on them, or it forces edits of retained evidence."""

    value = _OBSERVED[0]
    digest = ("ab" + value + "cd" * 30)[:64]
    record = json.dumps({"at_s": float(f"{value[:3]}.{value[3:]}"), "sha256": digest})
    assert _blocklisted(record, prose=True) == []
    assert _blocklisted(f"| 1 | `{digest}` |\n", prose=True) == []
    # Prose keeps the total rule: a dot-grouped rendering is still a handle.
    assert _blocklisted(f"{value[:3]}.{value[3:]}", prose=True) == [value]


@pytest.mark.parametrize(
    "rendering",
    [
        "{v}",
        "{v}.0",
        "window {v}",
        "0x{v}",
        "{a} {b}",
        "{a},{b}",
        "a{v}b",  # glued between hex letters: pins the exemption width (review M20)
        "id-{v}-ffff",
    ],
)
def test_integer_renderings_of_an_observed_handle_are_still_found(rendering):
    """The exemption removes only digests and fractional decimals; every
    integer rendering the total rule was built for still matches."""

    value = _OBSERVED[0]
    text = rendering.format(v=value, a=value[:3], b=value[3:])
    assert _blocklisted(text, prose=True) == [value]
    assert _blocklisted(json.dumps({"x": text}), prose=True) == [value]
    assert _blocklisted(json.dumps({"x": int(value)}), prose=True) == [value]
    assert _blocklisted(json.dumps({"x": float(value)}), prose=True) == [value]


def test_json_key_adjacency_is_not_a_handle_but_a_handle_in_a_value_still_is():
    """D165: the real false positive, and the property that must survive it."""

    adjacent = json.dumps({"sequence": 1000, "target_sha256": "a" * 64}, sort_keys=True)
    assert _document_offenders(adjacent)  # the text rule fires on key adjacency
    assert _structured_offenders("x.jsonl", adjacent) == []
    leaking = json.dumps({"detail": "bound target hwnd 4460192"})
    assert _structured_offenders("x.jsonl", leaking)
    assert _structured_offenders("x.json", json.dumps({"n": [{"note": "target window 0x1A2B3C"}]}))
    assert _structured_offenders("x.jsonl", "not json") is None

