"""Production configuration for the local GhostCursor plugin platform."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

from ghostcursor.memory.store import default_db_path
from ghostcursor.plugins.store import PluginStore, PluginStoreError
from ghostcursor.plugins.trust import load_trust_policy


CORE_VERSION = "1.0.0"
ENV_PLUGIN_ROOT = "GHOSTCURSOR_PLUGIN_ROOT"
_MODULE_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _MODULE_ROOT.parent.parent
_TRUST_PATH = _MODULE_ROOT / "trusted_keys.json"
_BUNDLED_ROOT = _REPO_ROOT / "plugins" / "bundled"
#: Optional root-signed trust policy. When this directory exists it MUST hold a
#: pinned root key and a valid, root-signed key manifest + revocation list; the
#: revocation list's revoked bundle digests then feed PluginStore.revoked_digests.
#: Absent = not configured (flat trusted_keys.json stays the key source, no
#: bundle revocations). Present-but-invalid = fail closed (raise), never a
#: silent fall-back that would un-revoke a bundle. (D186 Bucket-2 wiring.)
_TRUST_POLICY_DIR = _MODULE_ROOT / "trust"


def default_plugin_root() -> Path:
    override = os.environ.get(ENV_PLUGIN_ROOT)
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "GhostCursor" / "plugins"


def trusted_release_keys() -> Mapping[str, bytes]:
    value = json.loads(_TRUST_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not value:
        raise PluginStoreError("trusted release key file is invalid")
    try:
        return {
            key_id: base64.b64decode(encoded, validate=True)
            for key_id, encoded in value.items()
        }
    except (TypeError, ValueError) as exc:
        raise PluginStoreError("trusted release key file is invalid") from exc


def _bundled_index() -> tuple[dict, ...]:
    value = json.loads((_BUNDLED_ROOT / "index.json").read_text(encoding="utf-8"))
    if set(value) != {"schema_version", "bundles"} or value["schema_version"] != 1:
        raise PluginStoreError("bundled plugin index is invalid")
    bundles = value["bundles"]
    if not isinstance(bundles, list):
        raise PluginStoreError("bundled plugin index is invalid")
    return tuple(bundles)


def _bootstrap(store: PluginStore) -> None:
    """Install defaults once; an existing empty index is an operator choice."""

    if (store.root / "installed.json").exists():
        return
    for entry in _bundled_index():
        required = {
            "bundle_sha256",
            "enable_on_first_run",
            "manifest_sha256",
            "path",
            "plugin_id",
            "version",
        }
        if not isinstance(entry, dict) or set(entry) != required:
            raise PluginStoreError("bundled plugin entry is invalid")
        path = _BUNDLED_ROOT / entry["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["bundle_sha256"]:
            raise PluginStoreError(f"bundled plugin bytes changed: {entry['path']}")
        installed = store.install(path)
        if (
            installed.plugin_id != entry["plugin_id"]
            or installed.version != entry["version"]
            or installed.manifest_sha256 != entry["manifest_sha256"]
        ):
            raise PluginStoreError("bundled plugin identity disagrees with index")
        if entry["enable_on_first_run"]:
            store.enable(installed.plugin_id, installed.version)


def _read_sequence_floor(path: Path) -> tuple[int, int]:
    """The highest (key_manifest, revocation) sequences accepted so far, or
    (0, 0) if there is no usable record. A missing or malformed floor file is
    treated as no floor -- the root SIGNATURE still proves authenticity; the
    floor only adds rollback protection, and corrupting it cannot admit an
    unsigned document, only lose rollback protection (which local FS integrity
    is the OS's job to provide)."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        km, rev = value["key_manifest"], value["revocations"]
    except (OSError, ValueError, KeyError, TypeError):
        return (0, 0)
    if type(km) is not int or type(rev) is not int or km < 0 or rev < 0:
        return (0, 0)
    return (km, rev)


def signed_revoked_digests(
    trust_dir: Path | None = None, *, floor_path: Path | None = None
) -> frozenset[str]:
    """Revoked bundle digests from a root-signed revocation policy.

    If ``trust_dir`` (default ``_TRUST_POLICY_DIR``) does not exist, the policy
    is simply not configured and no bundle is revoked (empty set). If it DOES
    exist it must contain ``root.b64`` and a valid, root-signed ``key-manifest
    .json``/``.sig`` and ``revocations.json``/``.sig``; anything missing or not
    verifying raises (fail closed) rather than silently returning an empty set,
    which would un-revoke every bundle. Verification is `load_trust_policy`.

    Anti-rollback: the highest accepted document sequences are persisted to
    ``floor_path`` and passed back as the floor, so a validly-signed but OLDER
    revocation list (which could drop a revocation) is refused across restarts,
    not just within one process.
    """

    trust_dir = trust_dir or _TRUST_POLICY_DIR
    if not trust_dir.exists():
        return frozenset()
    floor_path = floor_path or (default_plugin_root() / "trust-floor.json")
    km_floor, rev_floor = _read_sequence_floor(floor_path)
    try:
        root = base64.b64decode(
            (trust_dir / "root.b64").read_text(encoding="utf-8").strip(), validate=True
        )
    except (OSError, ValueError) as exc:
        raise PluginStoreError(
            "trust policy is configured but its root key is unreadable"
        ) from exc
    policy = load_trust_policy(
        key_manifest_bytes=(trust_dir / "key-manifest.json").read_bytes(),
        key_manifest_signature=(trust_dir / "key-manifest.sig").read_bytes(),
        revocations_bytes=(trust_dir / "revocations.json").read_bytes(),
        revocations_signature=(trust_dir / "revocations.sig").read_bytes(),
        root_public_key=root,
        key_manifest_floor=km_floor,
        revocations_floor=rev_floor,
    )
    # Raise the floor to what we just accepted (monotonic; never lower it).
    new_floor = {
        "key_manifest": max(km_floor, policy.key_manifest_sequence),
        "revocations": max(rev_floor, policy.revocations_sequence),
    }
    if (new_floor["key_manifest"], new_floor["revocations"]) != (km_floor, rev_floor):
        try:
            floor_path.parent.mkdir(parents=True, exist_ok=True)
            floor_path.write_text(
                json.dumps(new_floor, separators=(",", ":")), encoding="utf-8"
            )
        except OSError:
            pass  # a read-only FS loses rollback persistence, not authenticity
    return policy.revoked_bundle_digests


def production_store(*, bootstrap: bool = True) -> PluginStore:
    store = PluginStore(
        default_plugin_root(),
        trusted_keys=trusted_release_keys(),
        core_version=CORE_VERSION,
        observation_store_path=default_db_path(),
        revoked_digests=signed_revoked_digests(),
    )
    if bootstrap:
        _bootstrap(store)
    return store


def developer_store() -> PluginStore:
    """Explicit unsigned-development store; never bootstraps production data."""

    return PluginStore(
        default_plugin_root(),
        trusted_keys=trusted_release_keys(),
        core_version=CORE_VERSION,
        developer_mode=True,
        observation_store_path=default_db_path(),
    )


def load_runtime_catalog():
    """Load current enabled authority; no enabled plugins means no intents."""

    return production_store().load_verified_catalog()


def load_composition_context():
    """Load executable catalog and signed capabilities from one store epoch."""

    return production_store().load_composition_context()


def runtime_authority_status(workflow) -> str | None:
    """Return why a running workflow lost authority, or ``None``.

    This is deliberately read-only and narrower than catalog loading. The
    workflow already passed signed-payload, compatibility, adoption, identity,
    and live-HWND revalidation before an overlay existed. During execution the
    active-index digest is the lifecycle epoch: enable, disable, and upgrade
    all publish a different index before they affect a subsequent launch.
    """

    try:
        current = production_store(bootstrap=False).current_active_index_sha256()
    except (OSError, PluginStoreError, ValueError) as exc:
        return f"active plugin authority is unavailable: {type(exc).__name__}"
    if current != workflow.index_sha256:
        return "active plugin authority changed during the tour"
    return None
