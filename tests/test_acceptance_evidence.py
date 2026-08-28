"""The acceptance evidence document is derived from run records, not authored.

D032 is the reason this tool exists at all: a hand-written evidence table is a
figure nothing else has read. The renderer's job is therefore mostly refusal --
every way a document could claim more than the records support is a case here,
and each one is mutation-verified by construction, because a refusal that never
fires would let the corresponding overstatement through silently.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.render_acceptance_evidence import (  # noqa: E402
    EvidenceRefused,
    check,
    group,
    load_records,
    main,
    render,
)

DIGESTS = {
    "pack": "a" * 64,
    "intent": "b" * 64,
    "recipe": "c" * 64,
}


#: `load_records()` stamps each record with the file it came from, so `check()`
#: and `render()` can name one. The factory does the same, rather than the
#: renderer tolerating its absence -- a tolerated absence would leave the real
#: path free to lose provenance and still render.
_SERIAL = iter(range(1, 1000))


def _record(
    intent_id: str,
    *,
    outcome: str = "passed",
    provenance=("uia",),
    digests=None,
    identity=("executable_version", "1.134.0"),
    steps=(1, 1),
    record_kind: str = "run",
    is_evidence: bool = True,
) -> dict:
    return {
        "record_kind": record_kind,
        "is_acceptance_evidence": is_evidence,
        "pack_id": "vscode",
        "intent_id": intent_id,
        "digests": dict(digests or DIGESTS),
        "application_identity": {"kind": identity[0], "value": identity[1]},
        "target": {
            "hwnd": 4242,
            "title": "Welcome - Visual Studio Code",
            "executable": "Code.exe",
        },
        "outcome": outcome,
        "grounding_provenance": list(provenance),
        "grounded_by_uia_only": bool(provenance) and set(provenance) == {"uia"},
        "steps": {"completed": steps[0], "total": steps[1]},
        "detail": "",
        "_source": f"{intent_id.lower()}-run{next(_SERIAL)}.json",
    }


def _write(directory: Path, records) -> Path:
    for record in records:
        payload = {k: v for k, v in record.items() if k != "_source"}
        (directory / record["_source"]).write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
    return directory


def _complete():
    return (
        [_record("EXPORT_DATA") for _ in range(3)]
        + [_record("OPEN_FOLDER") for _ in range(3)]
        + [_record("OPEN_TERMINAL") for _ in range(3)]
    )


# ---------------------------------------------------------------------------
# What a record must be before it counts
# ---------------------------------------------------------------------------


def test_a_preparation_record_is_not_acceptance_evidence(tmp_path) -> None:
    """It says so in its own payload; the renderer takes it at its word.

    `--prepare-only` binds a candidate without running it. Counting one would
    turn "the artifacts load" into "the workflow works".
    """
    _write(tmp_path, [_record("OPEN_FOLDER", record_kind="preparation")])
    with pytest.raises(EvidenceRefused, match="record_kind"):
        load_records(tmp_path)


def test_a_record_denying_it_is_evidence_is_refused(tmp_path) -> None:
    _write(tmp_path, [_record("OPEN_FOLDER", is_evidence=False)])
    with pytest.raises(EvidenceRefused, match="not marked as acceptance evidence"):
        load_records(tmp_path)


def test_an_empty_directory_renders_nothing(tmp_path) -> None:
    """Zero records is a refusal, never an empty document that looks complete."""
    with pytest.raises(EvidenceRefused, match="no run records"):
        load_records(tmp_path)


def test_unreadable_json_is_refused_rather_than_skipped(tmp_path) -> None:
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(EvidenceRefused, match="not valid JSON"):
        load_records(tmp_path)


# ---------------------------------------------------------------------------
# What the acceptance policy requires
# ---------------------------------------------------------------------------


def test_a_missing_workflow_is_refused(tmp_path) -> None:
    records = [r for r in _complete() if r["intent_id"] != "OPEN_TERMINAL"]
    with pytest.raises(EvidenceRefused, match="OPEN_TERMINAL"):
        check(group(records))


def test_two_passing_runs_are_not_three(tmp_path) -> None:
    records = _complete()
    folder = [r for r in records if r["intent_id"] == "OPEN_FOLDER"]
    folder[0]["outcome"] = "timed_out"
    with pytest.raises(EvidenceRefused, match="2 passing of 3"):
        check(group(records))


def test_a_failure_cannot_be_diluted_by_extra_runs(tmp_path) -> None:
    """3/3 means three passes, not three passes among however many attempts.

    Retrying until three succeed and reporting 3/3 is the shape this refuses:
    the failure is preserved in the count, so the document cannot be made to
    look clean by running more.
    """
    records = _complete()
    records.append(_record("OPEN_FOLDER", outcome="failed"))
    check(group(records))  # three still passed, so the gate is met...
    rendered = render(group(records))
    assert "failed" in rendered, "the failed attempt vanished from the document"
    assert rendered.count("| passed ") == 9


def test_runs_against_different_bytes_do_not_add_up(tmp_path) -> None:
    """One intent, one set of artifacts. Otherwise 3/3 spans three recipes."""
    records = _complete()
    folder = [r for r in records if r["intent_id"] == "OPEN_FOLDER"]
    folder[0]["digests"] = dict(DIGESTS, recipe="d" * 64)
    with pytest.raises(EvidenceRefused, match="2 digest sets"):
        check(group(records))


def test_runs_against_different_application_versions_do_not_add_up(tmp_path) -> None:
    records = _complete()
    folder = [r for r in records if r["intent_id"] == "OPEN_FOLDER"]
    folder[0]["application_identity"] = {
        "kind": "executable_version",
        "value": "1.133.0",
    }
    with pytest.raises(EvidenceRefused, match="2 application identities"):
        check(group(records))


def test_open_folder_passing_on_ocr_is_refused(tmp_path) -> None:
    """The gate asserts provenance, not completion (D069).

    Fallback OCR preserves the outcome while UIA is dark, so a passing run
    grounded by OCR is exactly the silent degradation this gate exists to
    catch -- and an outcome-only check would call it a success.
    """
    records = _complete()
    folder = [r for r in records if r["intent_id"] == "OPEN_FOLDER"]
    folder[0]["grounding_provenance"] = ["ocr"]
    folder[0]["grounded_by_uia_only"] = False
    with pytest.raises(EvidenceRefused, match="non-UIA grounding"):
        check(group(records))


def test_a_mixed_uia_and_ocr_open_folder_run_is_refused(tmp_path) -> None:
    """One OCR-grounded step is enough: the tier went dark for that step."""
    records = _complete()
    folder = [r for r in records if r["intent_id"] == "OPEN_FOLDER"]
    folder[0]["grounding_provenance"] = ["uia", "ocr"]
    folder[0]["grounded_by_uia_only"] = False
    with pytest.raises(EvidenceRefused, match="non-UIA grounding"):
        check(group(records))


def test_an_intent_nobody_asked_for_is_refused(tmp_path) -> None:
    """Task 8 accepts three workflows. A fourth record means a stale directory."""
    records = _complete() + [_record("OPEN_EXTENSIONS")]
    with pytest.raises(EvidenceRefused, match="OPEN_EXTENSIONS"):
        check(group(records))


# ---------------------------------------------------------------------------
# What the document says
# ---------------------------------------------------------------------------


def test_the_document_names_every_tested_digest_in_full(tmp_path) -> None:
    """A path names a mutable file; only the digest names the bytes reviewed."""
    rendered = render(group(_complete()))
    for digest in DIGESTS.values():
        assert digest in rendered
    assert "quarantined" in rendered


def test_a_failures_own_reason_reaches_the_document(tmp_path) -> None:
    """"Failed" without the reason makes the reader go back to the raw records.

    The reason comes from the record, so it stays derived rather than
    described: nobody gets to explain a failure into something milder.
    """
    records = _complete()
    records.append(
        _record("OPEN_TERMINAL", outcome="failed", steps=(0, 1))
        | {"detail": "verification timed out after 20s"}
    )
    rendered = render(group(records))
    assert "verification timed out after 20s" in rendered
    # A clean run has no reason to give, and an empty cell breaks the table.
    assert "| -- |" in rendered


def test_the_document_records_the_application_identity(tmp_path) -> None:
    rendered = render(group(_complete()))
    assert "executable_version" in rendered
    assert "1.134.0" in rendered


def test_check_refuses_a_document_that_was_edited_by_hand(tmp_path) -> None:
    """The whole point: an authored table is a figure nothing else has read."""
    records = _write(tmp_path, _complete())
    out = tmp_path / "evidence.md"
    assert main(["--records", str(records), "--out", str(out)]) == 0
    assert main(["--records", str(records), "--out", str(out), "--check"]) == 0

    out.write_text(
        out.read_text(encoding="utf-8").replace("timed_out", "passed") + "\nall good\n",
        encoding="utf-8",
    )
    assert main(["--records", str(records), "--out", str(out), "--check"]) == 1


def test_check_refuses_before_it_ever_compares(tmp_path) -> None:
    """A refused record set never reaches the document comparison at all.

    Otherwise a stale-but-matching document would report success over records
    that do not support it.
    """
    records = _complete()
    records[0]["outcome"] = "failed"
    directory = _write(tmp_path, records)
    out = tmp_path / "evidence.md"
    out.write_text("anything", encoding="utf-8")
    assert main(["--records", str(directory), "--out", str(out), "--check"]) == 2


def test_a_missing_document_fails_check_rather_than_being_created(tmp_path) -> None:
    directory = _write(tmp_path, _complete())
    out = tmp_path / "absent.md"
    assert main(["--records", str(directory), "--out", str(out), "--check"]) == 1
    assert not out.exists()
