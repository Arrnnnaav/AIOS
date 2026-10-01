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
BUILD = "16.0.20326.20158"
CAMPAIGN = "2026-10-01-deck"
ENV = {"GHOSTCURSOR_CAMPAIGN_SCOPE": "scope01", "GHOSTCURSOR_CAMPAIGN_SALT": "ab" * 32}


# --- harness path ------------------------------------------------------------


def _deck(index: int) -> bytes:
    """Stand-in bytes for attempt `index`'s published deck."""

    return f"deck-{index}".encode("utf-8")


_DECK_PLAN = json.loads(
    (
        ROOT / "plugins" / "sources" / "powerpoint" / "payload" / "ghostcursor"
        / "action-plans" / "build-investor-deck-v1.json"
    ).read_text(encoding="utf-8")
)["nodes"]


def _events(nodes: int = 255) -> list[dict]:
    """The runtime events of a clean attempt over the first `nodes` plan nodes."""

    stream, at = [], 0.0
    for ordinal, node in enumerate(_DECK_PLAN[:nodes], start=1):
        for kind in ("action_started", "action_completed"):
            at += 0.125
            stream.append({"type": "event", "event": kind, "ordinal": ordinal, "total": nodes,
                           "node_id": node["node_id"], "operation_id": node["operation_id"],
                           "at_s": at, "detail": "", "region": None})
    stream.append({"type": "event", "event": "completed", "ordinal": nodes, "total": nodes,
                   "node_id": None, "operation_id": None, "at_s": at + 0.125,
                   "detail": "all actions verified", "region": None})
    return stream


def _harness_records(index: int, *, nodes: int = 255) -> tuple[dict, ...]:
    return (
        {
            "type": "approved",
            "application_version": BUILD,
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
        *_events(nodes),
        {
            "type": "result",
            "code": "completed",
            "completed": True,
            "completed_nodes": nodes,
            "published_sha256": hashlib.sha256(_deck(index)).hexdigest(),
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
            "campaign_id": CAMPAIGN,
            "commit": COMMIT,
            "manifest_sha256": PIN,
            "mode": "quick",
            "plan_id": "build-investor-deck-v1",
            "plan_sha256": PLAN,
        },
    )
    for attempt in report["attempts"]:
        attempt.setdefault("artifact", f"attempt-{attempt['index']:02d}.pptx")
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
        (("attempts", 2, "records", -1, "completed_nodes"), 254, "not completed"),
        (("attempts", 2, "records", -1, "code"), "refused", "not completed"),
        (
            ("attempts", 1, "records", 0, "target_ref"),
            "window-ffffffff",
            "one campaign-scoped target",
        ),
        (
            ("attempts", 2, "records", -1, "published_sha256"),
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
        attempt["records"][-1]["published_sha256"] = same
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
    value = _harness_report()
    decks = tmp_path / "decks"
    decks.mkdir()
    for attempt in value["attempts"]:
        name = f"attempt-{attempt['index']:02d}.pptx"
        (decks / name).write_bytes(_deck(attempt["index"]))
        attempt["artifact"] = name
    report.write_text(json.dumps(value), encoding="utf-8")
    out = tmp_path / "campaign.md"

    assert checker.main(["--harness", str(report), "--out", str(out), "--artifacts", str(decks)]) == 0
    (decks / "attempt-02.pptx").write_bytes(b"swapped")
    assert checker.main(["--harness", str(report), "--out", str(out), "--artifacts", str(decks), "--check"]) == 3
    (decks / "attempt-02.pptx").write_bytes(_deck(2))
    digest = hashlib.sha256(report.read_bytes()).hexdigest()
    assert f"- `report.json` — SHA-256 `{digest}`" in out.read_text(encoding="utf-8")
    assert checker.main(["--harness", str(report), "--out", str(out), "--check"]) == 0
    out.write_bytes(out.read_bytes().replace(b"3 of 3", b"4 of 4"))
    assert checker.main(["--harness", str(report), "--out", str(out), "--check"]) == 2


# --- manager path ------------------------------------------------------------


def _manager_transcript(index: int, *, total: int = 255, order=None) -> list[dict]:
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
        if sequence > 1:
            record["proposal_sha256"] = f"{index + 9:x}" * 64
        if record["type"] == "act_proposal_displayed":
            record.update(
                application_version=BUILD,
                intent_id="BUILD_INVESTOR_DECK",
                manifest_sha256=PIN,
                output_path_sha256=f"{index:x}" * 64,
            )
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
                    "intent_id": "BUILD_INVESTOR_DECK",
                    "manifest_sha256": PIN,
                    "plan_id": "build-investor-deck-v1",
                    "plan_sha256": PLAN,
                    "scope": "scope01",
                    "campaign_id": CAMPAIGN,
                },
            }
        ),
        encoding="utf-8",
    )
    return directory


def test_a_clean_manager_campaign_is_accepted(tmp_path):
    summary = checker.check_manager(_manager_campaign(tmp_path))
    assert [row[1] for row in summary["rows"]] == ["255/255"] * 3


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
        path.read_bytes().replace(b'"completed_nodes": 255', b'"completed_nodes": 255 ')
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
                    "intent_id": "BUILD_INVESTOR_DECK",
                    "manifest_sha256": PIN,
                    "plan_id": "build-investor-deck-v1",
                    "plan_sha256": PLAN,
                    "scope": "s",
                    "campaign_id": CAMPAIGN,
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


# --- D152: every refusal the second review found untested -------------------


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("attempts", 1, "records", 0, "bundle_sha256"), "0" * 64, "different bundle"),
        (("binding", "bundle_sha256"), "not-a-digest", "no bundle digest"),
        (("binding", "plan_sha256"), "not-a-digest", "no plan digest"),
        (("binding", "plan_id"), "some-other-plan", "unknown plan"),
        (("schema_version",), 1, "not a harness campaign report"),
        (("path",), "manager", "not a harness campaign report"),
        (("attempts", 2, "records", 0, "application_version"), "16.0.1.1", "one application build"),
        (("attempts", 0, "records", 1, "detail"), "refused: candidates hwnd=4460192", "carries"),
        (("attempts", 0, "records", 1, "nested"), {"window_handle": 7}, "carries"),
    ],
)
def test_each_newly_guarded_harness_violation_is_refused(path, value, reason):
    with pytest.raises(checker.CampaignRefused, match=reason):
        checker.check_harness(_mutate(_harness_report(), path, value))


def test_a_campaign_with_no_target_reference_at_all_is_refused():
    report = _harness_report()
    for attempt in report["attempts"]:
        attempt["records"][0]["target_ref"] = None
    with pytest.raises(checker.CampaignRefused, match="one campaign-scoped target"):
        checker.check_harness(report)


def test_the_policy_is_three_attempts_and_not_a_flag(tmp_path):
    report = _harness_report()
    report["attempts"] = report["attempts"][:1]
    report["attempts_requested"] = 1
    with pytest.raises(checker.CampaignRefused, match="not 3"):
        checker.check_harness(report)
    source = tmp_path / "r.json"
    source.write_text(json.dumps(_harness_report()), encoding="utf-8")
    with pytest.raises(SystemExit):
        checker.main(["--harness", str(source), "--out", str(tmp_path / "o.md"), "--attempts", "1"])


def _manager_with(tmp_path, change):
    transcripts = [_manager_transcript(i) for i in (1, 2, 3)]
    change(transcripts)
    return _manager_campaign(tmp_path, transcripts)


def test_manager_attempts_must_write_distinct_outputs(tmp_path):
    def same(ts):
        for records in ts:
            records[1]["output_path_sha256"] = "a" * 64
    with pytest.raises(checker.CampaignRefused, match="distinct outputs"):
        checker.check_manager(_manager_with(tmp_path, same))


def test_a_duplicated_lifecycle_record_is_refused(tmp_path):
    def duplicate(ts):
        extra = dict(ts[1][3])
        ts[1].insert(4, extra)
        for sequence, record in enumerate(ts[1], start=1):
            record["sequence"] = sequence
    with pytest.raises(checker.CampaignRefused, match="expected exactly one"):
        checker.check_manager(_manager_with(tmp_path, duplicate))


def test_a_raw_handle_in_a_manager_record_is_refused(tmp_path):
    def leak(ts):
        ts[0][2]["hwnd"] = 4460192
    with pytest.raises(checker.CampaignRefused, match="carries"):
        checker.check_manager(_manager_with(tmp_path, leak))


def test_a_manager_attempt_answering_another_intent_is_refused(tmp_path):
    def other(ts):
        ts[1][1]["intent_id"] = "BUILD_ANIMATION_CATALOG"
    with pytest.raises(checker.CampaignRefused, match="another intent"):
        checker.check_manager(_manager_with(tmp_path, other))


def test_a_result_for_a_different_proposal_is_refused(tmp_path):
    def swap(ts):
        ts[2][-1]["proposal_sha256"] = "f" * 64
    with pytest.raises(checker.CampaignRefused, match="more than one proposal"):
        checker.check_manager(_manager_with(tmp_path, swap))


def test_backwards_timestamps_are_refused(tmp_path):
    def rewind(ts):
        ts[0][-1]["at_ns"] = 1
    with pytest.raises(checker.CampaignRefused, match="backwards"):
        checker.check_manager(_manager_with(tmp_path, rewind))


def test_manager_attempts_must_name_one_build(tmp_path):
    def drift(ts):
        ts[2][1]["application_version"] = "16.0.20326.20112"
    with pytest.raises(checker.CampaignRefused, match="one application build"):
        checker.check_manager(_manager_with(tmp_path, drift))


def test_the_rendered_document_names_the_build():
    document = checker.render(checker.check_harness(_harness_report()))
    assert f"PowerPoint build: `{BUILD}`" in document


# --- preflight helpers against real bytes and a real git repository ---------


def _git(root, *args):
    import subprocess

    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    (root / "tracked.txt").write_text("a\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-q", "-m", "init")
    return root


def test_a_dirty_tree_refuses_and_a_clean_one_names_head(tmp_path):
    from ghostcursor.devtools.campaign_pins import repository_commit

    root = _repo(tmp_path)
    assert len(repository_commit(root)) == 40
    (root / "tracked.txt").write_text("b\n", encoding="utf-8")
    with pytest.raises(CampaignPreflightError, match="uncommitted"):
        repository_commit(root)


def test_the_bundle_manifest_digest_is_taken_over_plugin_json(tmp_path):
    import zipfile

    from ghostcursor.devtools.campaign_pins import bundle_manifest_sha256

    bundle = tmp_path / "b.ghostplugin"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("signature.ed25519", b"s" * 64)
        archive.writestr("plugin.json", b"manifest-bytes")
        archive.writestr("ghostcursor/x.json", b"other")
    assert bundle_manifest_sha256(bundle) == hashlib.sha256(b"manifest-bytes").hexdigest()


def test_a_campaign_must_be_declared_in_the_committed_ledger(tmp_path):
    from ghostcursor.devtools.campaign_pins import LEDGER_RELATIVE, require_ledgered

    root = _repo(tmp_path)
    ledger = root / LEDGER_RELATIVE
    ledger.parent.mkdir(parents=True)
    entry = {"campaign_id": "2026-10-01-deck", "manifest_sha256": PIN,
             "path": "harness", "plan_id": "build-investor-deck-v1"}
    ledger.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    with pytest.raises(CampaignPreflightError, match="not committed"):
        require_ledgered("2026-10-01-deck", path="harness", plan_id="build-investor-deck-v1", root=root)
    _git(root, "add", LEDGER_RELATIVE)
    _git(root, "commit", "-q", "-m", "declare")

    assert require_ledgered("2026-10-01-deck", path="harness", plan_id="build-investor-deck-v1", root=root) == entry
    with pytest.raises(CampaignPreflightError, match="exactly once"):
        require_ledgered("2026-10-01-other", path="harness", plan_id="build-investor-deck-v1", root=root)
    with pytest.raises(CampaignPreflightError, match="different path"):
        require_ledgered("2026-10-01-deck", path="manager", plan_id="build-investor-deck-v1", root=root)
    with pytest.raises(CampaignPreflightError, match="malformed"):
        require_ledgered("../escape", path="harness", plan_id="build-investor-deck-v1", root=root)


def test_a_refused_campaign_report_keeps_attempts_and_publishes_no_handle(tmp_path):
    """Review B1: a second window at attempt 2 must not put handles into the
    retained report, and attempt 1 must survive."""

    import json as _json

    from ghostcursor.devtools.act_campaign import run_campaign

    windows = iter([(4712093,), (5823104, 6934215)])

    def launch(command, **_):
        from types import SimpleNamespace

        stdout = "\n".join(_json.dumps(r) for r in _harness_records(1)) + "\n"
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    with pytest.raises(CampaignError) as raised:
        run_campaign(
            attempts=3, build_command=lambda *a: ["x"], workspace=tmp_path,
            window_class="PPTFrameClass", restore=lambda _c: next(windows),
            launch=launch, settle_s=0,
        )
    report = campaign_report(
        status="refused", detail=str(raised.value), attempts=raised.value.attempts,
        attempts_requested=3, binding=_harness_report()["binding"],
    )
    serialized = _json.dumps(report)
    assert [a["index"] for a in report["attempts"]] == [1]
    for handle in ("4712093", "5823104", "6934215"):
        assert handle not in serialized


def test_a_crashed_attempt_keeps_a_redacted_cause():
    from ghostcursor.devtools.act_campaign import redacted_last_line

    line = redacted_last_line("trace\nRuntimeError: two windows 4460192 and 5550123 sha abcd1234ef\n")
    assert "4460192" not in line and "5550123" not in line and "<n>" in line
    assert "abcd1234ef" in line


def test_the_harness_can_reach_presentation_for_from_the_cli():
    """Review I3: a function defined after the __main__ guard is unbound when
    the module runs as `python -m`, so a pointer plan died with NameError."""

    import ast

    source = (ROOT / "ghostcursor" / "devtools" / "act_acceptance.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    guard = next(
        i for i, node in enumerate(tree.body)
        if isinstance(node, ast.If) and "__main__" in ast.unparse(node.test)
    )
    defined = [
        node.name for node in tree.body[:guard] if isinstance(node, ast.FunctionDef)
    ]
    assert "presentation_for" in defined and "run" in defined
    assert all(not isinstance(node, ast.FunctionDef) for node in tree.body[guard + 1:])


def test_an_attempt_without_exactly_one_approved_record_is_refused():
    report = _harness_report()
    report["attempts"][1]["records"].insert(0, dict(report["attempts"][1]["records"][0]))
    with pytest.raises(checker.CampaignRefused, match="needs one approved"):
        checker.check_harness(report)


def _rewrite_campaign(directory, change):
    path = directory / "campaign.json"
    campaign = json.loads(path.read_text(encoding="utf-8"))
    change(campaign)
    path.write_text(json.dumps(campaign), encoding="utf-8")
    return directory


def test_a_non_manager_campaign_file_is_refused(tmp_path):
    directory = _rewrite_campaign(_manager_campaign(tmp_path), lambda c: c.update(path="harness"))
    with pytest.raises(checker.CampaignRefused, match="not a manager campaign"):
        checker.check_manager(directory)


def test_a_campaign_binding_the_wrong_intent_is_refused(tmp_path):
    directory = _rewrite_campaign(
        _manager_campaign(tmp_path),
        lambda c: c["binding"].update(intent_id="BUILD_ANIMATION_CATALOG"),
    )
    with pytest.raises(checker.CampaignRefused, match="wrong intent"):
        checker.check_manager(directory)


def test_runtime_events_disagreeing_on_the_total_are_refused(tmp_path):
    def split(ts):
        events = [r for r in ts[0] if r["type"] == "act_runtime_event"]
        events[0]["total"] = 99
    with pytest.raises(checker.CampaignRefused, match="disagree on the node total"):
        checker.check_manager(_manager_with(tmp_path, split))


def test_a_staged_but_uncommitted_ledger_entry_is_refused(tmp_path):
    """The ledger is read from HEAD: a staged line could still be dropped
    after a failed campaign without any commit showing it existed."""

    from ghostcursor.devtools.campaign_pins import LEDGER_RELATIVE, require_ledgered

    root = _repo(tmp_path)
    ledger = root / LEDGER_RELATIVE
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({"campaign_id": "2026-10-01-deck", "manifest_sha256": PIN,
                                  "path": "harness", "plan_id": "build-investor-deck-v1"}) + "\n",
                      encoding="utf-8")
    _git(root, "add", LEDGER_RELATIVE)
    with pytest.raises(CampaignPreflightError, match="not committed"):
        require_ledgered("2026-10-01-deck", path="harness", plan_id="build-investor-deck-v1", root=root)


# --- D154: every exit writes, and the checker binds the signed plan ----------


def _binding_base():
    binding = dict(_harness_report()["binding"])
    binding.update(commit=None, manifest_sha256=None)
    return binding


def test_a_preflight_refusal_after_declaration_still_writes_a_report(tmp_path):
    """Review B1: once the ledger line is committed, a dirty tree or an unpinned
    manifest must leave a retained `refused` report, not only stdout."""

    from ghostcursor.devtools.act_campaign import conduct

    def preflight():
        raise CampaignPreflightError("the work tree has uncommitted tracked changes")

    report, code = conduct(
        report_path=tmp_path / "report.json",
        binding=_binding_base(),
        attempts_requested=3,
        preflight=preflight,
        run=lambda: pytest.fail("must not run after a preflight refusal"),
    )
    on_disk = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert code == 3 and on_disk == report
    assert report["campaign"] == "refused" and "preflight" in report["detail"]


def test_a_crashing_runner_still_writes_a_report(tmp_path):
    from ghostcursor.devtools.act_campaign import conduct

    def run():
        raise OSError("disk vanished")

    report, code = conduct(
        report_path=tmp_path / "report.json",
        binding=_binding_base(),
        attempts_requested=3,
        preflight=lambda: {"commit": COMMIT, "manifest_sha256": PIN},
        run=run,
    )
    assert code == 3 and report["campaign"] == "refused"
    assert (tmp_path / "report.json").is_file()


def test_an_existing_report_is_never_overwritten(tmp_path):
    from ghostcursor.devtools.act_campaign import conduct

    (tmp_path / "report.json").write_text("{}", encoding="utf-8")
    with pytest.raises(CampaignError, match="never overwrite"):
        conduct(
            report_path=tmp_path / "report.json",
            binding=_binding_base(),
            attempts_requested=3,
            preflight=dict,
            run=tuple,
        )
    assert (tmp_path / "report.json").read_text(encoding="utf-8") == "{}"


def test_a_timed_out_attempt_keeps_the_attempts_before_it(tmp_path):
    import subprocess as _subprocess
    from types import SimpleNamespace

    from ghostcursor.devtools.act_campaign import run_campaign

    calls = iter(range(10))

    def launch(command, **_):
        if next(calls) == 1:
            raise _subprocess.TimeoutExpired(command, 1800)
        stdout = "\n".join(json.dumps(r) for r in _harness_records(1)) + "\n"
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    with pytest.raises(CampaignError, match="TimeoutExpired") as raised:
        run_campaign(
            attempts=3,
            build_command=lambda *a: ["x"],
            workspace=tmp_path,
            window_class="PPTFrameClass",
            restore=lambda _c: (1,),
            launch=launch,
            settle_s=0,
        )
    assert [a.index for a in raised.value.attempts] == [1]


def test_a_leaking_record_is_withheld_but_its_attempt_is_kept():
    leaked = list(_harness_records(2))
    leaked[1] = {"type": "event", "detail": "candidates hwnd=4460192"}
    report = campaign_report(
        status="clean",
        detail=None,
        attempts=[_attempt(1), _attempt(2, records=tuple(leaked))],
        attempts_requested=3,
        binding=_harness_report()["binding"],
    )
    assert report["campaign"] == "refused"
    assert [a["index"] for a in report["attempts"]] == [1, 2]
    assert report["attempts"][1]["records"] == []
    assert report["attempts"][1]["records_withheld"]
    assert "4460192" not in json.dumps(report["attempts"][1]["records"])


def test_retained_artifacts_are_copied_and_digest_checked(tmp_path):
    from ghostcursor.devtools.act_campaign import retain_artifacts

    published = tmp_path / "out.pptx"
    published.write_bytes(_deck(1))
    attempt = Attempt(
        index=1,
        completed=True,
        code="completed",
        nodes=255,
        published_sha256=hashlib.sha256(_deck(1)).hexdigest(),
        output_path=str(published),
        seconds=1.0,
        records=_harness_records(1),
    )
    report = {"attempts": [{"index": 1, "published_sha256": attempt.published_sha256}]}
    retain_artifacts(report, [attempt], tmp_path / "artifacts")
    assert report["attempts"][0]["artifact"] == "attempt-01.pptx"
    assert (tmp_path / "artifacts" / "attempt-01.pptx").read_bytes() == _deck(1)

    published.write_bytes(b"changed")
    report = {"attempts": [{"index": 1, "published_sha256": attempt.published_sha256}]}
    retain_artifacts(report, [attempt], tmp_path / "artifacts2")
    assert "artifact" not in report["attempts"][0]
    assert report["attempts"][0]["artifact_refused"]


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("attempts", 1, "records", 0, "plan_id"), "animation-catalog-v1", "not the campaign"),
        (("attempts", 1, "records", 0, "nodes"), 3, "plan has 255 nodes"),
        (("binding", "plan_sha256"), "e" * 64, "not the signed plan"),
        (("binding", "campaign_id"), None, "no ledgered campaign id"),
    ],
)
def test_the_checker_binds_the_signed_plan_and_the_campaign(path, value, reason):
    with pytest.raises(checker.CampaignRefused, match=reason):
        checker.check_harness(_mutate(_harness_report(), path, value))


def test_a_catalog_campaign_under_the_decks_digest_is_refused():
    """Review I2/H1: the catalog's name over the deck's digest."""

    report = _mutate(_harness_report(), ("binding", "plan_id"), "animation-catalog-v1")
    with pytest.raises(checker.CampaignRefused, match="not the signed plan"):
        checker.check_harness(report)


def test_a_missing_or_substituted_retained_deck_is_refused(tmp_path):
    report = _harness_report()
    with pytest.raises(checker.CampaignRefused, match="missing from the store"):
        checker.check_harness(report, artifacts=tmp_path)
    for attempt in report["attempts"]:
        name = f"attempt-{attempt['index']:02d}.pptx"
        (tmp_path / name).write_bytes(b"not the published deck")
        attempt["artifact"] = name
    with pytest.raises(checker.CampaignRefused, match="not the published one"):
        checker.check_harness(report, artifacts=tmp_path)


def test_manager_node_totals_are_bound_to_the_signed_plan(tmp_path):
    transcripts = [_manager_transcript(i, total=3) for i in (1, 2, 3)]
    with pytest.raises(checker.CampaignRefused, match="plan has 255 nodes"):
        checker.check_manager(_manager_campaign(tmp_path, transcripts))


def test_a_manager_campaign_with_recorded_refusals_is_not_clean(tmp_path):
    directory = _rewrite_campaign(
        _manager_campaign(tmp_path), lambda c: c.update(refusals=["x"])
    )
    with pytest.raises(checker.CampaignRefused, match="recorded refusals"):
        checker.check_manager(directory)


def test_a_manager_refusal_after_declaration_is_retained(tmp_path):
    manager_campaign.record_refusal(tmp_path, CAMPAIGN, "attempt 1: dirty tree")
    manager_campaign.record_refusal(tmp_path, CAMPAIGN, "attempt 1: dirty tree again")
    campaign = json.loads((tmp_path / "campaign.json").read_text(encoding="utf-8"))
    assert campaign["path"] == "manager"
    assert campaign["binding"]["campaign_id"] == CAMPAIGN
    assert len(campaign["refusals"]) == 2


def test_each_plan_prints_its_own_verification_scope():
    deck = checker.render(checker.check_harness(_harness_report()))
    assert checker.PLAN_SCOPE["build-investor-deck-v1"] in deck
    assert "does not verify the effect" in checker.PLAN_SCOPE["animation-catalog-v1"]
    assert "verified every node" not in deck


def test_a_duplicate_ledger_declaration_is_refused(tmp_path):
    """Review I1/C2: weakening `len(matches) != 1` to `< 1` survived."""

    from ghostcursor.devtools.campaign_pins import LEDGER_RELATIVE, require_ledgered

    root = _repo(tmp_path)
    ledger = root / LEDGER_RELATIVE
    ledger.parent.mkdir(parents=True)
    line = json.dumps(
        {
            "campaign_id": "2026-10-01-deck",
            "manifest_sha256": PIN,
            "path": "harness",
            "plan_id": "build-investor-deck-v1",
        }
    ) + "\n"
    ledger.write_text(line + line, encoding="utf-8")
    _git(root, "add", LEDGER_RELATIVE)
    _git(root, "commit", "-q", "-m", "declare twice")
    with pytest.raises(CampaignPreflightError, match="exactly once"):
        require_ledgered(
            "2026-10-01-deck", path="harness", plan_id="build-investor-deck-v1", root=root
        )


def test_the_manager_audit_records_the_bound_build_under_schema_2():
    """Review I5: dropping the field or reverting the schema survived."""

    from types import SimpleNamespace

    from ghostcursor.manager import ManagerActAuditRecord, _proposal_audit_facts

    target = SimpleNamespace(
        executable="POWERPNT.EXE", executable_version=BUILD, hwnd=1, pid=1
    )
    facts = _proposal_audit_facts(
        "goal", SimpleNamespace(target=target, validated=None, descriptor=None)
    )
    assert facts["application_version"] == BUILD
    assert "application_version" in ManagerActAuditRecord.__dataclass_fields__
    source = (ROOT / "ghostcursor" / "manager.py").read_text(encoding="utf-8")
    assert "schema_version=2," in source and "schema_version=1," not in source


def test_the_harness_approved_record_names_the_build():
    import ast

    tree = ast.parse(
        (ROOT / "ghostcursor" / "devtools" / "act_acceptance.py").read_text(encoding="utf-8")
    )
    approved = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and getattr(call.func, "id", None) == "_emit"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value == "approved"
    ]
    assert len(approved) == 1
    keywords = {k.arg: ast.unparse(k.value) for k in approved[0].keywords}
    assert keywords.get("application_version") == "act_target.executable_version"


def test_a_plan_the_signed_index_does_not_list_is_refused(monkeypatch):
    monkeypatch.setitem(checker.PLAN_INTENTS, "ghost-plan-v1", "GHOST")
    report = _mutate(_harness_report(), ("binding", "plan_id"), "ghost-plan-v1")
    with pytest.raises(checker.CampaignRefused, match="does not list"):
        checker.check_harness(report)


def test_a_result_that_did_not_complete_is_refused_even_with_code_completed():
    report = _mutate(_harness_report(), ("attempts", 1, "records", -1, "completed"), False)
    with pytest.raises(checker.CampaignRefused, match="not completed"):
        checker.check_harness(report)


@pytest.mark.parametrize(
    "value",
    [
        {"detail": [{"hwnd": 1}]},
        {"events": [{"note": "target 4460192 gone"}]},
        {"detail": "window 0x1A2B3C"},
        {"detail": "HWND=0x00012a4f"},
        {"detail": "candidates: [(4460192, 'PowerPoint')]"},
        {"detail": "stale 5550123"},
        {"detail": "candidates [0x1A2B3C, 0x2B3C4D]"},
    ],
)
def test_handle_shaped_values_are_refused_at_any_depth(value):
    """Review I3: hex handles, bare numbers and nested lists all leaked."""

    from ghostcursor.devtools.act_campaign import record_leaks

    assert record_leaks(value)


@pytest.mark.parametrize(
    "value",
    [
        "Act plan completed",
        "published 94371 bytes",
        "16.0.20326.20158",
        "node 255 of 255",
        "2026-10-01T12:00:00Z",
        "window-12345678",
        "1" * 64,
    ],
)
def test_ordinary_values_are_not_mistaken_for_handles(value):
    from ghostcursor.devtools.act_campaign import record_leaks

    assert record_leaks({"detail": value}) == []


def test_an_attempt_without_a_result_keeps_the_attempts_before_it(tmp_path):
    """Review A6: a crashed attempt emitted no result record, and the refusal
    raised for it discarded the clean attempts that preceded it."""

    from types import SimpleNamespace

    from ghostcursor.devtools.act_campaign import run_campaign

    outputs = iter(
        [
            "\n".join(json.dumps(r) for r in _harness_records(1)) + "\n",
            "Traceback\nRuntimeError: boom\n",
        ]
    )

    def launch(command, **_):
        return SimpleNamespace(stdout=next(outputs), stderr="RuntimeError: boom 4460192", returncode=1)

    with pytest.raises(CampaignError) as raised:
        run_campaign(
            attempts=3,
            build_command=lambda *a: ["x"],
            workspace=tmp_path,
            window_class="PPTFrameClass",
            restore=lambda _c: (1,),
            launch=launch,
            settle_s=0,
        )
    assert [a.index for a in raised.value.attempts] == [1]
    assert "4460192" not in str(raised.value)


def test_the_campaign_scope_never_looks_like_a_number(tmp_path):
    """An all-digit scope trips the evidence handle scan in a committed report."""

    from types import SimpleNamespace

    from ghostcursor.devtools.act_campaign import run_campaign

    scopes = []

    def launch(command, env=None, **_):
        scopes.append(env["GHOSTCURSOR_CAMPAIGN_SCOPE"])
        stdout = "\n".join(json.dumps(r) for r in _harness_records(len(scopes))) + "\n"
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    for _ in range(20):
        scopes.clear()
        run_campaign(
            attempts=1,
            build_command=lambda *a: ["x"],
            workspace=tmp_path,
            window_class="PPTFrameClass",
            restore=lambda _c: (1,),
            launch=launch,
            settle_s=0,
        )
        assert scopes[0][0].isalpha()


def test_the_manager_runner_retains_a_refusal_after_declaration(tmp_path, monkeypatch):
    """Review B1 on the manager path: a refusal once declared is written down."""

    import ghostcursor.devtools.campaign_pins as pins
    import ghostcursor.plugins.platform as platform

    directory = tmp_path / "campaign"
    monkeypatch.setattr(pins, "campaign_directory", lambda _id: directory)
    monkeypatch.setattr(pins, "require_ledgered", lambda *a, **k: {})

    def broken_store():
        raise OSError("store unavailable")

    monkeypatch.setattr(platform, "production_store", broken_store)
    code = manager_campaign.main(["--campaign-id", CAMPAIGN, "--attempt", "1"])
    campaign = json.loads((directory / "campaign.json").read_text(encoding="utf-8"))
    assert code == 2
    assert campaign["refusals"] and "store unavailable" in campaign["refusals"][0]


# --- D155: fourth-review findings --------------------------------------------


def test_a_started_report_exists_before_anything_can_fail(tmp_path):
    """N3: a process killed outright still leaves a report that says it started."""

    from ghostcursor.devtools.act_campaign import conduct

    seen = {}

    def preflight():
        seen.update(json.loads((tmp_path / "report.json").read_text(encoding="utf-8")))
        return {"commit": COMMIT, "manifest_sha256": PIN}

    conduct(
        report_path=tmp_path / "report.json",
        binding=_binding_base(),
        attempts_requested=3,
        preflight=preflight,
        run=tuple,
    )
    assert seen["campaign"] == "started"


def test_an_interrupt_still_writes_the_report_and_then_propagates(tmp_path):
    """N3: Ctrl+C got past every `except Exception`."""

    from ghostcursor.devtools.act_campaign import conduct

    def run():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        conduct(
            report_path=tmp_path / "report.json",
            binding=_binding_base(),
            attempts_requested=3,
            preflight=lambda: {"commit": COMMIT, "manifest_sha256": PIN},
            run=run,
        )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["campaign"] == "refused" and "KeyboardInterrupt" in report["detail"]


def test_a_failing_deck_copy_does_not_lose_the_report(tmp_path, monkeypatch):
    """N3: a copy failure ran before the report write, unguarded."""

    import shutil

    from ghostcursor.devtools.act_campaign import conduct

    published = tmp_path / "out.pptx"
    published.write_bytes(_deck(1))
    attempt = Attempt(
        index=1,
        completed=True,
        code="completed",
        nodes=255,
        published_sha256=hashlib.sha256(_deck(1)).hexdigest(),
        output_path=str(published),
        seconds=1.0,
        records=_harness_records(1),
    )

    def broken_copy(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copyfile", broken_copy)
    report, _code = conduct(
        report_path=tmp_path / "report.json",
        binding=_binding_base(),
        attempts_requested=1,
        preflight=lambda: {"commit": COMMIT, "manifest_sha256": PIN},
        run=lambda: (attempt,),
        artifacts_dir=tmp_path / "decks",
    )
    assert report["attempts"][0]["artifact_refused"].startswith("copy failed")
    assert (tmp_path / "report.json").is_file()


def test_an_attempt_that_cannot_launch_keeps_the_attempts_before_it(tmp_path):
    """X1: narrowing the launch guard to TimeoutExpired survived."""

    from types import SimpleNamespace

    from ghostcursor.devtools.act_campaign import run_campaign

    calls = iter(range(10))

    def launch(command, **_):
        if next(calls) == 1:
            raise OSError("python.exe vanished")
        stdout = "\n".join(json.dumps(r) for r in _harness_records(1)) + "\n"
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    with pytest.raises(CampaignError, match="OSError") as raised:
        run_campaign(
            attempts=3,
            build_command=lambda *a: ["x"],
            workspace=tmp_path,
            window_class="PPTFrameClass",
            restore=lambda _c: (1,),
            launch=launch,
            settle_s=0,
        )
    assert [a.index for a in raised.value.attempts] == [1]


def test_a_missing_bundle_at_preflight_still_writes_a_report(tmp_path):
    """X3: a wrong --bundle path raises OSError, not a preflight refusal."""

    from ghostcursor.devtools.act_campaign import conduct

    def preflight():
        raise FileNotFoundError("no such bundle")

    report, code = conduct(
        report_path=tmp_path / "report.json",
        binding=_binding_base(),
        attempts_requested=3,
        preflight=preflight,
        run=tuple,
    )
    assert code == 3 and "no such bundle" in report["detail"]


def test_stderr_redaction_covers_hex_handles():
    """X13."""

    from ghostcursor.devtools.act_campaign import redacted_last_line

    line = redacted_last_line("RuntimeError: window 0x1A2B3C gone\n")
    assert "1A2B3C" not in line and "<n>" in line


def test_a_refused_campaign_renders_a_citable_document(tmp_path):
    """N5: a refused campaign needs a rendered document, not hand-written prose."""

    report = campaign_report(
        status="refused",
        detail="attempt 2 was not clean (refused, 40 nodes, published=False)",
        attempts=[_attempt(1)],
        attempts_requested=3,
        binding=_harness_report()["binding"],
    )
    source = tmp_path / "report.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    out = tmp_path / "campaign.md"
    assert checker.main(["--harness", str(source), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "NOT counted" in text and "attempt 2 was not clean" in text
    assert f"- `report.json` — SHA-256 `{hashlib.sha256(source.read_bytes()).hexdigest()}`" in text
    assert checker.main(["--harness", str(source), "--out", str(out), "--check"]) == 0


def test_a_manager_refusal_renders_a_citable_document(tmp_path):
    manager_campaign.record_refusal(tmp_path, CAMPAIGN, "attempt 1: dirty tree")
    out = tmp_path / "campaign.md"
    assert checker.main(["--manager", str(tmp_path), "--out", str(out)]) == 0
    assert "dirty tree" in out.read_text(encoding="utf-8")


def test_a_refusal_document_still_refuses_a_leaking_reason(tmp_path):
    report = campaign_report(
        status="refused",
        detail="two windows: hwnd 4460192 and 5550123",
        attempts=(),
        attempts_requested=3,
        binding=_harness_report()["binding"],
    )
    source = tmp_path / "report.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    assert checker.main(["--harness", str(source), "--out", str(tmp_path / "c.md")]) == 2


def test_the_commit_a_campaign_ran_at_must_contain_its_ledger_line(tmp_path):
    """X8: removing the commit-containment check survived."""

    sys.path.insert(0, str(ROOT / "tests"))
    import test_campaign_ledger as ledger

    root = _repo(tmp_path)
    head = subprocess_output(root, "rev-parse", "HEAD")
    entry = {
        "campaign_id": CAMPAIGN,
        "manifest_sha256": PIN,
        "path": "harness",
        "plan_id": "build-investor-deck-v1",
    }
    value = {
        "binding": {"campaign_id": CAMPAIGN, "commit": head, "plan_id": "build-investor-deck-v1"},
        "campaign": "refused",
        "detail": "x",
        "path": "harness",
        "schema_version": 2,
    }
    assert any("does not contain its ledger line" in p for p in ledger._binding_problems(entry, value, root))

    ledger_path = root / "docs" / "campaigns" / "ledger.jsonl"
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    _git(root, "add", "docs/campaigns/ledger.jsonl")
    _git(root, "commit", "-q", "-m", "declare")
    value["binding"]["commit"] = subprocess_output(root, "rev-parse", "HEAD")
    assert ledger._binding_problems(entry, value, root) == []


def subprocess_output(root, *args):
    import subprocess

    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def test_generated_ids_contain_no_digits():
    """R5: digits inside ids concatenated with dates and indices in paths into
    observed handle values; ids are now letters only."""

    from ghostcursor.devtools.act_campaign import letters

    for _ in range(200):
        value = letters(11)
        assert value.isalpha() and value.islower() and len(value) == 11
    acceptance = (ROOT / "ghostcursor" / "devtools" / "act_acceptance.py").read_text(encoding="utf-8")
    campaign = (ROOT / "ghostcursor" / "devtools" / "act_campaign.py").read_text(encoding="utf-8")
    assert 'run_id="r" + letters(11)' in acceptance
    assert 'token = "t" + letters(9)' in campaign
    assert '"s" + letters(11)' in campaign
    assert "uuid.uuid4().hex" not in campaign.split("def _attempts", 1)[1]


def test_decks_are_retained_outside_git():
    """N1/m2: tracked decks trip the CRLF and handle scans and publish the
    Office user name; they stay in the git-ignored store."""

    import subprocess

    from ghostcursor.devtools.act_campaign import REPOSITORY_ARTIFACTS

    relative = REPOSITORY_ARTIFACTS.relative_to(ROOT).as_posix() + "/probe/attempt-01.pptx"
    ignored = subprocess.run(["git", "check-ignore", "-q", relative], cwd=ROOT)
    assert ignored.returncode == 0


def test_any_deck_retention_failure_still_writes_the_report(tmp_path, monkeypatch):
    import ghostcursor.devtools.act_campaign as campaign

    def broken(*_a, **_k):
        raise RuntimeError("retention broke")

    monkeypatch.setattr(campaign, "retain_artifacts", broken)
    report, _code = campaign.conduct(
        report_path=tmp_path / "report.json",
        binding=_binding_base(),
        attempts_requested=3,
        preflight=lambda: {"commit": COMMIT, "manifest_sha256": PIN},
        run=tuple,
        artifacts_dir=tmp_path / "decks",
    )
    on_disk = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert on_disk["artifact_retention"] == "failed: RuntimeError"


def test_a_refusal_without_a_reason_is_not_rendered(tmp_path):
    report = campaign_report(
        status="refused", detail=None, attempts=(), attempts_requested=3,
        binding=_harness_report()["binding"],
    )
    source = tmp_path / "report.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    assert checker.main(["--harness", str(source), "--out", str(tmp_path / "c.md")]) == 2


def test_a_refusal_record_of_the_wrong_kind_is_not_rendered(tmp_path):
    source = tmp_path / "report.json"
    source.write_text(json.dumps({"campaign": "refused", "detail": "x", "path": "manager",
                                  "schema_version": 2, "binding": {"campaign_id": CAMPAIGN}}),
                      encoding="utf-8")
    assert checker.main(["--harness", str(source), "--out", str(tmp_path / "c.md")]) == 2


# --- D156: fifth-review residuals --------------------------------------------


def test_a_native_crash_is_named_not_numbered(tmp_path):
    """R1: an NTSTATUS exit code is a 10-digit decimal the renderer refuses."""

    from types import SimpleNamespace

    from ghostcursor.devtools.act_campaign import conduct, exit_label, run_campaign

    assert exit_label(0xC0000005) == "crashed (ACCESS_VIOLATION)"
    assert exit_label(-1073741819) == "crashed (ACCESS_VIOLATION)"
    assert exit_label(0xC0001234) == "crashed (native status)"
    assert exit_label(1) == "exit 1"

    outputs = iter(["\n".join(json.dumps(r) for r in _harness_records(1)) + "\n", ""])

    def launch(command, **_):
        stdout = next(outputs)
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0 if stdout else 0xC0000005)

    report, _ = conduct(
        report_path=tmp_path / "report.json",
        binding=_binding_base(),
        attempts_requested=3,
        preflight=lambda: {"commit": COMMIT, "manifest_sha256": PIN},
        run=lambda: run_campaign(
            attempts=3, build_command=lambda *a: ["x"], workspace=tmp_path / "w",
            window_class="PPTFrameClass", restore=lambda _c: (1,), launch=launch, settle_s=0,
        ),
    )
    assert "ACCESS_VIOLATION" in report["detail"] and "3221225477" not in report["detail"]
    out = tmp_path / "campaign.md"
    assert checker.main(["--harness", str(tmp_path / "report.json"), "--out", str(out)]) == 0


def test_an_interrupt_mid_campaign_keeps_the_attempts_that_ran(tmp_path):
    """R2: Ctrl+C during attempt 2 lost attempt 1 and its deck."""

    from types import SimpleNamespace

    from ghostcursor.devtools.act_campaign import conduct, run_campaign

    calls = iter(range(10))

    def launch(command, **_):
        if next(calls) == 1:
            raise KeyboardInterrupt
        stdout = "\n".join(json.dumps(r) for r in _harness_records(1)) + "\n"
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    with pytest.raises(KeyboardInterrupt):
        conduct(
            report_path=tmp_path / "report.json",
            binding=_binding_base(),
            attempts_requested=3,
            preflight=lambda: {"commit": COMMIT, "manifest_sha256": PIN},
            run=lambda: run_campaign(
                attempts=3, build_command=lambda *a: ["x"], workspace=tmp_path / "w",
                window_class="PPTFrameClass", restore=lambda _c: (1,), launch=launch, settle_s=0,
            ),
        )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["campaign"] == "refused"
    assert [a["index"] for a in report["attempts"]] == [1]
    assert "KeyboardInterrupt" in report["detail"]


def test_a_clean_report_the_checker_refuses_still_renders_as_not_counted(tmp_path):
    """R3: e.g. PowerPoint restarted between attempts, so the targets differ."""

    report = _harness_report()
    report["attempts"][2]["records"][0]["target_ref"] = "window-ffffffff"
    source = tmp_path / "report.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    out = tmp_path / "campaign.md"
    assert checker.main(["--harness", str(source), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "NOT counted" in text and "the checker refused it" in text
    assert "one campaign-scoped target" in text
    assert checker.main(["--harness", str(source), "--out", str(out), "--check"]) == 0


def test_a_manager_campaign_the_checker_refuses_still_renders(tmp_path):
    transcripts = [_manager_transcript(i) for i in (1, 2, 3)]
    transcripts[2][1]["application_version"] = "16.0.20326.20112"
    directory = _manager_campaign(tmp_path, transcripts)
    out = tmp_path / "campaign.md"
    assert checker.main(["--manager", str(directory), "--out", str(out)]) == 0
    assert "the checker refused it" in out.read_text(encoding="utf-8")


def test_a_handle_shaped_reason_is_made_safe_when_written(tmp_path):
    """R4: an all-decimal manifest prefix or HRESULT in a reason."""

    from ghostcursor.devtools.act_campaign import conduct, safe_detail

    detail, redacted = safe_detail("preflight: manifest 12345678 is not the pinned b0d63512")
    assert redacted and "12345678" not in detail
    assert safe_detail("attempt 2 was not clean (refused, 40 nodes)") == (
        "attempt 2 was not clean (refused, 40 nodes)", False
    )

    def preflight():
        raise RuntimeError("manifest 12345678 is not the pinned b0d63512")

    report, _ = conduct(
        report_path=tmp_path / "report.json", binding=_binding_base(),
        attempts_requested=3, preflight=preflight, run=tuple,
    )
    assert report["detail_redacted"] is True
    assert checker.main(["--harness", str(tmp_path / "report.json"), "--out", str(tmp_path / "c.md")]) == 0


def test_the_attempt_count_is_not_an_operator_choice():
    source = (ROOT / "ghostcursor" / "devtools" / "act_campaign.py").read_text(encoding="utf-8")
    assert '"--attempts"' not in source


# --- D160: S1 and the surviving mutants of the fifth review -----------------


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r["attempts"][1].pop("artifact"),
        lambda r: r["attempts"][1].update(artifact_refused="copy failed: OSError"),
        lambda r: r.update(artifact_retention="failed: RuntimeError"),
    ],
)
def test_a_campaign_whose_decks_were_not_retained_is_not_counted(tmp_path, change):
    """S1: the outcome is a fact of the report, not of a command-line flag."""

    report = _harness_report()
    change(report)
    with pytest.raises(checker.CampaignRefused, match="not retained|retention failed"):
        checker.check_harness(report)
    source = tmp_path / "report.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    out = tmp_path / "campaign.md"
    assert checker.main(["--harness", str(source), "--out", str(out)]) == 0
    assert "NOT counted" in out.read_text(encoding="utf-8")


def test_artifacts_flag_verifies_without_changing_the_document(tmp_path):
    report = _harness_report()
    source = tmp_path / "report.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    out = tmp_path / "campaign.md"
    assert checker.main(["--harness", str(source), "--out", str(out)]) == 0
    rendered = out.read_bytes()

    decks = tmp_path / "decks"
    decks.mkdir()
    for attempt in report["attempts"]:
        (decks / attempt["artifact"]).write_bytes(_deck(attempt["index"]))
    assert checker.main(["--harness", str(source), "--out", str(out), "--artifacts", str(decks), "--check"]) == 0
    (decks / "attempt-02.pptx").write_bytes(b"swapped")
    assert checker.main(["--harness", str(source), "--out", str(out), "--artifacts", str(decks), "--check"]) == 3
    assert checker.main(["--harness", str(source), "--out", str(out), "--artifacts", str(decks)]) == 3
    assert out.read_bytes() == rendered


def test_an_ordinary_failure_in_the_loop_refuses_without_reraising(tmp_path):
    """M5: an OSError inside an attempt is a refusal that keeps what ran, not an interrupt."""

    from types import SimpleNamespace

    from ghostcursor.devtools.act_campaign import CampaignInterrupted, conduct, run_campaign

    windows = iter([(1,), OSError("enumeration failed")])

    def restore(_c):
        value = next(windows)
        if isinstance(value, Exception):
            raise value
        return value

    def launch(command, **_):
        stdout = "\n".join(json.dumps(r) for r in _harness_records(1)) + "\n"
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    with pytest.raises(CampaignError) as raised:
        run_campaign(attempts=3, build_command=lambda *a: ["x"], workspace=tmp_path / "w",
                     window_class="PPTFrameClass", restore=restore, launch=launch, settle_s=0)
    assert not isinstance(raised.value, CampaignInterrupted)
    assert [a.index for a in raised.value.attempts] == [1]

    windows = iter([(1,), OSError("enumeration failed")])
    report, code = conduct(
        report_path=tmp_path / "report.json", binding=_binding_base(), attempts_requested=3,
        preflight=lambda: {"commit": COMMIT, "manifest_sha256": PIN},
        run=lambda: run_campaign(attempts=3, build_command=lambda *a: ["x"], workspace=tmp_path / "w2",
                                 window_class="PPTFrameClass", restore=restore, launch=launch, settle_s=0),
    )
    assert code == 3 and "OSError" in report["detail"] and [a["index"] for a in report["attempts"]] == [1]


def test_the_public_key_is_read_raw_or_base64_and_nothing_else(tmp_path):
    """M11."""

    import base64

    from ghostcursor.devtools.act_acceptance import public_key_bytes

    raw = bytes(range(32))
    (tmp_path / "raw").write_bytes(raw)
    (tmp_path / "b64").write_bytes(base64.b64encode(raw) + b"\n")
    (tmp_path / "bad").write_bytes(base64.b64encode(b"short"))
    assert public_key_bytes(tmp_path / "raw") == raw
    assert public_key_bytes(tmp_path / "b64") == raw
    with pytest.raises(ValueError):
        public_key_bytes(tmp_path / "bad")


def test_the_binding_records_the_signing_key_id():
    """M19: read from the CLI wiring, since main() is the live entry."""

    import ast

    source = (ROOT / "ghostcursor" / "devtools" / "act_campaign.py").read_text(encoding="utf-8")
    main = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "main")
    bindings = [
        n for n in ast.walk(main)
        if isinstance(n, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "key_id" for k in n.keys)
    ]
    assert len(bindings) == 1
    value = bindings[0].values[[k.value for k in bindings[0].keys].index("key_id")]
    assert ast.unparse(value) == "arguments.key_id"


def test_a_checker_reason_is_made_safe_before_rendering(tmp_path):
    """N7: a refusal quoting an all-decimal digest prefix must still render."""

    report = _harness_report()
    report["binding"]["plan_sha256"] = "12345678" + "a" * 56
    source = tmp_path / "report.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    out = tmp_path / "campaign.md"
    assert checker.main(["--harness", str(source), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "the checker refused it" in text and "12345678" not in text


def test_an_uncleanable_reason_is_withheld_not_rendered(monkeypatch):
    """N10: if redaction cannot clear a reason, the reason is withheld."""

    import ghostcursor.devtools.act_campaign as campaign

    monkeypatch.setattr(campaign, "record_leaks", lambda value: ["detail.<text>"])
    detail, redacted = campaign.safe_detail("anything at all")
    assert redacted and detail.startswith("the refusal reason was withheld")


@pytest.mark.parametrize(
    "text",
    [
        "the target accepted the input",
        "window deadline passed",
        "target defaults changed",
        "handle bad state",
    ],
)
def test_english_after_a_handle_word_is_not_a_handle(text):
    from ghostcursor.devtools.act_campaign import record_leaks

    assert record_leaks({"detail": text}) == []


@pytest.mark.parametrize("kind", ["publish_refused", "interrupt_fired", "probe_faults"])
def test_a_disqualifying_record_beside_a_completed_result_is_refused(kind):
    report = _harness_report()
    report["attempts"][0]["records"].insert(-1, {"type": kind})
    with pytest.raises(checker.CampaignRefused, match="disqualifying"):
        checker.check_harness(report)


@pytest.mark.parametrize(
    "change",
    [
        lambda ev: ev.pop(10),  # a node's verification is missing
        lambda ev: ev.__setitem__(3, dict(ev[3], event="action_failed")),
        lambda ev: ev.__setitem__(5, dict(ev[5], ordinal=99)),
        lambda ev: ev.__setitem__(7, dict(ev[7], node_id="n999-forged")),
        lambda ev: ev.pop(),  # no final completed event
        lambda ev: ev.__setitem__(9, dict(ev[9], at_s=-1.0)),
    ],
)
def test_the_event_stream_itself_must_show_every_node_verified(change):
    """Review E1: completion is recomputed from the runtime's own events, not
    taken from the result record's summary count."""

    report = _harness_report()
    records = report["attempts"][1]["records"]
    events = [r for r in records if r.get("type") == "event"]
    others = [r for r in records if r.get("type") != "event"]
    change(events)
    report["attempts"][1]["records"] = [others[0], *events, *others[1:]]
    with pytest.raises(checker.CampaignRefused, match="events|event times"):
        checker.check_harness(report)


def test_the_retained_campaign_passes_the_event_stream_check():
    """The accepted 1 October campaign must satisfy the stricter checker as is."""

    source = ROOT / "docs" / "evidence" / "campaigns" / "2026-10-01-investor-deck-harness" / "report.json"
    summary = checker.check_harness(json.loads(source.read_text(encoding="utf-8")))
    assert [row[1] for row in summary["rows"]] == ["255/255"] * 3

