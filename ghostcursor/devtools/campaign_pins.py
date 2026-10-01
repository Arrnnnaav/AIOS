"""What a counted campaign must be bound to, checked before the first attempt.

A campaign run on bytes nobody pinned produces evidence nobody can cite: the
D149 review found that neither campaign path compared the manifest it loaded
with the manifest the documents name, so a run on a stale or foreign bundle
would have read exactly like a run on the reviewed one.

``POWERPOINT_MANIFEST_SHA256`` is the one pin both campaign paths refuse
without. ``tests/test_powerpoint_manifest_pin.py`` recomputes the manifest from
tracked sources and requires its ``DOCUMENTED`` value to equal this constant,
so the pin cannot move in one place and not the other.

Diagnostic tooling only; nothing here grants or checks execution authority.
"""

from __future__ import annotations

import hashlib
import subprocess
import zipfile
from pathlib import Path

#: The PowerPoint manifest the tracking documents name (D152).
POWERPOINT_MANIFEST_SHA256 = (
    "b0d63512d1bcc14bc49f322139613018fc31483f7a7b49007ce0532e35082b4e"
)
POWERPOINT_PLUGIN_ID = "ghostcursor.powerpoint"

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class CampaignPreflightError(RuntimeError):
    """A campaign that must not start."""


def bundle_manifest_sha256(bundle: Path) -> str:
    """The digest of a bundle's canonical manifest bytes, as signed."""

    with zipfile.ZipFile(bundle) as archive:
        return hashlib.sha256(archive.read("plugin.json")).hexdigest()


def require_pinned_manifest(manifest_sha256: str) -> None:
    if manifest_sha256 != POWERPOINT_MANIFEST_SHA256:
        raise CampaignPreflightError(
            f"manifest {manifest_sha256[:8]} is not the pinned "
            f"{POWERPOINT_MANIFEST_SHA256[:8]}; a campaign on unpinned bytes "
            "cannot be cited"
        )


def installed_manifest_sha256(store) -> str:
    """The manifest of the active PowerPoint bundle in ``store``."""

    context = store.load_composition_context()
    adapter = context.adapters.get(POWERPOINT_PLUGIN_ID)
    if adapter is None:
        raise CampaignPreflightError("the PowerPoint plugin is not active")
    return adapter.manifest_sha256


def repository_commit(root: Path = REPOSITORY_ROOT) -> str:
    """HEAD of a clean work tree, or a refusal.

    A campaign run on uncommitted changes names a commit whose bytes are not
    the ones that ran, so a dirty tree refuses rather than recording a false
    binding.
    """

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise CampaignPreflightError(
                f"git {args[0]} failed: {result.stderr.strip()}"
            )
        return result.stdout

    dirty = git("status", "--porcelain", "--untracked-files=no").strip()
    if dirty:
        raise CampaignPreflightError(
            "the work tree has uncommitted tracked changes; commit before a "
            "counted campaign so the recorded commit is the code that ran"
        )
    return git("rev-parse", "HEAD").strip()


__all__ = [
    "CampaignPreflightError",
    "POWERPOINT_MANIFEST_SHA256",
    "POWERPOINT_PLUGIN_ID",
    "bundle_manifest_sha256",
    "hold_commits",
    "release_commits",
    "installed_manifest_sha256",
    "repository_commit",
    "require_pinned_manifest",
]


#: Every counted campaign is declared here, in a COMMITTED line, before its
#: first attempt runs. `tests/test_campaign_ledger.py` requires every declared
#: campaign to have its results retained, so running until a campaign passes
#: and keeping only that one becomes visible (D152).
LEDGER_RELATIVE = "docs/campaigns/ledger.jsonl"
CAMPAIGN_ID_PATTERN = r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]{1,40}"


def campaign_directory(campaign_id: str, root: Path = REPOSITORY_ROOT) -> Path:
    import re

    if not re.fullmatch(CAMPAIGN_ID_PATTERN, campaign_id):
        raise CampaignPreflightError(f"campaign id {campaign_id!r} is malformed")
    return root / "docs" / "evidence" / "campaigns" / campaign_id


def require_ledgered(
    campaign_id: str, *, path: str, plan_id: str, root: Path = REPOSITORY_ROOT
) -> dict:
    """The committed ledger entry for this campaign, or a refusal.

    Read from HEAD, not the working copy: an entry that exists only on disk
    could be deleted after a failed campaign, which is the case this exists
    to expose.
    """

    import json

    campaign_directory(campaign_id, root)
    shown = subprocess.run(
        ["git", "show", f"HEAD:{LEDGER_RELATIVE}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if shown.returncode != 0:
        raise CampaignPreflightError("the campaign ledger is not committed")
    entries = [json.loads(line) for line in shown.stdout.splitlines() if line.strip()]
    matches = [e for e in entries if e.get("campaign_id") == campaign_id]
    if len(matches) != 1:
        raise CampaignPreflightError(
            f"campaign {campaign_id} is not declared exactly once in the committed "
            f"ledger; append it to {LEDGER_RELATIVE} and commit before attempt 1"
        )
    entry = matches[0]
    expected = {
        "path": path,
        "plan_id": plan_id,
        "manifest_sha256": POWERPOINT_MANIFEST_SHA256,
    }
    if any(entry.get(key) != value for key, value in expected.items()):
        raise CampaignPreflightError(
            "the ledger entry declares a different path, plan or manifest"
        )
    hold_commits(campaign_id, root)
    return entry


#: While this file exists a campaign is open and nothing may be committed
#: (D163): the recorded commit must be the code that ran every attempt. The
#: project's PreToolUse hook refuses `git commit` while it exists; rendering
#: the campaign document, the last step of every campaign, removes it.
COMMIT_LOCK_RELATIVE = ".artifacts/campaign.lock"


def hold_commits(campaign_id: str, root: Path = REPOSITORY_ROOT) -> None:
    lock = root / COMMIT_LOCK_RELATIVE
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes((campaign_id + "\n").encode("utf-8"))


def release_commits(root: Path = REPOSITORY_ROOT) -> None:
    (root / COMMIT_LOCK_RELATIVE).unlink(missing_ok=True)
