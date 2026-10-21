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

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Mapping

from ghostcursor.plugins.bundle import (
    _SEMVER_RE,
    BundleVerificationError,
    verify_bundle,
)


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
    signing_key_id: str = ""
    is_latest: bool = False  # highest semver for this plugin_id in the catalog

    def as_line(self) -> str:
        if self.error:
            return f"{self.plugin_id}  —  UNREADABLE: {self.error}"
        flags = [
            "signed" if self.signed else "UNSIGNED",
            "compatible" if self.compatible else "INCOMPATIBLE",
        ]
        if self.is_latest:
            flags.append("latest")
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
                signing_key_id=str(bundle.manifest.get("signing_key_id") or ""),
            )
        )
    entries.sort(key=lambda e: (e.plugin_id, e.version))
    return _mark_latest(entries)


def _semver_key(version: str) -> tuple[int, int, int]:
    """(major, minor, patch) for comparison; (-1,-1,-1) if not plain semver."""

    m = _SEMVER_RE.fullmatch(version or "")
    return (int(m[1]), int(m[2]), int(m[3])) if m else (-1, -1, -1)


def _mark_latest(entries: list[CatalogEntry]) -> list[CatalogEntry]:
    """Flag the highest-semver verified entry per plugin_id as is_latest
    (MCP's latest rule). Error/unversioned rows never win."""

    best: dict[str, tuple[int, int, int]] = {}
    for e in entries:
        if e.error:
            continue
        key = _semver_key(e.version)
        if key > best.get(e.plugin_id, (-2, -2, -2)):
            best[e.plugin_id] = key
    out = []
    for e in entries:
        latest = (not e.error) and _semver_key(e.version) == best.get(e.plugin_id)
        out.append(replace(e, is_latest=latest))
    return out


def updates_available(
    entries: Iterable[CatalogEntry], installed: Mapping[str, str]
) -> list[tuple[str, str, str]]:
    """(plugin_id, installed_version, latest_version) for each installed plugin
    the catalog has a strictly-higher semver for. Pure local compare."""

    latest: dict[str, str] = {}
    for e in entries:
        if not e.error and e.is_latest:
            latest[e.plugin_id] = e.version
    out = []
    for plugin_id, have in installed.items():
        newest = latest.get(plugin_id)
        if newest and _semver_key(newest) > _semver_key(have):
            out.append((plugin_id, have, newest))
    return sorted(out)


def search(
    entries: Iterable[CatalogEntry],
    query: str,
    *,
    presentation: Mapping[str, Mapping] | None = None,
) -> list[CatalogEntry]:
    """Entries whose id, applications, signing key, or presentation text
    (display_name/summary/keywords/publisher, keyed by digest) match ``query``
    as a case-insensitive substring. Local only; no network."""

    q = " ".join(str(query).split()).casefold()
    if not q:
        return list(entries)
    presentation = presentation or {}
    hits = []
    for e in entries:
        hay = [e.plugin_id, e.signing_key_id, *e.applications]
        p = presentation.get(e.manifest_sha256, {})
        hay += [
            str(p.get("display_name", "")),
            str(p.get("summary", "")),
            str(p.get("publisher", "")),
            str(p.get("category", "")),
            " ".join(str(k) for k in p.get("keywords", []) if isinstance(k, str)),
        ]
        if any(q in str(h).casefold() for h in hay):
            hits.append(e)
    return hits


def sort_entries(entries: Iterable[CatalogEntry], by: str = "id") -> list[CatalogEntry]:
    """Sort a catalog like Open VSX's sortBy: 'id' (alpha), 'version' (semver,
    high first), or 'latest' (is_latest first, then id). Stable, pure."""

    items = list(entries)
    if by == "version":
        return sorted(items, key=lambda e: _semver_key(e.version), reverse=True)
    if by == "latest":
        return sorted(items, key=lambda e: (not e.is_latest, e.plugin_id, e.version))
    return sorted(items, key=lambda e: (e.plugin_id, e.version))


def filter_entries(
    entries: Iterable[CatalogEntry],
    *,
    signed: bool | None = None,
    compatible: bool | None = None,
    latest: bool | None = None,
    app: str | None = None,
) -> list[CatalogEntry]:
    """Keep catalog entries matching every supplied constraint (Open VSX's
    category/filter intent, over the facts we already verify). ``app`` matches
    a targeted application case-insensitively. Error rows are dropped."""

    app_l = app.casefold() if app else None
    out = []
    for e in entries:
        if e.error:
            continue
        if signed is not None and e.signed != signed:
            continue
        if compatible is not None and e.compatible != compatible:
            continue
        if latest is not None and e.is_latest != latest:
            continue
        if app_l is not None and not any(app_l in a.casefold() for a in e.applications):
            continue
        out.append(e)
    return out


def build_index(
    entries: Iterable[CatalogEntry],
    *,
    presentation: Mapping[str, Mapping] | None = None,
    revoked_digests: Iterable[str] = (),
    generated_at: str | None = None,
) -> dict:
    """A read-only catalog ``index.json`` (MCP-style trusted/untrusted split):
    author presentation text is untrusted display; the ``verified`` block is the
    facts this run recomputed with verify_bundle. Keyed by manifest_sha256 so
    the catalog text can never point at a different bundle than the one
    verified. Carries no ratings/counts (those would need egress)."""

    import time

    presentation = presentation or {}
    out_entries = []
    for e in entries:
        if e.error:
            continue
        p = presentation.get(e.manifest_sha256, {})
        out_entries.append(
            {
                "plugin_id": e.plugin_id,
                "version": e.version,
                "manifest_sha256": e.manifest_sha256,
                "publisher_provided": {
                    k: p[k]
                    for k in (
                        "display_name",
                        "summary",
                        "publisher",
                        "homepage",
                        "keywords",
                        "category",
                    )
                    if k in p
                },
                "verified": {
                    "signed": e.signed,
                    "signing_key_id": e.signing_key_id,
                    "compatible": e.compatible,
                    "applications": list(e.applications),
                    "is_latest": e.is_latest,
                    "status": "revoked" if e.revoked else "active",
                },
            }
        )
    return {
        "index_schema_version": 1,
        "generated_at": generated_at
        or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "entries": out_entries,
        "revoked_digests": sorted(set(revoked_digests)),
    }
