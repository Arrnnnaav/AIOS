from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import render_confirmation_budget as renderer


def _record(*, round_trip=640.0, write=16.0, failure=None):
    return {
        "application_version": "16.0.20326.20132",
        "failure": failure,
        "is_acceptance_evidence": False,
        "operation": "powerpoint.new_slide_uia",
        "record_kind": "confirmation_budget_diagnostic",
        "sample_timeout_s": 60,
        "samples_completed": 60,
        "samples_requested": 60,
        "schema_version": 1,
        "selector_sha256": "a" * 64,
        "target_ref": "window-test",
        "target_scope": "scope-test",
        "visual_budget": {"frame_budget_ms": 2, "settle_ms": 250, "traversal_ms": 300},
        "samples": [
            {
                "confirmation_round_trip_ms": round_trip,
                "confirmation_to_request_write_ms": write,
            }
            for _ in range(60)
        ],
    }


def _write(path: Path, record: dict) -> None:
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def test_derivation_requires_three_complete_raw_records(tmp_path):
    paths = []
    for index in range(3):
        path = tmp_path / f"run-{index}.json"
        _write(path, _record())
        paths.append(path)

    report = renderer.derive(paths)

    assert report["confirmation_round_trip_ms"]["samples"] == 180
    assert report["confirmation_round_trip_ms"]["p99_ms"] == 640.0
    assert report["confirmation_round_trip_ms"]["derived_deadline_ms"] == 1280
    assert report["confirmation_to_request_write_ms"]["derived_deadline_ms"] == 32


def test_derivation_uses_worst_run_p99_and_max(tmp_path):
    paths = []
    values = ([100.0] * 59 + [500.0], [100.0] * 59 + [640.0], [100.0] * 59 + [620.0])
    for index, run_values in enumerate(values):
        record = _record()
        record["samples"] = [
            {"confirmation_round_trip_ms": value, "confirmation_to_request_write_ms": 16.0}
            for value in run_values
        ]
        path = tmp_path / f"run-{index}.json"
        _write(path, record)
        paths.append(path)

    report = renderer.derive(paths)

    assert report["confirmation_round_trip_ms"]["p99_ms"] == 640.0
    assert report["confirmation_round_trip_ms"]["max_ms"] == 640.0
    assert report["confirmation_round_trip_ms"]["derived_deadline_ms"] == 1280


def test_each_derived_deadline_depends_on_raw_samples(tmp_path):
    paths = []
    for index in range(3):
        path = tmp_path / f"run-{index}.json"
        _write(path, _record())
        paths.append(path)
    before = renderer.derive(paths)
    changed = _record(write=17.0)
    _write(paths[0], changed)

    after = renderer.derive(paths)

    assert before["confirmation_to_request_write_ms"]["derived_deadline_ms"] == 32
    assert after["confirmation_to_request_write_ms"]["derived_deadline_ms"] == 34


def test_raw_record_change_changes_derived_result(tmp_path):
    paths = []
    for index in range(3):
        path = tmp_path / f"run-{index}.json"
        _write(path, _record())
        paths.append(path)
    before = renderer.derive(paths)

    changed = _record(round_trip=701.0)
    _write(paths[2], changed)
    after = renderer.derive(paths)

    assert before["record_digests"][2] != after["record_digests"][2]
    assert after["confirmation_round_trip_ms"]["derived_deadline_ms"] == 1402


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record: record.update(failure={"failure_class": "NodeRefused"}),
        lambda record: record.update(samples_completed=59),
        lambda record: record["samples"].pop(),
        lambda record: record["samples"][0].update(confirmation_round_trip_ms=True),
    ],
)
def test_incomplete_or_untrustworthy_records_are_refused(tmp_path, mutate):
    paths = []
    for index in range(3):
        record = _record()
        if index == 1:
            mutate(record)
        path = tmp_path / f"run-{index}.json"
        _write(path, record)
        paths.append(path)

    with pytest.raises(renderer.EvidenceRefused):
        renderer.derive(paths)


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf"), "16"])
def test_non_finite_negative_and_string_timings_are_refused(tmp_path, bad):
    paths = []
    for index in range(3):
        record = _record()
        if index == 0:
            record["samples"][0]["confirmation_to_request_write_ms"] = bad
        path = tmp_path / f"run-{index}.json"
        _write(path, record)
        paths.append(path)

    with pytest.raises(renderer.EvidenceRefused):
        renderer.derive(paths)


def test_render_and_check_are_reproducible(tmp_path):
    paths = []
    for index in range(3):
        path = tmp_path / f"run-{index}.json"
        _write(path, _record())
        paths.append(path)
    report = renderer.derive(paths)
    output = tmp_path / "budget.md"
    output.write_text(renderer.render(report), encoding="utf-8", newline="\n")

    assert renderer.main([
        "--records", *(str(path) for path in paths),
        "--out", str(output), "--check",
    ]) == 0
    output.write_text(output.read_text(encoding="utf-8") + "drift\n", encoding="utf-8", newline="\n")
    with pytest.raises(SystemExit, match="stale"):
        renderer.main([
            "--records", *(str(path) for path in paths),
            "--out", str(output), "--check",
        ])
