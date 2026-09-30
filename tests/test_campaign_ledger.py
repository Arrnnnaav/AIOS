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
        clean = (
            json.loads(source.read_text(encoding="utf-8")).get("campaign") == "clean"
            if entry["path"] == "harness"
            else len(json.loads(source.read_text(encoding="utf-8")).get("attempts", []))
            == 3
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
        json.dumps({"campaign": "clean"}), encoding="utf-8"
    )
    entry = {
        "campaign_id": "2026-10-01-deck",
        "manifest_sha256": "0" * 64,
        "path": "harness",
        "plan_id": "build-investor-deck-v1",
    }
    problems = entries_problems([entry], tmp_path)
    assert len(problems) == 1 and "refused" in problems[0]
