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
            "hwnd": 1050680,
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


def _campaign(tmp_path: Path, records: list[dict]) -> Path:
    return _write(tmp_path / "records" / "add-slide", records)


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
    assert "start order" in output


# --- consecutive means nothing rejected happened in between ---------------


def test_a_rejected_run_inside_the_window_is_refused(tmp_path):
    """The finding an independent review reproduced: three distinct,
    individually clean records drawn from already-rejected sets rendered a
    clean "3/3 passed". Excluded records are committed beside the accepted
    ones so this question can be asked of the repository."""

    accepted = _campaign(tmp_path, _three())
    _write(
        accepted.parent / "excluded",
        [_record(run_id="d" * 32, started_at="2026-09-04T10:07:00.000+00:00")],
    )
    code, output = _render(accepted, tmp_path / "o.md")
    assert code == 2
    assert "not consecutive" in output


def test_a_rejected_run_outside_the_window_does_not_refuse(tmp_path):
    """Earlier failed attempts are expected and are not disqualifying. Only
    one landing BETWEEN the accepted runs breaks the sequence -- otherwise
    the gate would refuse every candidate that ever needed a second try."""

    accepted = _campaign(tmp_path, _three())
    _write(
        accepted.parent / "excluded",
        [_record(run_id="d" * 32, started_at="2026-09-04T09:00:00.000+00:00")],
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


def test_runs_bound_to_different_windows_are_refused(tmp_path):
    """One captured HWND across the campaign, or the runs were not driving
    the same application window."""

    records = _three()
    records[2]["target"] = dict(records[2]["target"], hwnd=999999)
    code, output = _render(_campaign(tmp_path, records), tmp_path / "o.md")
    assert code == 2
    assert "HWND" in output


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
