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

#: The PowerPoint manifest the tracking documents name (D151).
POWERPOINT_MANIFEST_SHA256 = (
    "6dbd5ba2585fbf9287abe5753270407be1253f3660047fbc435694864421cd53"
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
    "installed_manifest_sha256",
    "repository_commit",
    "require_pinned_manifest",
]
