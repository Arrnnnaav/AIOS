"""Every declared campaign is retained, and the ledger only grows (D152).

A counted campaign is declared in `docs/campaigns/ledger.jsonl`, in a
commit, before its first attempt; both runners refuse otherwise. This test is
the other half: every declared campaign must have its results under
`docs/evidence/campaigns/<id>/`, a clean one must carry a document that
re-renders from its records, and no line may ever be removed or changed.
Without it, running campaigns until one passes and keeping only that one is
invisible (review I2).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEDGER = "docs/campaigns/ledger.jsonl"
FIELDS = {"campaign_id", "manifest_sha256", "path", "plan_id"}


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        pytest.skip("not a git work tree")
    return result.stdout


def _commit_declares(root: Path, commit: str, campaign_id: str) -> bool:
    shown = subprocess.run(
        ["git", "show", f"{commit}:{LEDGER}"], cwd=root, capture_output=True, text=True
    )
    return shown.returncode == 0 and any(
        json.loads(line).get("campaign_id") == campaign_id
        for line in shown.stdout.splitlines()
        if line.strip()
    )


def _binding_problems(entry: dict, value: dict, root: Path) -> list[str]:
    """A retained result belongs to THIS entry, whatever its outcome (review I1).

    Without this, a failed campaign could be retained as `{}`, or campaign A's
    clean report copied into campaign B's directory.
    """

    cid = entry["campaign_id"]
    problems = []
    schema = (2, "harness") if entry["path"] == "harness" else (1, "manager")
    if (value.get("schema_version"), value.get("path")) != schema:
        problems.append(f"{cid}: retained result is not a {entry['path']} campaign record")
        return problems
    binding = value.get("binding") or {}
    if binding.get("campaign_id") != cid:
        problems.append(f"{cid}: retained result names campaign {binding.get('campaign_id')!r}")
    if "plan_id" in binding and binding["plan_id"] != entry["plan_id"]:
        problems.append(f"{cid}: retained result ran plan {binding['plan_id']!r}")
    if binding.get("manifest_sha256") not in (None, entry["manifest_sha256"]):
        problems.append(f"{cid}: retained result bound another manifest")
    if entry["path"] == "harness" and value.get("campaign") != "clean" and not value.get("detail"):
        problems.append(f"{cid}: a refused campaign must say why")
    commit = binding.get("commit")
    if commit and not _commit_declares(root, commit, cid):
        problems.append(f"{cid}: the commit it ran at does not contain its ledger line")
    return problems


def entries_problems(entries, root: Path) -> list[str]:
    """What is wrong with these ledger entries against the files under `root`."""

    problems, seen = [], set()
    for entry in entries:
        if set(entry) != FIELDS:
            problems.append(f"entry fields {sorted(entry)} are not {sorted(FIELDS)}")
            continue
        cid = entry["campaign_id"]
        if cid in seen:
            problems.append(f"{cid} declared twice")
        seen.add(cid)
        directory = root / "docs" / "evidence" / "campaigns" / cid
        source = directory / (
            "report.json" if entry["path"] == "harness" else "campaign.json"
        )
        if not source.is_file():
            problems.append(f"{cid}: declared but its results are not retained")
            continue
        value = json.loads(source.read_text(encoding="utf-8"))
        problems.extend(_binding_problems(entry, value, root))
        clean = (
            value.get("campaign") == "clean"
            if entry["path"] == "harness"
            else len(value.get("attempts", [])) == 3 and not value.get("refusals")
        )
        if clean:
            flag = "--harness" if entry["path"] == "harness" else "--manager"
            target = source if entry["path"] == "harness" else directory
            check = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "render_act_campaign.py"),
                    flag,
                    str(target),
                    "--out",
                    str(directory / "campaign.md"),
                    "--check",
                ],
                cwd=root,
                capture_output=True,
                text=True,
            )
            if check.returncode != 0:
                problems.append(
                    f"{cid}: {check.stdout.strip() or check.stderr.strip()}"
                )
    return problems


def test_every_declared_campaign_is_retained_and_checks():
    raw = (ROOT / LEDGER).read_text(encoding="utf-8")
    entries = [json.loads(line) for line in raw.splitlines() if line.strip()]
    assert not entries_problems(entries, ROOT)


def test_the_ledger_is_append_only_across_its_history():
    """Each committed version is a byte prefix of the next. Deleting the line
    of a failed campaign is the edit this exists to catch."""

    commits = _git("log", "--reverse", "--format=%H", "--", LEDGER).split()
    versions = [_git("show", f"{commit}:{LEDGER}") for commit in commits]
    for earlier, later in zip(versions, versions[1:]):
        assert later.startswith(earlier), "a ledger line was removed or rewritten"
    assert (
        (ROOT / LEDGER)
        .read_text(encoding="utf-8")
        .startswith(versions[-1] if versions else "")
    )


def test_the_check_sees_an_unretained_campaign(tmp_path):
    entry = {
        "campaign_id": "2026-10-01-deck",
        "manifest_sha256": "0" * 64,
        "path": "harness",
        "plan_id": "build-investor-deck-v1",
    }
    assert entries_problems([entry], tmp_path) == [
        "2026-10-01-deck: declared but its results are not retained"
    ]
    assert entries_problems([entry, entry], tmp_path)[0] != ""
    assert any(
        "fields" in p for p in entries_problems([{"campaign_id": "x"}], tmp_path)
    )


def test_the_check_runs_the_renderer_on_a_clean_campaign(tmp_path):
    directory = tmp_path / "docs" / "evidence" / "campaigns" / "2026-10-01-deck"
    directory.mkdir(parents=True)
    (directory / "report.json").write_text(
        json.dumps({"binding": {"campaign_id": "2026-10-01-deck"}, "campaign": "clean",
                    "path": "harness", "schema_version": 2}),
        encoding="utf-8",
    )
    entry = {
        "campaign_id": "2026-10-01-deck",
        "manifest_sha256": "0" * 64,
        "path": "harness",
        "plan_id": "build-investor-deck-v1",
    }
    problems = entries_problems([entry], tmp_path)
    assert len(problems) == 1 and "refused" in problems[0]


def _entry(**overrides):
    value = {
        "campaign_id": "2026-10-01-deck",
        "manifest_sha256": "0" * 64,
        "path": "harness",
        "plan_id": "build-investor-deck-v1",
    }
    value.update(overrides)
    return value


def _retain(root, campaign_id, value, name="report.json"):
    directory = root / "docs" / "evidence" / "campaigns" / campaign_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(value), encoding="utf-8")


def test_an_empty_record_does_not_count_as_retaining_a_failed_campaign(tmp_path):
    _retain(tmp_path, "2026-10-01-deck", {})
    assert any("not a harness campaign record" in p for p in entries_problems([_entry()], tmp_path))


def test_another_campaigns_report_cannot_stand_in(tmp_path):
    _retain(tmp_path, "2026-10-01-deck", {
        "binding": {"campaign_id": "2026-10-01-other", "plan_id": "build-investor-deck-v1"},
        "campaign": "refused", "detail": "x", "path": "harness", "schema_version": 2,
    })
    assert any("names campaign" in p for p in entries_problems([_entry()], tmp_path))


def test_a_report_for_another_plan_or_manifest_is_refused(tmp_path):
    _retain(tmp_path, "2026-10-01-deck", {
        "binding": {"campaign_id": "2026-10-01-deck", "plan_id": "animation-catalog-v1",
                    "manifest_sha256": "f" * 64},
        "campaign": "refused", "detail": "x", "path": "harness", "schema_version": 2,
    })
    problems = entries_problems([_entry()], tmp_path)
    assert any("ran plan" in p for p in problems)
    assert any("another manifest" in p for p in problems)


def test_a_refused_campaign_must_say_why(tmp_path):
    _retain(tmp_path, "2026-10-01-deck", {
        "binding": {"campaign_id": "2026-10-01-deck"},
        "campaign": "refused", "detail": None, "path": "harness", "schema_version": 2,
    })
    assert any("must say why" in p for p in entries_problems([_entry()], tmp_path))


def test_the_commit_a_campaign_ran_at_must_already_declare_it():
    """HEAD~0's ledger is empty at this commit, so a report claiming to have
    run at it for an undeclared id is refused (runs against real history)."""

    head = _git("rev-parse", "HEAD").strip()
    assert not _commit_declares(ROOT, head, "2026-10-01-never-declared")
