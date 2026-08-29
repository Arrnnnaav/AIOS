"""Task 12 evidence must be a projection of records, never an authored claim."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.render_open_extensions_evidence import (  # noqa: E402
    APPLICATION_IDENTITY,
    EXPECTED_DIGESTS,
    EvidenceRefused,
    check,
    load_records,
    main,
    render,
)


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_ROOT = ROOT / "docs/superpowers/candidates/declarative-workflow-compiler"
TARGET = {
    "hwnd": 4242,
    "title": "Welcome - AIOS - Visual Studio Code",
    "executable": "code.exe",
}
ARTIFACTS = {
    "pack": "vscode/pack/vscode.185cd7431e4f7e5e.json",
    "intent": "vscode/intents/open_extensions.f4c5f6a24ab49466.json",
    "recipe": "vscode/recipes/open_extensions.b749cca0ff2f1292.json",
}


def _record(run: int) -> dict:
    end = 5.0 + run
    return {
        "application_identity": dict(APPLICATION_IDENTITY),
        "detail": "",
        "digests": dict(EXPECTED_DIGESTS),
        "grounded_by_uia_only": True,
        "grounding_provenance": ["uia"],
        "intent_id": "OPEN_EXTENSIONS",
        "is_acceptance_evidence": True,
        "outcome": "passed",
        "pack_id": "vscode",
        "record_kind": "run",
        "steps": {"completed": 1, "total": 1},
        "target": dict(TARGET),
        "timing": {
            "first_observation_s": 0.25,
            "first_hint_s": 1.0,
            "verification_started_s": end - 0.5,
            "ended_s": end,
        },
    }


def _measurement() -> dict:
    return {
        "schema_version": 1,
        "application_identity": dict(APPLICATION_IDENTITY),
        "target": dict(TARGET),
        "artifacts": dict(ARTIFACTS),
        "source_url": (
            "https://code.visualstudio.com/docs/configure/extensions/extension-marketplace"
        ),
        "action_property_read": {
            "name": "Extensions (Ctrl+Shift+X)",
            "control_type": "TabItem",
            "automation_id": "",
            "runtime_id": [42, 1],
            "bbox": [10, 20, 30, 40],
        },
        "verification_property_read": {
            "name": "Installed Section",
            "control_type": "Button",
            "automation_id": "",
            "runtime_id": [42, 2],
            "bbox": [50, 60, 70, 80],
        },
        "setup_observations": [
            {
                "state": "extensions-unpinned",
                "action_raw_count": 0,
                "action_readable_count": 0,
                "bounded_tabitem_matches": 0,
                "note": "not exposed",
            },
            {
                "state": "restart-badge-present",
                "action_raw_count": 0,
                "action_readable_count": 0,
                "observed_name": "Extensions (Ctrl+Shift+X) - restart",
                "note": "exact name differed",
            },
            {
                "state": "first-read-after-restart",
                "action_raw_count": 0,
                "action_readable_count": 0,
                "verification_raw_count": 0,
                "verification_readable_count": 0,
                "note": "cold read",
            },
        ],
        "version_checks": [
            {"run": run, "phase": phase, "value": "1.135.0.0"}
            for run in (1, 2, 3)
            for phase in ("pre", "post")
        ],
        "provider_samples": [
            {
                "run": run,
                "phase": phase,
                "samples": 3,
                "action_raw": 1,
                "action_readable": 1,
                "verification_raw": 0 if phase == "pre" else 1,
                "verification_readable": 0 if phase == "pre" else 1,
            }
            for run in (1, 2, 3)
            for phase in ("pre", "post")
        ],
    }


def _write_records(directory: Path, records=None) -> Path:
    directory.mkdir()
    records = records or [_record(run) for run in (1, 2, 3)]
    for run, record in enumerate(records, 1):
        (directory / f"run{run}.json").write_bytes(
            json.dumps(record, indent=2).encode("utf-8")
        )
    return directory


def _loaded(tmp_path: Path):
    records = load_records(_write_records(tmp_path / "runs"))
    return records, _measurement()


def test_complete_campaign_renders_only_what_records_support(tmp_path) -> None:
    records, measurement = _loaded(tmp_path)
    check(records, measurement, CANDIDATE_ROOT)
    rendered = render(records, measurement)
    assert "3/3 passed" in rendered
    assert "| 1 | pre | 1/1 | 0/0 |" in rendered
    assert "| 1 | post | 1/1 | 1/1 |" in rendered
    assert "UIA-only" in rendered
    for digest in EXPECTED_DIGESTS.values():
        assert digest in rendered


@pytest.mark.parametrize("count", [2, 4])
def test_exactly_three_run_records_are_required(tmp_path, count) -> None:
    _write_records(tmp_path / "runs", [_record(run) for run in range(1, count + 1)])
    with pytest.raises(EvidenceRefused, match="exactly 3"):
        load_records(tmp_path / "runs")


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        ((0, "outcome"), "failed", "outcome"),
        ((0, "grounding_provenance"), ["ocr"], "UIA-only"),
        ((0, "digests", "recipe"), "f" * 64, "digests"),
        ((0, "application_identity", "value"), "1.136.0.0", "identity"),
    ],
)
def test_run_record_drift_is_refused(tmp_path, path, value, message) -> None:
    records, measurement = _loaded(tmp_path)
    target = records
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(EvidenceRefused, match=message):
        check(records, measurement, CANDIDATE_ROOT)


def test_version_drift_resets_the_campaign(tmp_path) -> None:
    records, measurement = _loaded(tmp_path)
    measurement["version_checks"][-1]["value"] = "1.136.0.0"
    with pytest.raises(EvidenceRefused, match="version drifted"):
        check(records, measurement, CANDIDATE_ROOT)


def test_every_pre_and_post_version_check_is_required(tmp_path) -> None:
    records, measurement = _loaded(tmp_path)
    measurement["version_checks"].pop()
    with pytest.raises(EvidenceRefused, match="pre/post"):
        check(records, measurement, CANDIDATE_ROOT)


@pytest.mark.parametrize(
    ("phase", "field", "value"),
    [
        ("pre", "action_readable", 0),
        ("pre", "verification_readable", 1),
        ("post", "verification_raw", 0),
    ],
)
def test_provider_state_cannot_be_rewritten(tmp_path, phase, field, value) -> None:
    records, measurement = _loaded(tmp_path)
    sample = next(item for item in measurement["provider_samples"] if item["phase"] == phase)
    sample[field] = value
    with pytest.raises(EvidenceRefused, match="provider counts differ"):
        check(records, measurement, CANDIDATE_ROOT)


def test_readiness_failures_cannot_be_dropped(tmp_path) -> None:
    records, measurement = _loaded(tmp_path)
    measurement["setup_observations"].pop()
    with pytest.raises(EvidenceRefused, match="readiness findings"):
        check(records, measurement, CANDIDATE_ROOT)


def test_readiness_counts_cannot_be_rewritten(tmp_path) -> None:
    records, measurement = _loaded(tmp_path)
    measurement["setup_observations"][0]["bounded_tabitem_matches"] = 1
    with pytest.raises(EvidenceRefused, match="unpinned"):
        check(records, measurement, CANDIDATE_ROOT)


def test_provider_measurement_must_name_the_same_target(tmp_path) -> None:
    records, measurement = _loaded(tmp_path)
    measurement["target"]["hwnd"] = 9999
    with pytest.raises(EvidenceRefused, match="target differs"):
        check(records, measurement, CANDIDATE_ROOT)


@pytest.mark.parametrize(
    ("role", "field", "value"),
    [
        ("action_property_read", "name", "Extensions"),
        ("action_property_read", "control_type", "Group"),
        ("verification_property_read", "name", "Installed"),
        ("verification_property_read", "control_type", "Text"),
    ],
)
def test_property_reads_must_match_the_recipe_selectors(
    tmp_path, role, field, value
) -> None:
    records, measurement = _loaded(tmp_path)
    measurement[role][field] = value
    with pytest.raises(EvidenceRefused, match="property read differs"):
        check(records, measurement, CANDIDATE_ROOT)


def test_three_runs_must_bind_one_hwnd(tmp_path) -> None:
    records, measurement = _loaded(tmp_path)
    records[-1]["target"]["hwnd"] = 9999
    with pytest.raises(EvidenceRefused, match="one captured HWND"):
        check(records, measurement, CANDIDATE_ROOT)


def test_timing_landmarks_must_stay_ordered(tmp_path) -> None:
    records, measurement = _loaded(tmp_path)
    records[0]["timing"]["verification_started_s"] = 0.5
    with pytest.raises(EvidenceRefused, match="timing landmarks"):
        check(records, measurement, CANDIDATE_ROOT)


def test_candidate_bytes_are_rehashed_not_taken_from_the_record(tmp_path) -> None:
    records, measurement = _loaded(tmp_path)
    copied = tmp_path / "candidate"
    for relative in ARTIFACTS.values():
        source = CANDIDATE_ROOT / relative
        destination = copied / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    recipe = copied / ARTIFACTS["recipe"]
    recipe.write_bytes(recipe.read_bytes() + b"\n")
    with pytest.raises(EvidenceRefused, match="candidate bytes hash"):
        check(records, measurement, copied)


def test_recipe_and_measurement_must_share_the_official_url(tmp_path) -> None:
    records, measurement = _loaded(tmp_path)
    measurement["source_url"] = "https://example.invalid"
    with pytest.raises(EvidenceRefused, match="provenance URL"):
        check(records, measurement, CANDIDATE_ROOT)


def test_noncanonical_measurement_is_refused(tmp_path) -> None:
    records = _write_records(tmp_path / "runs")
    measurement = tmp_path / "measurement.json"
    noncanonical = json.dumps(_measurement(), indent=2).replace("\n", "\r\n")
    measurement.write_bytes(noncanonical.encode("utf-8"))
    out = tmp_path / "evidence.md"
    assert (
        main(
            [
                "--records",
                str(records),
                "--measurement",
                str(measurement),
                "--candidate-root",
                str(CANDIDATE_ROOT),
                "--out",
                str(out),
            ]
        )
        == 2
    )
    assert not out.exists()


def test_check_refuses_a_hand_edited_document(tmp_path) -> None:
    records = _write_records(tmp_path / "runs")
    measurement = tmp_path / "measurement.json"
    measurement.write_bytes(json.dumps(_measurement(), indent=2).encode("utf-8"))
    out = tmp_path / "evidence.md"
    args = [
        "--records",
        str(records),
        "--measurement",
        str(measurement),
        "--candidate-root",
        str(CANDIDATE_ROOT),
        "--out",
        str(out),
    ]
    assert main(args) == 0
    assert main(args + ["--check"]) == 0
    out.write_bytes(out.read_bytes() + b"edited\n")
    assert main(args + ["--check"]) == 1


def test_fixture_helpers_do_not_share_mutable_state() -> None:
    first = _measurement()
    second = copy.deepcopy(_measurement())
    first["provider_samples"][0]["action_raw"] = 9
    assert second["provider_samples"][0]["action_raw"] == 1
