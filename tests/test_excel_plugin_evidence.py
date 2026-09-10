"""Excel activation evidence is a projection of exact harness records."""

from __future__ import annotations

import copy
from pathlib import Path
import shutil

import pytest

from tools.render_excel_plugin_evidence import (
    EvidenceRefused,
    WORKFLOWS,
    check,
    load_records,
    main,
    render,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "plugins" / "sources" / "excel"
RECORDS = SOURCE / "acceptance-records"
CANDIDATE = SOURCE / "payload" / "ghostcursor" / "packs" / "excel"
EVIDENCE = SOURCE / "payload" / "docs" / "evidence" / "excel-plugin-acceptance.md"


def _loaded():
    campaigns, excluded = load_records(RECORDS)
    return copy.deepcopy(campaigns), copy.deepcopy(excluded)


def test_exact_campaign_renders_two_three_of_three_uia_only_proofs() -> None:
    campaigns, excluded = _loaded()
    check(campaigns, excluded, CANDIDATE)
    rendered = render(campaigns, excluded)
    assert rendered.count("**3/3 passed**") == 2
    assert "`SELECT_CELL_B2`" in rendered
    assert "`ADD_WORKSHEET`" in rendered
    assert "UIA-only" in rendered
    assert "Two earlier worksheet attempts are retained" in rendered


@pytest.mark.parametrize("intent_id", sorted(WORKFLOWS))
def test_a_failed_counted_run_is_refused(intent_id) -> None:
    campaigns, excluded = _loaded()
    campaigns[intent_id][0]["outcome"] = "failed"
    with pytest.raises(EvidenceRefused, match="outcome"):
        check(campaigns, excluded, CANDIDATE)


@pytest.mark.parametrize("intent_id", sorted(WORKFLOWS))
def test_non_uia_grounding_is_refused(intent_id) -> None:
    campaigns, excluded = _loaded()
    campaigns[intent_id][1]["grounding_provenance"] = ["ocr"]
    with pytest.raises(EvidenceRefused, match="UIA-only"):
        check(campaigns, excluded, CANDIDATE)


def test_application_version_drift_is_refused() -> None:
    campaigns, excluded = _loaded()
    campaigns["SELECT_CELL_B2"][2]["application_identity"]["value"] = "16.1"
    with pytest.raises(EvidenceRefused, match="application identity"):
        check(campaigns, excluded, CANDIDATE)


def test_record_digest_drift_is_refused() -> None:
    campaigns, excluded = _loaded()
    campaigns["ADD_WORKSHEET"][0]["digests"]["recipe"] = "f" * 64
    with pytest.raises(EvidenceRefused, match="artifact digests"):
        check(campaigns, excluded, CANDIDATE)


def test_timing_landmarks_must_be_complete_and_ordered() -> None:
    campaigns, excluded = _loaded()
    campaigns["ADD_WORKSHEET"][0]["timing"]["verification_started_s"] = 0.1
    with pytest.raises(EvidenceRefused, match="unordered"):
        check(campaigns, excluded, CANDIDATE)


def test_cell_campaign_must_remain_on_one_target_binding() -> None:
    campaigns, excluded = _loaded()
    campaigns["SELECT_CELL_B2"][2]["target"]["target_ref"] = "window-Z"
    with pytest.raises(EvidenceRefused, match="one redacted target binding"):
        check(campaigns, excluded, CANDIDATE)


def test_a_non_string_target_reference_is_refused() -> None:
    """The only negative case used to be `""`, which the truthiness check
    caught, so dropping the isinstance check survived the whole suite. A raw
    integer handle in `target_ref` is exactly what that check exists to
    refuse (D129)."""

    campaigns, excluded = _loaded()
    campaigns["ADD_WORKSHEET"][2]["target"]["target_ref"] = 770301
    with pytest.raises(EvidenceRefused, match="target differs"):
        check(campaigns, excluded, CANDIDATE)


def test_a_missing_campaign_scope_is_refused() -> None:
    campaigns, excluded = _loaded()
    del campaigns["ADD_WORKSHEET"][2]["target"]["target_scope"]
    with pytest.raises(EvidenceRefused, match="target differs"):
        check(campaigns, excluded, CANDIDATE)


def test_each_record_requires_a_usable_target_reference() -> None:
    campaigns, excluded = _loaded()
    campaigns["ADD_WORKSHEET"][2]["target"]["target_ref"] = ""
    with pytest.raises(EvidenceRefused, match="target differs"):
        check(campaigns, excluded, CANDIDATE)


def test_both_excluded_attempts_are_required_and_never_counted() -> None:
    campaigns, excluded = _loaded()
    excluded.pop()
    with pytest.raises(EvidenceRefused, match="exactly two excluded"):
        check(campaigns, excluded, CANDIDATE)


def test_an_excluded_attempt_cannot_be_rewritten_as_a_pass() -> None:
    campaigns, excluded = _loaded()
    excluded[0]["outcome"] = "passed"
    with pytest.raises(EvidenceRefused, match="outcome"):
        check(campaigns, excluded, CANDIDATE)


def test_candidate_bytes_are_rehashed_not_trusted_from_records(tmp_path) -> None:
    campaigns, excluded = _loaded()
    copied = tmp_path / "candidate"
    shutil.copytree(CANDIDATE, copied)
    recipe = copied / WORKFLOWS["ADD_WORKSHEET"]["recipe_path"]
    recipe.write_bytes(recipe.read_bytes() + b"\n")
    with pytest.raises(EvidenceRefused, match="candidate bytes hash"):
        check(campaigns, excluded, copied)


def test_record_inventory_rejects_hidden_extra_or_missing_runs(tmp_path) -> None:
    copied = tmp_path / "records"
    shutil.copytree(RECORDS, copied)
    (copied / "extra.json").write_text("{}", encoding="utf-8")
    with pytest.raises(EvidenceRefused, match="record inventory differs"):
        load_records(copied)


def test_renderer_check_refuses_a_hand_edited_document(tmp_path) -> None:
    out = tmp_path / "evidence.md"
    args = [
        "--records",
        str(RECORDS),
        "--candidate-root",
        str(CANDIDATE),
        "--out",
        str(out),
    ]
    assert main(args) == 0
    assert main(args + ["--check"]) == 0
    out.write_bytes(out.read_bytes() + b"edited\n")
    assert main(args + ["--check"]) == 1


def test_committed_evidence_matches_the_exact_records() -> None:
    assert (
        main(
            [
                "--records",
                str(RECORDS),
                "--candidate-root",
                str(CANDIDATE),
                "--out",
                str(EVIDENCE),
                "--check",
            ]
        )
        == 0
    )
