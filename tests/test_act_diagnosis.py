"""Each competing explanation for a failed node must be separable from the others.

A classifier that collapses two causes into one label is worse than no
classifier: it ends the investigation at the wrong place.
"""

from __future__ import annotations

import json

import pytest

from ghostcursor.devtools.act_diagnosis import (
    classify_boundary,
    read_records,
    summarise,
)


def _state(**overrides):
    state = {
        "exists": True,
        "fault": None,
        "mtime_ns": 1,
        "part_count": 2,
        "readable_zip": True,
        "sha256": "a" * 64,
        "size": 100,
        "reads_agreed": True,
    }
    state.update(overrides)
    return state


def _record(**overrides):
    record = {
        "adapter_added_parts": [],
        "adapter_removed_parts": [],
        "adapter_wrote_parts": ["ppt/slides/slide5.xml"],
        "after_adapter": _state(),
        "after_verify": _state(),
        "before_node": _state(sha256="b" * 64),
        "node_id": "n025",
        "operation_id": "powerpoint.set_transition",
        "type": "node_boundary",
        "verified": False,
        "verifier_error": None,
        "verifier_seconds": 1.5,
        "package_changed_during_verification": False,
    }
    record.update(overrides)
    return record


def test_a_verified_node_is_not_diagnosed_as_anything_else():
    assert classify_boundary(_record(verified=True)).classification == "verified"


def test_a_save_that_changed_nothing_is_never_written():
    finding = classify_boundary(_record(adapter_wrote_parts=[]))

    assert finding.classification == "never_written"
    assert finding.node_id == "n025"


def test_a_save_that_added_a_part_is_not_never_written():
    """Added parts count as written. A new slide's XML did not exist before."""

    finding = classify_boundary(
        _record(adapter_wrote_parts=[], adapter_added_parts=["ppt/slides/slide9.xml"])
    )

    assert finding.classification != "never_written"


def test_a_save_that_touched_the_wrong_part_is_distinguished_from_never_written():
    finding = classify_boundary(
        _record(adapter_wrote_parts=["docProps/app.xml"]),
        expected_parts=("ppt/slides/slide5.xml",),
    )

    assert finding.classification == "wrong_part"
    assert "docProps/app.xml" in finding.detail


def test_wrong_part_is_never_claimed_without_a_declared_expectation():
    """No expectation supplied means the distinction is unavailable, not that
    the part was correct."""

    finding = classify_boundary(_record(adapter_wrote_parts=["docProps/app.xml"]))

    assert finding.classification == "written_and_verified_false"


def test_a_package_whose_reads_disagree_is_not_reported_as_never_written():
    finding = classify_boundary(_record(after_adapter=_state(reads_agreed=False)))

    assert finding.classification == "bytes_moved_during_read"


def test_a_package_that_will_not_open_is_unreadable():
    finding = classify_boundary(_record(after_adapter=_state(readable_zip=False)))

    assert finding.classification == "unreadable"


def test_a_missing_package_after_the_save_is_never_written():
    finding = classify_boundary(_record(after_adapter=_state(exists=False)))

    assert finding.classification == "never_written"


def test_a_package_change_during_verification_outranks_every_explanation():
    """It invalidates the digests rather than explaining the failure, so it
    must win even when another signal is also present. It still names no
    culprit: an external writer is indistinguishable from here."""

    finding = classify_boundary(
        _record(package_changed_during_verification=True, adapter_wrote_parts=[])
    )

    assert finding.classification == "package_changed_during_verification"


def test_a_verifier_exception_is_reported_as_itself():
    finding = classify_boundary(
        _record(verifier_error="Timeout: verifier never replied")
    )

    assert finding.classification == "verifier_error"
    assert "never replied" in finding.detail


def test_a_clean_write_that_still_failed_points_at_the_verifier_not_the_boundary():
    finding = classify_boundary(_record(), expected_parts=("ppt/slides/slide5.xml",))

    assert finding.classification == "written_and_verified_false"


def test_a_node_with_no_pre_observation_is_unclassified_rather_than_guessed():
    finding = classify_boundary(_record(before_node=None, adapter_wrote_parts=[]))

    assert finding.classification == "unclassified"


def test_the_summary_reports_the_first_failure_not_an_arbitrary_one():
    records = [
        _record(node_id="n001", verified=True),
        _record(node_id="n025", adapter_wrote_parts=[]),
        _record(node_id="n099", after_adapter=_state(reads_agreed=False)),
    ]

    summary = summarise(records)

    assert summary["nodes_recorded"] == 3
    assert summary["first_failure"].node_id == "n025"
    assert summary["classifications"] == {
        "never_written": 1,
        "bytes_moved_during_read": 1,
        "verified": 1,
    }
    assert summary["verifier_seconds_max"] == 1.5


def test_records_of_other_types_are_ignored_by_the_summary():
    summary = summarise(
        [{"type": "diagnostic_run_started"}, {"type": "probe_fault"}, _record()]
    )

    assert summary["nodes_recorded"] == 1


def test_a_malformed_line_is_surfaced_rather_than_silently_dropped(tmp_path):
    path = tmp_path / "diagnostics.jsonl"
    path.write_text(
        json.dumps(_record()) + "\n{ not json\n" + json.dumps(_record()) + "\n",
        encoding="utf-8",
    )

    records = read_records(path)

    assert len(records) == 3
    assert records[1]["type"] == "malformed_line"
    assert records[1]["line"] == 2


def test_the_classifier_reads_the_record_the_probe_actually_writes(tmp_path):
    """Binds the two modules together.

    Every field name here is a contract between ActBoundaryProbe and this
    classifier. Nothing else notices if one of them is renamed, and the
    failure mode is a silent 'unclassified' on every node.
    """

    import zipfile

    from ghostcursor.devtools.act_probe import ActBoundaryProbe

    output = tmp_path / "deck.pptx"

    def package(payload: bytes) -> None:
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("ppt/slides/slide5.xml", payload)

    records: list[dict] = []
    probe = ActBoundaryProbe(output, records.append)
    package(b"<sld/>")

    from types import SimpleNamespace

    node = SimpleNamespace(node_id="n025", operation_id="powerpoint.set_transition")
    probe.event_sink()(SimpleNamespace(type="action_started", node_id="n025"))
    package(b"<sld transition=/>")
    observer = probe.verify_observer()
    observer("verify_started", {"node_id": "n025"})
    observer(
        "verify_finished",
        {
            "error": None,
            "node_id": node.node_id,
            "operation_id": node.operation_id,
            "seconds": 1.0,
            "verified": False,
        },
    )

    finding = classify_boundary(records[0], expected_parts=("ppt/slides/slide5.xml",))

    assert finding.node_id == "n025"
    assert finding.operation_id == "powerpoint.set_transition"
    assert finding.verified is False
    assert finding.classification == "written_and_verified_false"
    assert finding.adapter_wrote_parts == ("ppt/slides/slide5.xml",)


def test_a_probe_record_whose_save_changed_nothing_classifies_as_never_written(
    tmp_path,
):
    """The same binding, on the branch that matters most for action 25."""

    import zipfile
    from types import SimpleNamespace

    from ghostcursor.devtools.act_probe import ActBoundaryProbe

    output = tmp_path / "deck.pptx"
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("ppt/slides/slide5.xml", b"<sld/>")

    records: list[dict] = []
    probe = ActBoundaryProbe(output, records.append)
    probe.event_sink()(SimpleNamespace(type="action_started", node_id="n025"))
    # No write between the node starting and verification: the effect never
    # reached the package.
    observer = probe.verify_observer()
    observer("verify_started", {"node_id": "n025"})
    observer(
        "verify_finished",
        {
            "error": None,
            "node_id": "n025",
            "operation_id": "powerpoint.set_transition",
            "seconds": 1.0,
            "verified": False,
        },
    )

    assert classify_boundary(records[0]).classification == "never_written"


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"adapter_wrote_parts": []}, "never_written"),
        ({"after_adapter": _state(reads_agreed=False)}, "bytes_moved_during_read"),
        ({"after_adapter": _state(readable_zip=False)}, "unreadable"),
        ({"package_changed_during_verification": True}, "package_changed_during_verification"),
    ],
)
def test_every_failure_class_is_reachable(overrides, expected):
    """Non-vacuity: a classifier whose branches cannot all fire is a table of
    labels, not a diagnosis."""

    assert classify_boundary(_record(**overrides)).classification == expected


def test_a_record_with_no_verification_result_is_not_counted_as_a_pass():
    """It failed toward success: `verified is not False` let a missing or null
    result be reported as a verified node and excluded from the failures."""

    record = _record()
    del record["verified"]

    assert classify_boundary(record).classification == "unclassified"


def test_a_null_verification_result_without_an_error_is_unclassified():
    assert (
        classify_boundary(_record(verified=None, verifier_error=None)).classification
        == "unclassified"
    )


def test_an_unclassified_node_is_reported_as_a_failure_by_the_summary():
    """Otherwise the summary silently drops the node it could not explain."""

    summary = summarise([_record(node_id="n001", verified=True), _record(verified=None)])

    assert summary["first_failure"] is not None
    assert summary["first_failure"].classification == "unclassified"
