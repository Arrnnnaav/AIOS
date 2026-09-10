"""The ADD_SLIDE evidence renderer refuses what it cannot substantiate.

Every case here is a way someone could end up with a document claiming a
counted campaign that did not happen. Two of them were found by independent
D032 reviews after the renderer was already written and already believed
correct, which is why they are tests rather than comments:

- three copies of ONE record rendered "3/3 passed", because nothing looked
  past the file count;
- three genuinely distinct, individually clean records drawn from two
  DIFFERENT already-rejected attempt sets rendered "3/3 passed", because the
  only cross-record checks were a shared HWND and shared digests -- both true
  of every record for one candidate on one machine.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RENDERER = REPO / "tools" / "render_add_slide_evidence.py"
CANDIDATE = REPO / "plugins/sources/powerpoint/payload/ghostcursor/packs/powerpoint"
ACCEPTED = REPO / "plugins/sources/powerpoint/acceptance-records/add-slide"


def _render(records: Path, out: Path, *extra: str):
    result = subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            "--records",
            str(records),
            "--candidate-root",
            str(CANDIDATE),
            "--out",
            str(out),
            *extra,
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode, (result.stderr or result.stdout)


def _record(**overrides) -> dict:
    """One clean record, in the shape the harness emits."""

    base = {
        "record_kind": "run",
        "is_acceptance_evidence": True,
        "pack_id": "powerpoint",
        "intent_id": "ADD_SLIDE",
        "digests": {
            "pack": "0b099d868a13477ce1ae281062d303f441120a13a427ce1f6bda1bf589d1b5fc",
            "intent": "b977a9e62a2e9810e479bf137c92edffdec9578984399780543642856be3caa3",
            "recipe": "96ad179d9e4349b1846014c2592c113cf7f0ddd6f33c195fecef589cf23dcad1",
        },
        "application_identity": {
            "kind": "executable_version",
            "value": "16.0.20326.20112",
        },
        "target": {
            "target_ref": "window-a1b2c3d4",
            "target_scope": "scope-1",
            "title": "live.pptx - PowerPoint",
            "executable": "powerpnt.exe",
        },
        "outcome": "passed",
        "grounding_provenance": ["uia"],
        "grounded_by_uia_only": True,
        "steps": {"completed": 1, "total": 1},
        "detail": "",
        "run_id": "a" * 32,
        "started_at": "2026-09-04T10:00:00.000+00:00",
        "timing": {
            "first_observation_s": 0.75,
            "first_hint_s": 1.5,
            "verification_started_s": 3.0,
            "ended_s": 3.5,
        },
    }
    base.update(overrides)
    return base


def _write(directory: Path, records: list[dict]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for index, record in enumerate(records, start=1):
        (directory / f"run-{index}.json").write_text(
            json.dumps(record, indent=2, sort_keys=True), encoding="utf-8", newline=""
        )
    return directory


def _campaign(tmp_path: Path, records: list[dict], *, excluded=()) -> Path:
    """An accepted campaign directory, with the sibling `excluded/` the
    renderer requires.

    The sibling is mandatory, not optional: without it every derived count
    reads zero while the document's narrative still describes the recorded
    anomaly, so the document contradicts itself and silently drops a finding.
    """

    directory = _write(tmp_path / "records" / "add-slide", records)
    # At least one non-qualifying record by default, and unstamped, which is
    # what the real repository holds: every committed one predates run-identity
    # stamping. An EMPTY directory is refused, because git does not track one
    # and every derived count would read zero.
    default = {k: v for k, v in _record().items() if k != "started_at"}
    _write(directory.parent / "excluded", list(excluded) or [default])
    return directory


def _three() -> list[dict]:
    return [
        _record(run_id="a" * 32, started_at="2026-09-04T10:00:00.000+00:00"),
        _record(run_id="b" * 32, started_at="2026-09-04T10:05:00.000+00:00"),
        _record(run_id="c" * 32, started_at="2026-09-04T10:10:00.000+00:00"),
    ]


# --- the baseline, or every refusal below proves nothing -------------------


def test_three_clean_consecutive_records_render(tmp_path):
    code, output = _render(_campaign(tmp_path, _three()), tmp_path / "out.md")
    assert code == 0, output
    assert "3/3 passed" in (tmp_path / "out.md").read_text(encoding="utf-8")


def test_the_committed_evidence_matches_its_committed_records():
    """`--check` re-renders the real document from the real records. A stale
    committed document fails here rather than being silently believed."""

    document = REPO / "docs/evidence/add-slide-candidate-acceptance.md"
    records = sorted(ACCEPTED.glob("*.json")) if ACCEPTED.is_dir() else []
    if not records or not document.is_file():
        # No accepted campaign is committed right now. Attempt set 3 passed
        # every per-run gate but its records predate run-identity stamping,
        # so they cannot show three files were three consecutive runs; they
        # are preserved under `excluded/` and the document was withdrawn
        # rather than left un-derivable. A fresh campaign restores both.
        pytest.skip("no committed acceptance campaign to check")
    assert len(records) == 3, records
    code, output = _render(ACCEPTED, document, "--check")
    assert code == 0, output


# --- three files are not three runs ---------------------------------------


def test_one_record_copied_three_times_is_refused(tmp_path):
    """Found by an independent review. The renderer checked only that there
    were three files."""

    code, output = _render(_campaign(tmp_path, [_record()] * 3), tmp_path / "o.md")
    assert code == 2
    assert "identical" in output


def test_records_sharing_a_run_id_are_refused(tmp_path):
    """Defeating the byte-identical check by perturbing one field must not
    be enough: the identity is what says these were separate runs."""

    records = _three()
    records[2]["run_id"] = records[0]["run_id"]
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2
    assert "run_id" in output


@pytest.mark.parametrize("field", ["run_id", "started_at"])
def test_a_record_without_run_identity_is_refused(tmp_path, field):
    """Records predating the stamping cannot be rendered. That is the point:
    without them nothing establishes three files were three consecutive
    runs, and a gate that waved them through would be decorative."""

    records = _three()
    del records[1][field]
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2


def test_records_out_of_start_order_are_refused(tmp_path):
    records = _three()
    records[0]["started_at"] = "2026-09-04T23:00:00.000+00:00"
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2
    assert "strictly in order" in output


def test_records_starting_at_the_same_instant_are_refused(tmp_path):
    """Ordering that accepts ties is not ordering. Three ~4s runs cannot
    begin in the same millisecond on one machine, and a renderer that shrugs
    at it will shrug at three copies stamped by hand."""

    records = _three()
    for record in records:
        record["started_at"] = "2026-09-04T10:00:00.000+00:00"
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2
    assert "strictly in order" in output


def test_runs_that_overlap_in_time_are_refused(tmp_path):
    """A run cannot begin before the previous one finished. Start ordering
    alone allows three overlapping records, which no single operator could
    have produced."""

    records = _three()
    # run-2 starts one second after run-1 began, but run-1 lasted 3.5s.
    records[1]["started_at"] = "2026-09-04T10:00:01.000+00:00"
    records[2]["started_at"] = "2026-09-04T10:00:02.000+00:00"
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2
    assert "overlap" in output


def test_a_campaign_with_no_sibling_excluded_directory_is_refused(tmp_path):
    """Every derived count would read zero while the narrative still
    describes the recorded anomaly, so the document would contradict itself
    and silently drop a finding."""

    bare = _write(tmp_path / "bare" / "add-slide", _three())
    code, output = _render(bare, tmp_path / "o.md")
    assert code == 2
    assert "excluded" in output


def test_a_stray_file_or_subdirectory_in_the_campaign_is_refused(tmp_path):
    """`*.json` is not recursive, so a fourth record could sit in a
    subdirectory where the exactly-three count cannot see it."""

    campaign = _campaign(tmp_path, _three())
    (campaign / "extra").mkdir()
    code, output = _render(campaign, tmp_path / "o.md")
    assert code == 2
    assert "nothing else" in output

    campaign2 = _campaign(tmp_path / "b", _three())
    (campaign2 / "run-4.json.bak").write_text("{}", encoding="utf-8")
    code, output = _render(campaign2, tmp_path / "o2.md")
    assert code == 2


# --- consecutive means nothing rejected happened in between ---------------


def test_a_rejected_run_inside_the_window_is_refused(tmp_path):
    """The finding an independent review reproduced: three distinct,
    individually clean records drawn from already-rejected sets rendered a
    clean "3/3 passed". Excluded records are committed beside the accepted
    ones so this question can be asked of the repository."""

    accepted = _campaign(
        tmp_path,
        _three(),
        excluded=[_record(run_id="d" * 32, started_at="2026-09-04T10:07:00.000+00:00")],
    )
    code, output = _render(accepted, tmp_path / "o.md")
    assert code == 2
    assert "not consecutive" in output


def test_a_rejected_run_outside_the_window_does_not_refuse(tmp_path):
    """Earlier failed attempts are expected and are not disqualifying. Only
    one landing BETWEEN the accepted runs breaks the sequence -- otherwise
    the gate would refuse every candidate that ever needed a second try."""

    accepted = _campaign(
        tmp_path,
        _three(),
        excluded=[_record(run_id="d" * 32, started_at="2026-09-04T09:00:00.000+00:00")],
    )
    code, output = _render(accepted, tmp_path / "o.md")
    assert code == 0, output


# --- the per-record gates -------------------------------------------------


@pytest.mark.parametrize(
    "override, expected",
    [
        ({"outcome": "failed"}, "not passed"),
        ({"detail": "aborted"}, "detail"),
        ({"steps": {"completed": 0, "total": 1}}, "1/1"),
        ({"grounding_provenance": ["uia", "ocr"]}, "UIA-only"),
        ({"grounded_by_uia_only": False}, "UIA-only"),
        ({"record_kind": "preparation"}, "record_kind"),
        ({"is_acceptance_evidence": False}, "acceptance evidence"),
        ({"intent_id": "ADD_WORKSHEET"}, "intent"),
        ({"pack_id": "excel"}, "pack"),
    ],
)
def test_a_record_that_does_not_substantiate_the_claim_is_refused(
    tmp_path, override, expected
):
    records = _three()
    records[1].update(override)
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2
    assert expected in output


def test_runs_with_different_target_bindings_are_refused(tmp_path):
    """One captured HWND across the campaign, or the runs were not driving
    the same application window."""

    records = _three()
    records[2]["target"] = dict(records[2]["target"], target_ref="window-99887766")
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2
    assert "one target binding" in output


def test_a_record_naming_different_candidate_bytes_is_refused(tmp_path):
    records = _three()
    records[0]["digests"] = dict(records[0]["digests"], recipe="0" * 64)
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2
    assert "digests" in output


def test_a_record_from_another_application_build_is_refused(tmp_path):
    records = _three()
    records[0]["application_identity"] = {
        "kind": "executable_version",
        "value": "16.0.99999.1",
    }
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2
    assert "application identity" in output


def test_a_record_missing_the_timing_mark_is_refused(tmp_path):
    """Declared per workflow and enforced by exact set equality. ADD_SLIDE
    declares the mark present, and a set producing it in two runs and not the
    third was refused for that inconsistency."""

    records = _three()
    del records[2]["timing"]["verification_started_s"]
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2
    assert "landmarks are incomplete" in output


def test_unordered_timing_landmarks_are_refused(tmp_path):
    records = _three()
    records[0]["timing"]["verification_started_s"] = 0.1
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2
    assert "unordered" in output


@pytest.mark.parametrize("count", [2, 4])
def test_a_campaign_that_is_not_three_runs_is_refused(tmp_path, count):
    code, output = _render(
        _campaign(tmp_path, (_three() * 2)[:count]), tmp_path / "o.md"
    )
    assert code == 2


# --- the document is derived, not authored --------------------------------


def test_a_hand_edited_document_fails_check(tmp_path):
    records = _campaign(tmp_path, _three())
    out = tmp_path / "out.md"
    assert _render(records, out)[0] == 0
    out.write_text(
        out.read_text(encoding="utf-8").replace("3/3 passed", "4/4 passed"),
        encoding="utf-8",
        newline="",
    )
    code, output = _render(records, out, "--check")
    assert code == 2
    assert "differs from a fresh render" in output


def test_the_document_names_the_directory_it_actually_read(tmp_path):
    """The sentence discharging D034 was once a hardcoded path, so a document
    rendered from a scratch directory claimed a durable location."""

    records = _campaign(tmp_path, _three())
    out = tmp_path / "out.md"
    assert _render(records, out)[0] == 0
    document = out.read_text(encoding="utf-8")

    # It names the directory it read...
    assert "records/add-slide" in document
    # ...and NOT the durable committed location, which is what a hardcoded
    # string produced: a document rendered from a scratch directory that
    # claimed the records lived where evidence is kept.
    assert "acceptance-records/add-slide" not in document


def test_the_named_path_does_not_depend_on_how_it_was_invoked(tmp_path):
    """`--check` compares exact bytes, so a document whose text changed with
    a relative-versus-absolute argument would fail for a reason that has
    nothing to do with the evidence."""

    records = _campaign(tmp_path, _three())
    absolute = tmp_path / "abs.md"
    assert _render(records.resolve(), absolute)[0] == 0
    relative = tmp_path / "rel.md"
    import os

    here = Path.cwd()
    try:
        os.chdir(records.parent)
        assert _render(Path("add-slide"), relative)[0] == 0
    finally:
        os.chdir(here)
    assert absolute.read_text(encoding="utf-8") == relative.read_text(
        encoding="utf-8"
    )
# --- the candidate the document describes (D032 review, round 3) -----------
#
# `_check_recipe` and `_check_artifacts` had NO coverage. A reviewer disabled
# all eight of their checks one at a time and no test noticed. They exist so
# the document cannot describe a selector the signed recipe does not declare,
# and so its digest table is a statement about files rather than about JSON --
# "correct and unmutation-verified" is exactly what D018 forbids for a gate
# the document's factual claims rest on.


@pytest.fixture
def candidate(tmp_path):
    """A writable copy of the real candidate root, so a test can perturb one
    field without touching the tracked pack."""

    import shutil

    root = tmp_path / "candidate"
    shutil.copytree(CANDIDATE, root)
    return root


def _render_candidate(records: Path, root: Path, out: Path, renderer: Path = None):
    result = subprocess.run(
        [
            sys.executable,
            str(renderer or RENDERER),
            "--records",
            str(records),
            "--candidate-root",
            str(root),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode, (result.stderr or result.stdout)


RECIPE_DIGEST = "96ad179d9e4349b1846014c2592c113cf7f0ddd6f33c195fecef589cf23dcad1"


def _repin(root: Path, records: Path, out_dir: Path) -> Path:
    """Re-pin the perturbed recipe's digest EVERYWHERE a careless edit would:
    in every run record and in the renderer's own constant.

    Without both, the record-digest check fires first and `_check_recipe` is
    never reached -- which is how eight of its checks went uncovered while
    appearing tested. Returns the patched renderer to invoke.
    """

    import hashlib
    import json as _json

    digest = hashlib.sha256((root / "recipes/add_slide.json").read_bytes()).hexdigest()
    for path in records.glob("*.json"):
        record = _json.loads(path.read_text(encoding="utf-8"))
        record["digests"]["recipe"] = digest
        path.write_text(
            _json.dumps(record, indent=2, sort_keys=True), encoding="utf-8", newline=""
        )
    patched = out_dir / "renderer.py"
    patched.write_text(
        RENDERER.read_text(encoding="utf-8").replace(RECIPE_DIGEST, digest),
        encoding="utf-8",
        newline="",
    )
    return patched


def _edit_recipe(root: Path, mutate) -> None:
    path = root / "recipes/add_slide.json"
    recipe = json.loads(path.read_text(encoding="utf-8"))
    mutate(recipe)
    path.write_text(
        json.dumps(recipe, indent=2, sort_keys=True), encoding="utf-8", newline=""
    )


def test_the_real_candidate_renders(tmp_path, candidate):
    """Baseline. Without it every refusal below proves nothing."""

    records = _campaign(tmp_path, _three())
    code, output = _render_candidate(records, candidate, tmp_path / "o.md")
    assert code == 0, output


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (
            lambda r: r["steps"][0]["verification_rule"].__setitem__(
                "selector", "slide1_before"
            ),
            "verification selector",
        ),
        (
            lambda r: r["steps"][0]["verification_rule"].__setitem__(
                "kind", "window_title_matches"
            ),
            "verification kind",
        ),
        (
            lambda r: r["steps"][0].__setitem__("target_selector", "slide2_after"),
            "action selector",
        ),
        (
            lambda r: r["selectors"]["new_slide"].__setitem__(
                "cardinality", "at_least_one"
            ),
            "EXACTLY_ONE",
        ),
        (
            lambda r: r["selectors"]["new_slide"].__setitem__("strategy", "fuzzy"),
            "provider_exact",
        ),
        (
            lambda r: r["selectors"]["slide2_after"].__setitem__("names", ["Slide 2"]),
            "selector names",
        ),
        (
            lambda r: r["steps"].append(json.loads(json.dumps(r["steps"][0]))),
            "steps",
        ),
    ],
)
def test_a_recipe_that_does_not_declare_what_the_document_says_is_refused(
    tmp_path, candidate, mutate, expected
):
    """Each of these would make the rendered document describe a selector,
    cardinality or rule the signed recipe does not actually declare."""

    records = _campaign(tmp_path, _three())
    _edit_recipe(candidate, mutate)
    renderer = _repin(candidate, records, tmp_path)

    code, output = _render_candidate(
        records, candidate, tmp_path / "o.md", renderer=renderer
    )
    assert code == 2
    assert expected in output


def test_candidate_bytes_are_re_hashed_from_disk(tmp_path, candidate):
    """The document says "re-hashed from disk at render time". A record only
    CLAIMS what the harness was handed; re-hashing is what makes the digest
    table a statement about files."""

    records = _campaign(tmp_path, _three())
    path = candidate / "recipes/add_slide.json"
    path.write_bytes(path.read_bytes() + b"\n")

    code, output = _render_candidate(records, candidate, tmp_path / "o.md")
    assert code == 2
    assert "hash to" in output


def test_a_missing_candidate_artifact_is_refused(tmp_path, candidate):
    records = _campaign(tmp_path, _three())
    (candidate / "recipes/add_slide.json").unlink()

    code, output = _render_candidate(records, candidate, tmp_path / "o.md")
    assert code == 2
    assert "missing" in output


def test_check_against_a_document_that_does_not_exist_is_refused(tmp_path):
    records = _campaign(tmp_path, _three())
    code, output = _render(records, tmp_path / "absent.md", "--check")
    assert code == 2
    assert "does not exist" in output


def test_check_compares_bytes_not_text(tmp_path):
    """The document says `--check` compares exact bytes. `read_text` applies
    universal-newline translation, so a CRLF-converted document passed a
    check described as byte-exact."""

    records = _campaign(tmp_path, _three())
    out = tmp_path / "out.md"
    assert _render(records, out)[0] == 0
    out.write_bytes(out.read_bytes().replace(b"\n", b"\r\n"))

    code, output = _render(records, out, "--check")
    assert code == 2


def test_a_non_finite_timing_landmark_is_refused(tmp_path):
    """`json.loads` accepts NaN, and NaN compares false against everything,
    so it slid past the ordering check in every position but the first and
    rendered a table cell reading "nans"."""

    records = _campaign(tmp_path, _three())
    path = records / "run-2.json"
    path.write_text(
        path.read_text(encoding="utf-8").replace('"ended_s": 3.5', '"ended_s": NaN'),
        encoding="utf-8",
        newline="",
    )

    code, output = _render(records, tmp_path / "o.md")
    assert code == 2
    assert "finite" in output or "no duration" in output


def test_a_record_missing_started_at_in_the_first_position_is_refused(tmp_path):
    """The existing case deleted it from the MIDDLE record, so the ordering
    check fired first and the guard itself was never exercised -- the test
    passed for the wrong reason and the reviewer's mutation walked through
    it."""

    records = _three()
    del records[0]["started_at"]
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2
    assert "started_at" in output


def test_the_document_reports_that_the_window_check_saw_nothing(tmp_path):
    """When every committed non-qualifying run predates stamping, the check
    evaluates zero records. Reporting only its verdict would read as a check
    that passed."""

    records = _campaign(
        tmp_path,
        _three(),
        excluded=[{k: v for k, v in _record().items() if k != "started_at"}],
    )
    out = tmp_path / "o.md"
    assert _render(records, out)[0] == 0
    document = out.read_text(encoding="utf-8")
    assert "evaluated zero records" in document
    assert "established nothing" in document


def test_the_document_publishes_the_ids_and_instants(tmp_path):
    """A reader cannot audit consecutiveness from numbers the document
    withholds: records dated years apart rendered a document
    indistinguishable from a real campaign."""

    records = _three()
    out = tmp_path / "o.md"
    assert _render(_campaign(tmp_path, records), out)[0] == 0
    document = out.read_text(encoding="utf-8")
    from datetime import datetime

    for record in records:
        assert record["run_id"] in document
        # NORMALISED to UTC, because the column header says UTC and the
        # sequence checks compare instants rather than the raw text.
        assert datetime.fromisoformat(record["started_at"]).isoformat() in document


def test_records_spanning_years_are_refused(tmp_path):
    """A counted campaign is three supervised runs in one sitting. Records
    dated 2019, 2025 and 2031 are ordered and non-overlapping and passed
    every other check."""

    records = _three()
    for record, stamp in zip(
        records,
        [
            "2019-01-01T10:00:00.000+00:00",
            "2025-01-01T10:00:00.000+00:00",
            "2031-01-01T10:00:00.000+00:00",
        ],
    ):
        record["started_at"] = stamp
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2
    assert "one sitting" in output


def test_a_record_from_another_application_is_refused(tmp_path):
    """The target executable is what says these runs drove PowerPoint. A
    reviewer disabled the check and nothing noticed."""

    records = _three()
    for record in records:
        record["target"] = dict(record["target"], executable="excel.exe")
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2
    assert "executable" in output


@pytest.mark.parametrize("target_ref", [0, -1, None, "", 770201])
def test_a_record_without_a_usable_target_reference_is_refused(tmp_path, target_ref):
    """The reference is what the runs were bound to, pseudonymously (D128).
    An empty string, a number, or an absent field is not one, and the
    one-binding check would happily agree three records shared the same
    non-reference."""

    records = _three()
    for record in records:
        record["target"] = dict(record["target"], target_ref=target_ref)
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2
    assert "binding reference" in output


# --- instants, not strings (D032 review, round 4) --------------------------
#
# All three sequence checks compared raw `started_at` TEXT. A reviewer stamped
# one run `+05:30`, which sorts after a `+00:00` string naming a LATER moment,
# and defeated the ordering, the overlap check and the window check at once --
# then the document affirmatively printed that the window check had passed.


def test_a_timezone_offset_cannot_reorder_the_runs(tmp_path):
    """`13:00+05:30` is 07:30 UTC, five and a half hours BEFORE
    `10:00+00:00`, while sorting after it as text."""

    records = _three()
    records[1]["started_at"] = "2026-09-04T13:00:00.000+05:30"
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2
    assert "strictly in order" in output


def test_a_rejected_run_cannot_hide_behind_an_offset(tmp_path):
    """The worst version: a failed run squarely inside the accepted window,
    stamped in another timezone, slipped the window check -- and the document
    then claimed the check had evaluated it and found nothing."""

    accepted = _campaign(
        tmp_path,
        _three(),
        excluded=[
            _record(
                run_id="d" * 32,
                # 10:07 UTC, inside the 10:00-10:10 window, written as IST.
                started_at="2026-09-04T15:37:00.000+05:30",
                outcome="failed",
            )
        ],
    )
    code, output = _render(accepted, tmp_path / "o.md")
    assert code == 2
    assert "not consecutive" in output


@pytest.mark.parametrize(
    "stamp", ["2026-09-04T10:00:00.000", "2026-09-04", "not-a-time", ""]
)
def test_a_start_time_that_names_no_instant_is_refused(tmp_path, stamp):
    """An offset is required rather than assumed. Reading a naive stamp as
    UTC would be a guess about a number the document presents as measured --
    and a naive value previously raised an uncaught TypeError."""

    records = _three()
    records[0]["started_at"] = stamp
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2
    assert "instant" in output or "started_at" in output


def test_an_equivalent_offset_is_accepted(tmp_path):
    """Normalisation must not become strictness for its own sake: the same
    instant written in another timezone is the same instant."""

    records = _three()
    records[1]["started_at"] = "2026-09-04T15:35:00.000+05:30"  # 10:05 UTC
    out = tmp_path / "o.md"
    code, output = _render(_campaign(tmp_path, records), out)
    assert code == 0, output
    # ...and it is PRINTED normalised, because the column says UTC.
    assert "10:05:00+00:00" in out.read_text(encoding="utf-8")


# --- the excluded directory is guarded like the campaign directory ---------


def test_a_rejected_run_in_a_subdirectory_is_refused(tmp_path):
    """`glob("*.json")` is not recursive. A failed run in `excluded/archive/`
    was invisible to the window check while the counts stayed the same."""

    accepted = _campaign(tmp_path, _three())
    nested = accepted.parent / "excluded" / "archive"
    _write(nested, [_record(run_id="d" * 32)])
    code, output = _render(accepted, tmp_path / "o.md")
    assert code == 2
    assert "subdirector" in output


def test_an_empty_excluded_directory_is_refused(tmp_path):
    """Git does not track empty directories, so one means the non-qualifying
    records are absent -- and every derived count reads zero while the
    document still narrates the recorded anomaly."""

    accepted = _write(tmp_path / "records" / "add-slide", _three())
    (accepted.parent / "excluded").mkdir(parents=True)
    code, output = _render(accepted, tmp_path / "o.md")
    assert code == 2
    assert "no run records" in output


# --- a run duration that makes the overlap check meaningless ---------------


@pytest.mark.parametrize("ended", [-1.0, 2592000.0])
def test_an_implausible_run_duration_is_refused(tmp_path, ended):
    """An unbounded `ended_s` makes the overlap check vacuous in one
    direction and poisons the rendered drain figure in the other."""

    records = _three()
    records[0]["timing"]["ended_s"] = ended
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2


def test_the_document_prints_the_whole_run_id(tmp_path):
    """Truncating to eight characters was in tension with the document's own
    rationale for printing them at all."""

    records = _three()
    out = tmp_path / "o.md"
    assert _render(_campaign(tmp_path, records), out)[0] == 0
    document = out.read_text(encoding="utf-8")
    for record in records:
        assert record["run_id"] in document
