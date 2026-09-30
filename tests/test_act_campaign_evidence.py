"""A counted campaign's evidence is checked, not written up (D150).

The D149 review found that a campaign run on the rebuilt bundle would have
produced a report that kept no records, named no manifest or commit, and was
checked by nothing -- the write-up would have been prose again (D137). These
tests hold the checker to every refusal it claims, against synthetic
campaigns and against the real retained 11 September manager transcripts.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import render_act_campaign as checker  # noqa: E402

from ghostcursor.devtools import act_manager_campaign as manager_campaign  # noqa: E402
from ghostcursor.devtools.act_campaign import (  # noqa: E402
    Attempt,
    CampaignError,
    campaign_report,
    retained_records,
)
from ghostcursor.devtools.campaign_pins import (  # noqa: E402
    POWERPOINT_MANIFEST_SHA256 as PIN,
    CampaignPreflightError,
    require_pinned_manifest,
)

COMMIT = "c" * 40
PLAN = "84e39d0d2987e153923c537587380e9eeecccfae0a50ede5be586e0238e4fe79"
BUNDLE = "b" * 64
ENV = {"GHOSTCURSOR_CAMPAIGN_SCOPE": "scope01", "GHOSTCURSOR_CAMPAIGN_SALT": "ab" * 32}


# --- harness path ------------------------------------------------------------


def _harness_records(index: int, *, nodes: int = 255) -> tuple[dict, ...]:
    return (
        {
            "type": "approved",
            "approval_sha256": "1" * 64,
            "bundle_sha256": BUNDLE,
            "catalog_generation": 10,
            "graph_sha256": "2" * 64,
            "manifest_sha256": PIN,
            "nodes": nodes,
            "output_path": f"D:/w/out/attempt-{index}.pptx",
            "plan_id": "build-investor-deck-v1",
            "plan_sha256": PLAN,
            "target_ref": "window-1a2b3c4d",
            "target_scope": "scope01",
        },
        {"type": "event", "event": "action_started", "ordinal": 1, "total": nodes},
        {
            "type": "result",
            "code": "completed",
            "completed": True,
            "completed_nodes": nodes,
            "published_sha256": f"{index:x}" * 64,
        },
    )


def _attempt(index: int, **kw) -> Attempt:
    records = kw.pop("records", _harness_records(index))
    result = [r for r in records if r["type"] == "result"][0]
    return Attempt(
        index=index,
        completed=result["completed"],
        code=result["code"],
        nodes=result["completed_nodes"],
        published_sha256=result.get("published_sha256"),
        output_path=None,
        seconds=100.0 + index,
        records=records,
    )


def _harness_report(attempts=None, **overrides) -> dict:
    report = campaign_report(
        status="clean",
        detail=None,
        attempts=attempts or [_attempt(i) for i in (1, 2, 3)],
        attempts_requested=3,
        binding={
            "bundle_sha256": BUNDLE,
            "commit": COMMIT,
            "manifest_sha256": PIN,
            "mode": "quick",
            "plan_id": "build-investor-deck-v1",
            "plan_sha256": PLAN,
        },
    )
    report.update(overrides)
    return report


def test_a_clean_harness_campaign_is_accepted_and_renders():
    summary = checker.check_harness(_harness_report())
    document = checker.render(summary)

    assert [row[0] for row in summary["rows"]] == [1, 2, 3]
    assert PIN in document and COMMIT in document
    assert "3 of 3 consecutive attempts" in document


def _mutate(report, path, value):
    report = copy.deepcopy(report)
    target = report
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return report


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("binding", "manifest_sha256"), "0" * 64, "not the pinned"),
        (("binding", "commit"), "HEAD", "names no commit"),
        (("campaign",), "refused", "campaign ended"),
        (("attempts_requested",), 4, "requested 4"),
        (
            ("attempts", 0, "records", 0, "manifest_sha256"),
            "0" * 64,
            "unpinned manifest",
        ),
        (("attempts", 1, "records", 0, "plan_sha256"), "0" * 64, "different plan"),
        (("attempts", 2, "records", 2, "completed_nodes"), 254, "not completed"),
        (("attempts", 2, "records", 2, "code"), "refused", "not completed"),
        (
            ("attempts", 1, "records", 0, "target_ref"),
            "window-ffffffff",
            "one campaign-scoped target",
        ),
        (
            ("attempts", 2, "records", 2, "published_sha256"),
            "1" * 64,
            "nothing published",
        ),
    ],
)
def test_each_harness_violation_is_refused(path, value, reason):
    with pytest.raises(checker.CampaignRefused, match=reason):
        checker.check_harness(_mutate(_harness_report(), path, value))


def test_a_dropped_attempt_is_refused():
    report = _harness_report()
    report["attempts"] = [report["attempts"][0], report["attempts"][2]]
    with pytest.raises(checker.CampaignRefused, match="not exactly 1..3"):
        checker.check_harness(report)


def test_a_reused_artifact_is_refused():
    report = _harness_report()
    same = report["attempts"][0]["published_sha256"]
    for attempt in report["attempts"]:
        attempt["published_sha256"] = same
        attempt["records"][2]["published_sha256"] = same
    with pytest.raises(checker.CampaignRefused, match="not distinct"):
        checker.check_harness(report)


def test_a_raw_handle_in_a_record_is_refused_at_retention_and_at_check():
    leaked = _harness_records(1)
    leaked[0]["target_hwnd"] = 123456
    with pytest.raises(CampaignError, match="target_hwnd"):
        retained_records(leaked)

    report = _harness_report()
    report["attempts"][0]["records"][0]["hwnd"] = 123456
    with pytest.raises(checker.CampaignRefused, match="hwnd"):
        checker.check_harness(report)


def test_a_refused_campaign_keeps_the_attempt_that_ended_it():
    failed = _attempt(
        2,
        records=_harness_records(2, nodes=255)[:2]
        + (
            {
                "type": "result",
                "code": "refused",
                "completed": False,
                "completed_nodes": 40,
                "published_sha256": None,
            },
        ),
    )
    report = campaign_report(
        status="refused",
        detail="attempt 2 was not clean",
        attempts=[_attempt(1), failed],
        attempts_requested=3,
        binding=_harness_report()["binding"],
    )
    assert [a["index"] for a in report["attempts"]] == [1, 2]
    with pytest.raises(checker.CampaignRefused, match="campaign ended"):
        checker.check_harness(report)


def test_check_mode_rejects_a_hand_edited_document(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps(_harness_report()), encoding="utf-8")
    out = tmp_path / "campaign.md"

    assert checker.main(["--harness", str(report), "--out", str(out)]) == 0
    assert checker.main(["--harness", str(report), "--out", str(out), "--check"]) == 0
    out.write_bytes(out.read_bytes().replace(b"3 of 3", b"4 of 4"))
    assert checker.main(["--harness", str(report), "--out", str(out), "--check"]) == 2


# --- manager path ------------------------------------------------------------


def _manager_transcript(index: int, *, total: int = 3, order=None) -> list[dict]:
    kinds = list(order or checker.MANAGER_ORDER)
    body = []
    for kind in kinds:
        if kind == "act_run_result":
            body.extend(
                {"type": "act_runtime_event", "total": total} for _ in range(total)
            )
        body.append({"type": kind})
    records = []
    for sequence, record in enumerate([{"type": "manager_opened"}, *body], start=1):
        record.update(sequence=sequence, at_ns=sequence * 1_000_000_000)
        if record["type"] == "act_proposal_displayed":
            record.update(manifest_sha256=PIN, output_path_sha256=f"{index:x}" * 64)
        if record["type"] == "act_run_result":
            record.update(code="completed", completed=True, completed_nodes=total)
        records.append(record)
    return records


def _manager_campaign(tmp_path, transcripts=None) -> Path:
    directory = tmp_path / "campaign"
    directory.mkdir()
    entries = []
    for index, records in enumerate(
        transcripts or [_manager_transcript(i) for i in (1, 2, 3)], start=1
    ):
        name = manager_campaign.transcript_name(index)
        raw = "".join(json.dumps(r, sort_keys=True) + "\n" for r in records).encode(
            "utf-8"
        )
        (directory / name).write_bytes(raw)
        entries.append(
            {
                "index": index,
                "manager_exit": 0,
                "transcript": name,
                "transcript_sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    (directory / "campaign.json").write_text(
        json.dumps(
            {
                "attempts": entries,
                "path": "manager",
                "schema_version": 1,
                "binding": {
                    "commit": COMMIT,
                    "manifest_sha256": PIN,
                    "plan_id": "build-investor-deck-v1",
                    "plan_sha256": PLAN,
                    "scope": "scope01",
                },
            }
        ),
        encoding="utf-8",
    )
    return directory


def test_a_clean_manager_campaign_is_accepted(tmp_path):
    summary = checker.check_manager(_manager_campaign(tmp_path))
    assert [row[1] for row in summary["rows"]] == ["3/3"] * 3


def test_the_d123_order_is_enforced(tmp_path):
    order = list(checker.MANAGER_ORDER)
    order[1], order[2] = order[2], order[1]  # approval before the handoff
    transcripts = [
        _manager_transcript(1),
        _manager_transcript(2, order=order),
        _manager_transcript(3),
    ]
    with pytest.raises(checker.CampaignRefused, match="D123"):
        checker.check_manager(_manager_campaign(tmp_path, transcripts))


def test_a_transcript_edited_after_recording_is_refused(tmp_path):
    directory = _manager_campaign(tmp_path)
    path = directory / manager_campaign.transcript_name(2)
    path.write_bytes(
        path.read_bytes().replace(b'"completed_nodes": 3', b'"completed_nodes": 3 ')
    )
    with pytest.raises(checker.CampaignRefused, match="changed after it was recorded"):
        checker.check_manager(directory)


def test_an_unlisted_transcript_on_disk_is_refused(tmp_path):
    """A fourth attempt left out of `campaign.json` is a dropped attempt."""

    directory = _manager_campaign(tmp_path)
    (directory / manager_campaign.transcript_name(4)).write_text(
        "{}\n", encoding="utf-8"
    )
    with pytest.raises(
        checker.CampaignRefused, match="differ from the campaign's list"
    ):
        checker.check_manager(directory)


def test_a_transcript_with_a_sequence_gap_is_refused(tmp_path):
    """A removed record leaves a gap in the manager's own sequence numbers."""

    transcripts = [_manager_transcript(i) for i in (1, 2, 3)]
    del transcripts[1][3]
    with pytest.raises(checker.CampaignRefused, match="sequence has a gap"):
        checker.check_manager(_manager_campaign(tmp_path, transcripts))


def test_an_incomplete_manager_attempt_is_refused(tmp_path):
    transcripts = [_manager_transcript(i) for i in (1, 2, 3)]
    transcripts[2][-1]["completed_nodes"] = 2
    with pytest.raises(checker.CampaignRefused, match="not completed"):
        checker.check_manager(_manager_campaign(tmp_path, transcripts))


def test_the_real_diagnostic_transcripts_parse_and_fail_only_on_their_manifest(
    tmp_path,
):
    """The 11 September transcripts are real manager output. Checked here with a
    pinned binding, every structural check passes and the refusal is the one
    that should fire: they bound the superseded `28dbaf2d` (D149)."""

    source = ROOT / "docs" / "evidence" / "diagnostic"
    directory = tmp_path / "real"
    directory.mkdir()
    entries = []
    for index in (1, 2, 3):
        name = manager_campaign.transcript_name(index)
        shutil.copyfile(source / name, directory / name)
        entries.append(
            {
                "index": index,
                "manager_exit": 0,
                "transcript": name,
                "transcript_sha256": hashlib.sha256(
                    (source / name).read_bytes()
                ).hexdigest(),
            }
        )
    (directory / "campaign.json").write_text(
        json.dumps(
            {
                "attempts": entries,
                "path": "manager",
                "schema_version": 1,
                "binding": {
                    "commit": COMMIT,
                    "manifest_sha256": PIN,
                    "plan_id": "build-investor-deck-v1",
                    "plan_sha256": PLAN,
                    "scope": "s",
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        checker.CampaignRefused, match="proposal bound an unpinned manifest"
    ):
        checker.check_manager(directory)


# --- manager runner preflight ----------------------------------------------------


def _prepare(directory, attempt, **overrides):
    values = {
        "environment": ENV,
        "commit": COMMIT,
        "manifest_sha256": PIN,
        "plan_sha256": PLAN,
    }
    values.update(overrides)
    return manager_campaign.prepare_attempt(directory, attempt, **values)


def test_the_runner_refuses_an_unpinned_manifest_and_a_missing_scope(tmp_path):
    with pytest.raises(CampaignPreflightError, match="not the pinned"):
        _prepare(tmp_path, 1, manifest_sha256="0" * 64)
    with pytest.raises(CampaignPreflightError, match="exported"):
        _prepare(tmp_path, 1, environment={})
    with pytest.raises(CampaignPreflightError):
        require_pinned_manifest(
            "28dbaf2d372c55144e289316a1b92dd25185281351cd685a8e735ee9d759a836"
        )


def test_the_runner_enforces_consecutive_attempts_and_one_binding(tmp_path):
    with pytest.raises(CampaignPreflightError, match="starts at attempt 1"):
        _prepare(tmp_path, 2)

    transcript = _prepare(tmp_path, 1)
    transcript.write_text(
        "".join(json.dumps(r) + "\n" for r in _manager_transcript(1)), encoding="utf-8"
    )
    manager_campaign.record_attempt(tmp_path, 1, 0)

    with pytest.raises(CampaignPreflightError, match="not the next consecutive"):
        _prepare(tmp_path, 3)
    with pytest.raises(CampaignPreflightError, match="differs from the campaign"):
        _prepare(tmp_path, 2, commit="d" * 40)
    assert _prepare(tmp_path, 2).name == manager_campaign.transcript_name(2)


def test_the_runner_does_not_continue_past_an_unclean_attempt(tmp_path):
    transcript = _prepare(tmp_path, 1)
    records = _manager_transcript(1)
    records[-1]["completed"] = False
    transcript.write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )
    manager_campaign.record_attempt(tmp_path, 1, 0)

    with pytest.raises(CampaignPreflightError, match="did not complete"):
        _prepare(tmp_path, 2)


def test_the_runner_never_overwrites_a_transcript(tmp_path):
    _prepare(tmp_path, 1).write_text("{}\n", encoding="utf-8")
    with pytest.raises(CampaignPreflightError, match="never overwrite"):
        _prepare(tmp_path, 1)
