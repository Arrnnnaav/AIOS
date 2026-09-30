"""Run ONE attempt of a counted manager-path Act campaign.

The manager path is the one the harness campaign never crosses: the real
`Approve & run` command, the D123 foreground handoff and the one-use
`ActExecutionRequest` (D121). A human presses `Approve & run`; nothing here
proposes, approves, dispatches or verifies. `launch_manager` receives only the
documented observation-only audit path (D122).

Replaces the frozen `docs/evidence/diagnostic/manager_campaign_harness.py`,
which hard-coded the repository path (so it ran whatever the main checkout
held, not the reviewed commit), checked no manifest, and counted nothing
(D150). This one refuses before the manager opens unless:

- one campaign scope and salt are exported for every attempt (D133);
- the installed PowerPoint manifest is the pinned one;
- the work tree is clean, so the recorded commit is the code that runs;
- this attempt is the next consecutive one, and every earlier attempt in the
  campaign ended `completed` -- the first unclean attempt ends the campaign;
- neither this attempt's transcript nor any later one already exists.

The campaign directory holds `campaign.json` (the binding and the attempt
list) and one transcript per attempt. `tools/render_act_campaign.py --check`
reads them; this module never summarises a result itself.

    py -3.12 -m ghostcursor.devtools.act_manager_campaign \\
        --campaign-dir <dir> --attempt 1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from ghostcursor.devtools.campaign_pins import (
    POWERPOINT_PLUGIN_ID,
    CampaignPreflightError,
    installed_manifest_sha256,
    repository_commit,
    require_pinned_manifest,
)

PLAN_ID = "build-investor-deck-v1"
CAMPAIGN_FILE = "campaign.json"
SCOPE_VARIABLE = "GHOSTCURSOR_CAMPAIGN_SCOPE"
SALT_VARIABLE = "GHOSTCURSOR_CAMPAIGN_SALT"


def transcript_name(attempt: int) -> str:
    return f"act-live-manager-campaign-attempt-{attempt}.jsonl"


def _write(path: Path, value: dict) -> None:
    path.write_bytes(
        (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )


def _last_result(transcript: Path) -> dict | None:
    results = [
        record
        for record in (
            json.loads(line)
            for line in transcript.read_text(encoding="utf-8").splitlines()
            if line
        )
        if record.get("type") == "act_run_result"
    ]
    return results[-1] if len(results) == 1 else None


def prepare_attempt(
    campaign_dir: Path,
    attempt: int,
    *,
    environment,
    commit: str,
    manifest_sha256: str,
    plan_sha256: str,
) -> Path:
    """Validate the campaign state for ``attempt`` and return its transcript path.

    Pure over its inputs apart from reading and writing ``campaign_dir``, so it
    is tested hermetically; `main` supplies the live preflight values.
    """

    scope = environment.get(SCOPE_VARIABLE)
    if not scope or not environment.get(SALT_VARIABLE):
        raise CampaignPreflightError(
            f"{SCOPE_VARIABLE} and {SALT_VARIABLE} must both be exported, once, "
            "for every attempt of the campaign"
        )
    require_pinned_manifest(manifest_sha256)
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise CampaignPreflightError("attempt must be a positive integer")

    campaign_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = campaign_dir / CAMPAIGN_FILE
    binding = {
        "commit": commit,
        "manifest_sha256": manifest_sha256,
        "plan_id": PLAN_ID,
        "plan_sha256": plan_sha256,
        "scope": scope,
    }
    if not manifest_path.exists():
        if attempt != 1:
            raise CampaignPreflightError("a campaign starts at attempt 1")
        _write(
            manifest_path,
            {
                "attempts": [],
                "binding": binding,
                "path": "manager",
                "schema_version": 1,
            },
        )
    campaign = json.loads(manifest_path.read_text(encoding="utf-8"))
    if campaign.get("binding") != binding:
        raise CampaignPreflightError(
            "this attempt's commit, manifest, plan or scope differs from the "
            "campaign's; start a new campaign directory"
        )
    recorded = campaign.get("attempts", [])
    if attempt != len(recorded) + 1:
        raise CampaignPreflightError(
            f"attempt {attempt} is not the next consecutive attempt "
            f"({len(recorded) + 1}); attempts are never skipped or repeated"
        )
    for entry in recorded:
        result = _last_result(campaign_dir / entry["transcript"])
        if result is None or result.get("completed") is not True:
            raise CampaignPreflightError(
                f"attempt {entry['index']} did not complete; the campaign ended "
                "there and is not continued"
            )
    for later in range(attempt, attempt + 64):
        if (campaign_dir / transcript_name(later)).exists():
            raise CampaignPreflightError(
                f"{transcript_name(later)} already exists; never overwrite a run"
            )
    return campaign_dir / transcript_name(attempt)


def record_attempt(campaign_dir: Path, attempt: int, exit_code: int) -> None:
    """Append this attempt to the campaign, including a run that failed."""

    manifest_path = campaign_dir / CAMPAIGN_FILE
    campaign = json.loads(manifest_path.read_text(encoding="utf-8"))
    transcript = campaign_dir / transcript_name(attempt)
    campaign["attempts"].append(
        {
            "index": attempt,
            "manager_exit": exit_code,
            "transcript": transcript.name,
            "transcript_sha256": (
                hashlib.sha256(transcript.read_bytes()).hexdigest()
                if transcript.exists()
                else None
            ),
        }
    )
    _write(manifest_path, campaign)


def main(argv=None) -> int:  # pragma: no cover - thin live wrapper
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--attempt", type=int, required=True)
    arguments = parser.parse_args(argv)

    from ghostcursor.plugins.platform import production_store

    campaign_dir = arguments.campaign_dir.resolve()
    try:
        store = production_store()
        manifest = installed_manifest_sha256(store)
        plan = (
            store.load_composition_context()
            .adapters[POWERPOINT_PLUGIN_ID]
            .plans[PLAN_ID]
        )
        transcript = prepare_attempt(
            campaign_dir,
            arguments.attempt,
            environment=os.environ,
            commit=repository_commit(),
            manifest_sha256=manifest,
            plan_sha256=plan.plan_sha256,
        )
    except (CampaignPreflightError, KeyError, OSError) as exc:
        print(f"refusing: {exc}")
        return 2

    from ghostcursor.manager import launch_manager

    print(f"attempt {arguments.attempt}: transcript -> {transcript}")
    print("Goal:  build the ghostcursor investor deck in powerpoint")
    print("Mode:  Act. Review the complete plan, then press Approve & run once.")
    print("Close the manager only after the terminal result is visible.")
    code = launch_manager(act_audit_path=transcript)
    record_attempt(campaign_dir, arguments.attempt, code)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["prepare_attempt", "record_attempt", "transcript_name"]
