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
        --campaign-id <declared id> --attempt 1
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

#: Each signed object-model plan and the one intent it answers. The checker
#: requires every attempt's proposal to carry this intent (D152, review I1).
PLAN_INTENTS = {
    "build-investor-deck-v1": "BUILD_INVESTOR_DECK",
    "animation-catalog-v1": "BUILD_ANIMATION_CATALOG",
}
GOALS = {
    "build-investor-deck-v1": "build the ghostcursor investor deck in powerpoint",
    "animation-catalog-v1": "build the animation catalog in powerpoint",
}
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
    plan_id: str = PLAN_ID,
    campaign_id: str | None = None,
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
        "campaign_id": campaign_id,
        "intent_id": PLAN_INTENTS[plan_id],
        "plan_id": plan_id,
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
                "refusals": [],
                "schema_version": 1,
            },
        )
    campaign = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        campaign.get("binding") == {"campaign_id": campaign_id}
        and not campaign.get("attempts")
        and attempt == 1
    ):
        # Only a refusal before attempt 1 was retained (record_refusal): the
        # cause is fixed and attempt 1 binds the campaign now, keeping the
        # refusals. Without this the pinned campaign id could never start.
        campaign["binding"] = binding
        _write(manifest_path, campaign)
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


def record_refusal(campaign_dir: Path, campaign_id: str, detail: str) -> None:
    """Retain a refusal that happened after the campaign was declared.

    A committed ledger line demands retained results, so a refusal before the
    first attempt -- an unpinned manifest, a dirty tree, a wrong attempt
    number -- is written down rather than printed and lost (D154, review B1).
    """

    campaign_dir.mkdir(parents=True, exist_ok=True)
    path = campaign_dir / CAMPAIGN_FILE
    if path.exists():
        campaign = json.loads(path.read_text(encoding="utf-8"))
    else:
        campaign = {
            "attempts": [],
            "binding": {"campaign_id": campaign_id},
            "path": "manager",
            "refusals": [],
            "schema_version": 1,
        }
    campaign.setdefault("refusals", []).append(detail)
    _write(path, campaign)


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
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--plan-id", choices=sorted(PLAN_INTENTS), default=PLAN_ID)
    arguments = parser.parse_args(argv)

    from ghostcursor.devtools.campaign_pins import (
        campaign_directory,
        require_ledgered,
    )
    from ghostcursor.plugins.platform import production_store

    # Nothing is written before the ledger check passes.
    try:
        campaign_dir = campaign_directory(arguments.campaign_id)
        require_ledgered(
            arguments.campaign_id, path="manager", plan_id=arguments.plan_id
        )
    except CampaignPreflightError as exc:
        print(f"refusing: {exc}")
        return 2

    try:
        store = production_store()
        manifest = installed_manifest_sha256(store)
        plan = (
            store.load_composition_context()
            .adapters[POWERPOINT_PLUGIN_ID]
            .plans[arguments.plan_id]
        )
        transcript = prepare_attempt(
            campaign_dir,
            arguments.attempt,
            environment=os.environ,
            commit=repository_commit(),
            manifest_sha256=manifest,
            plan_sha256=plan.plan_sha256,
            plan_id=arguments.plan_id,
            campaign_id=arguments.campaign_id,
        )
    except Exception as exc:
        record_refusal(
            campaign_dir, arguments.campaign_id, f"attempt {arguments.attempt}: {exc}"
        )
        print(f"refusing: {exc}")
        return 2

    from ghostcursor.manager import launch_manager

    print(f"attempt {arguments.attempt}: transcript -> {transcript}")
    print(f"Goal:  {GOALS[arguments.plan_id]}")
    print("Mode:  Act. Review the complete plan, then press Approve & run once.")
    print("Close the manager only after the terminal result is visible.")
    code = 1
    try:
        code = launch_manager(act_audit_path=transcript)
    finally:
        # A manager that crashed still ran an attempt; it is recorded.
        record_attempt(campaign_dir, arguments.attempt, code)
    return code

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["prepare_attempt", "record_attempt", "record_refusal", "transcript_name"]
