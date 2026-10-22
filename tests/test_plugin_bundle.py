from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ghostcursor.plugins.bundle import BundleVerificationError, verify_bundle
from ghostcursor.plugins.compatibility import check_core_compatibility
from ghostcursor.action import OPERATION_ARTIFACT_PATH
from ghostcursor.action_plans import ACTION_PLAN_INDEX_PATH
from ghostcursor.task_graph import CAPABILITY_ARTIFACT_PATH


CORE_VERSION = "0.1.0"


def _keys():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private, {"release-1": public}


def _manifest(files: dict[str, bytes], **changes):
    value = {
        "schema_version": 1,
        "plugin_id": "ghostcursor.test",
        "version": "1.0.0",
        "plugin_api_version": 1,
        "core_compatibility": {
            "minimum": "0.1.0",
            "maximum_exclusive": "1.0.0",
        },
        "applications": [{"kind": "executable", "value": "Test.exe"}],
        "signing_key_id": "release-1",
        "adapter_api": None,
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
    }
    value.update(changes)
    return value


def _write_bundle(tmp_path: Path, *, manifest=None, files=None, sign=True, extras=None):
    files = files or {
        "ghostcursor/packs/index.json": b'{"packs":[],"schema_version":2}\n'
    }
    manifest = manifest or _manifest(files)
    raw_manifest = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    private, trusted = _keys()
    path = tmp_path / "test.ghostplugin"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("plugin.json", raw_manifest)
        for name, raw in files.items():
            archive.writestr(name, raw)
        if sign:
            archive.writestr("signature.ed25519", private.sign(raw_manifest))
        for name, raw in extras or []:
            archive.writestr(name, raw)
    return path, trusted


def _v2_files(*, adapter: bytes | None = None, operations: bytes | None = None):
    adapter = adapter or b"print('signed adapter')\n"
    adapter_sha = hashlib.sha256(adapter).hexdigest()
    operation_value = {
        "operations": {
            "test.create": {
                "effect_key_fields": ["name"],
                "parameters": {
                    "name": {
                        "allowed_values": [],
                        "kind": "string",
                        "required": True,
                    }
                },
                "postconditions": ["document.created"],
                "preconditions": [],
                "risk": "low",
                "safe_to_repeat": False,
                "timeout_s": 5,
            }
        },
        "plugin_id": "ghostcursor.test",
        "plugin_version": "1.0.0",
        "schema_version": 1,
    }
    operations = (
        operations
        or json.dumps(operation_value, sort_keys=True, separators=(",", ":")).encode()
    )
    plan_path = "ghostcursor/action-plans/create-test.json"
    plan = json.dumps(
        {
            "edges": [],
            "nodes": [
                {
                    "node_id": "create",
                    "operation_id": "test.create",
                    "parameters": {"name": {"$parameter": "name"}},
                }
            ],
            "plan_id": "create-test",
            "schema_version": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    plans = json.dumps(
        {
            "plans": {
                "create-test": {
                    "intent_id": "CREATE_TEST",
                    "parameters": {"name": {"kind": "string", "required": True}},
                    "path": plan_path,
                    "sha256": hashlib.sha256(plan).hexdigest(),
                }
            },
            "plugin_id": "ghostcursor.test",
            "plugin_version": "1.0.0",
            "schema_version": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        "ghostcursor/packs/index.json": b'{"packs":[],"schema_version":2}',
        "ghostcursor/adapter/test_adapter.py": adapter,
        "ghostcursor/adapter/test_verifier.py": b"print('signed verifier')\n",
        ACTION_PLAN_INDEX_PATH: plans,
        plan_path: plan,
        OPERATION_ARTIFACT_PATH: operations,
    }, adapter_sha


def _v2_manifest(files):
    return _manifest(
        files,
        plugin_api_version=2,
        adapter_api={
            "entrypoint": "ghostcursor/adapter/test_adapter.py",
            "operations": OPERATION_ARTIFACT_PATH,
            "plans": ACTION_PLAN_INDEX_PATH,
            "protocol_version": 1,
            "verifier": "ghostcursor/adapter/test_verifier.py",
        },
    )


def test_compatibility_is_a_half_open_semantic_version_range():
    manifest = _manifest({"ghostcursor/packs/index.json": b"{}"})
    assert check_core_compatibility(manifest, "0.1.0").compatible
    assert check_core_compatibility(manifest, "0.9.9").compatible
    assert not check_core_compatibility(manifest, "1.0.0").compatible


def test_a_signed_bundle_binds_the_exact_manifest_and_every_file(tmp_path):
    path, trusted = _write_bundle(tmp_path)
    bundle = verify_bundle(path, trusted_keys=trusted, core_version=CORE_VERSION)
    assert bundle.plugin_id == "ghostcursor.test"
    assert bundle.signed is True
    assert bundle.files["ghostcursor/packs/index.json"] == (
        b'{"packs":[],"schema_version":2}\n'
    )


def test_changing_a_file_without_the_signed_digest_is_rejected(tmp_path):
    files = {"ghostcursor/packs/index.json": b"before"}
    manifest = _manifest(files)
    path, trusted = _write_bundle(
        tmp_path, manifest=manifest, files={"ghostcursor/packs/index.json": b"after"}
    )
    with pytest.raises(BundleVerificationError, match="digest mismatch"):
        verify_bundle(path, trusted_keys=trusted, core_version=CORE_VERSION)


def test_changing_the_digest_list_after_signing_is_rejected(tmp_path):
    files = {"ghostcursor/packs/index.json": b"before"}
    manifest = _manifest(files)
    path, trusted = _write_bundle(tmp_path, manifest=manifest, files=files)
    with zipfile.ZipFile(path, "r") as source:
        entries = {info.filename: source.read(info) for info in source.infolist()}
    changed = dict(manifest)
    changed["files"] = {
        "ghostcursor/packs/index.json": hashlib.sha256(b"after").hexdigest()
    }
    entries["plugin.json"] = json.dumps(
        changed, sort_keys=True, separators=(",", ":")
    ).encode()
    with zipfile.ZipFile(path, "w") as target:
        for name, raw in entries.items():
            target.writestr(name, raw)
    with pytest.raises(BundleVerificationError, match="signature is invalid"):
        verify_bundle(path, trusted_keys=trusted, core_version=CORE_VERSION)


def test_unsigned_bundles_exist_only_in_explicit_developer_mode(tmp_path):
    files = {"ghostcursor/packs/index.json": b"{}"}
    manifest = _manifest(files, signing_key_id=None)
    path, trusted = _write_bundle(tmp_path, manifest=manifest, files=files, sign=False)
    with pytest.raises(BundleVerificationError, match="forbidden in production"):
        verify_bundle(path, trusted_keys=trusted, core_version=CORE_VERSION)
    assert (
        verify_bundle(
            path,
            trusted_keys=trusted,
            core_version=CORE_VERSION,
            developer_mode=True,
        ).signed
        is False
    )


def test_a_bundle_signed_by_an_untrusted_key_is_refused(tmp_path):
    """A valid Ed25519 signature under a key_id the caller does not trust is
    rejected cleanly (BundleVerificationError, not a raw KeyError) before any
    file is read -- the signing-key allowlist is the trust boundary."""

    path, _trusted = _write_bundle(tmp_path)  # signed as "release-1"
    with pytest.raises(BundleVerificationError, match="signing key is not trusted"):
        verify_bundle(path, trusted_keys={}, core_version=CORE_VERSION)
    # and a different trusted id does not launder it in
    other = {"release-2": b"\0" * 32}
    with pytest.raises(BundleVerificationError, match="signing key is not trusted"):
        verify_bundle(path, trusted_keys=other, core_version=CORE_VERSION)


def test_a_signed_v2_bundle_binds_adapter_and_closed_operation_registry(tmp_path):
    files, adapter_sha = _v2_files()
    path, trusted = _write_bundle(tmp_path, files=files, manifest=_v2_manifest(files))

    bundle = verify_bundle(path, trusted_keys=trusted, core_version=CORE_VERSION)

    assert bundle.manifest["plugin_api_version"] == 2
    assert (
        hashlib.sha256(bundle.files["ghostcursor/adapter/test_adapter.py"]).hexdigest()
        == adapter_sha
    )


def test_an_executable_adapter_is_forbidden_even_in_unsigned_developer_mode(tmp_path):
    files, _ = _v2_files()
    manifest = _v2_manifest(files)
    manifest["signing_key_id"] = None
    path, trusted = _write_bundle(tmp_path, files=files, manifest=manifest, sign=False)

    with pytest.raises(BundleVerificationError, match="adapters must be signed"):
        verify_bundle(
            path,
            trusted_keys=trusted,
            core_version=CORE_VERSION,
            developer_mode=True,
        )


@pytest.mark.parametrize(
    "missing",
    [
        "ghostcursor/adapter/test_adapter.py",
        "ghostcursor/adapter/test_verifier.py",
        ACTION_PLAN_INDEX_PATH,
        OPERATION_ARTIFACT_PATH,
    ],
)
def test_v2_manifest_requires_both_signed_adapter_artifacts(tmp_path, missing):
    files, _ = _v2_files()
    manifest = _v2_manifest(files)
    del manifest["files"][missing]
    path, trusted = _write_bundle(tmp_path, files=files, manifest=manifest)

    with pytest.raises(BundleVerificationError, match="missing required file"):
        verify_bundle(path, trusted_keys=trusted, core_version=CORE_VERSION)


def test_adapter_registry_identity_and_adapter_bytes_are_independently_bound(tmp_path):
    files, _ = _v2_files(adapter=b"print('before')\n")
    manifest = _v2_manifest(files)
    changed = dict(files)
    changed["ghostcursor/adapter/test_adapter.py"] = b"print('after')\n"
    path, trusted = _write_bundle(tmp_path, files=changed, manifest=manifest)

    with pytest.raises(BundleVerificationError, match="digest mismatch"):
        verify_bundle(path, trusted_keys=trusted, core_version=CORE_VERSION)


def test_an_incompatible_bundle_is_rejected(tmp_path):
    files = {"ghostcursor/packs/index.json": b"{}"}
    manifest = _manifest(
        files,
        core_compatibility={"minimum": "2.0.0", "maximum_exclusive": "3.0.0"},
    )
    path, trusted = _write_bundle(tmp_path, manifest=manifest, files=files)
    with pytest.raises(BundleVerificationError, match="outside"):
        verify_bundle(path, trusted_keys=trusted, core_version=CORE_VERSION)


def test_a_signed_but_malformed_capability_artifact_is_rejected_at_bundle_verification(
    tmp_path,
):
    files = {
        "ghostcursor/packs/index.json": b'{"packs":[],"schema_version":2}',
        CAPABILITY_ARTIFACT_PATH: b'{"schema_version":1}\n',
    }
    path, trusted = _write_bundle(tmp_path, files=files)
    with pytest.raises(BundleVerificationError, match="capability artifact is invalid"):
        verify_bundle(path, trusted_keys=trusted, core_version=CORE_VERSION)


@pytest.mark.parametrize("entry", ["../escape", "/absolute", "a\\b"])
def test_unsafe_archive_paths_are_rejected(tmp_path, entry):
    path, trusted = _write_bundle(tmp_path, extras=[(entry, b"bad")])
    with pytest.raises(BundleVerificationError, match="bundle entr"):
        verify_bundle(path, trusted_keys=trusted, core_version=CORE_VERSION)


def test_symlink_entries_are_rejected(tmp_path):
    path, trusted = _write_bundle(tmp_path)
    with zipfile.ZipFile(path, "a") as archive:
        info = zipfile.ZipInfo("linked")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "packs/index.json")
    with pytest.raises(BundleVerificationError, match="symlink"):
        verify_bundle(path, trusted_keys=trusted, core_version=CORE_VERSION)
