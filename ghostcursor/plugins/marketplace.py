"""A browsable catalog of available plugin bundles (D144/D186, first-party
marketplace stage-7 MVP).

Read-only. It verifies each ``.ghostplugin`` in a directory with the SAME
``verify_bundle`` the store installs through, and reports what is installable:
plugin id, version, whether it is signed, whether it is compatible with this
core, its manifest digest, and the applications it targets. It installs
nothing and changes no verification -- install stays ``PluginStore.install``.

The ChatGPT/GPT-Store model informs the shape (a manifest per plugin, a digest
that re-verification is bound to, a catalog that lists them), done locally over
signed bundles instead of a hosted directory.

The D144 trust pieces are still gated and NOT changed here: publisher-key
identity in the manifest, a SIGNED revocation list, and re-sign provenance.
This slice adds only a local revocation DENYLIST check -- a set of revoked
manifest digests the catalog marks and refuses -- which can only refuse more,
never allow more. A cryptographically signed revocation list is the next
tier-1 step and needs its own review.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from ghostcursor.plugins.bundle import BundleVerificationError, verify_bundle


@dataclass(frozen=True)
class CatalogEntry:
    plugin_id: str
    version: str
    manifest_sha256: str
    signed: bool
    compatible: bool
    applications: tuple[str, ...]
    revoked: bool
    error: str  # "" when the bundle verified

    def as_line(self) -> str:
        if self.error:
            return f"{self.plugin_id}  —  UNREADABLE: {self.error}"
        flags = [
            "signed" if self.signed else "UNSIGNED",
            "compatible" if self.compatible else "INCOMPATIBLE",
        ]
        if self.revoked:
            flags.append("REVOKED")
        apps = ", ".join(self.applications) or "no apps"
        return (
            f"{self.plugin_id} {self.version}  [{', '.join(flags)}]  "
            f"{apps}  ({self.manifest_sha256[:12]})"
        )


def _applications(manifest: Mapping) -> tuple[str, ...]:
    apps = manifest.get("applications")
    if not isinstance(apps, list):
        return ()
    out = []
    for app in apps:
        if isinstance(app, dict) and "value" in app:
            out.append(str(app["value"]))
    return tuple(out)


def catalog(
    directory,
    *,
    trusted_keys: Mapping[str, bytes],
    core_version: str,
    revoked: Iterable[str] = (),
) -> list[CatalogEntry]:
    """Verify every ``.ghostplugin`` in ``directory`` (read-only) and return a
    catalog entry per bundle, sorted by id then version. A bundle that fails
    verification is listed with its error, not silently dropped."""

    directory = Path(directory)
    revoked_set = set(revoked)
    entries: list[CatalogEntry] = []
    for path in sorted(directory.glob("*.ghostplugin")):
        try:
            bundle = verify_bundle(
                path,
                trusted_keys=trusted_keys,
                core_version=core_version,
                require_compatible=False,
            )
        except BundleVerificationError as exc:
            entries.append(
                CatalogEntry(path.stem, "", "", False, False, (), False, str(exc))
            )
            continue
        entries.append(
            CatalogEntry(
                plugin_id=bundle.plugin_id,
                version=bundle.version,
                manifest_sha256=bundle.manifest_sha256,
                signed=bundle.signed,
                compatible=bundle.compatibility.compatible,
                applications=_applications(bundle.manifest),
                revoked=bundle.manifest_sha256 in revoked_set,
                error="",
            )
        )
    entries.sort(key=lambda e: (e.plugin_id, e.version))
    return entries
