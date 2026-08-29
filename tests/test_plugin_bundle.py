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
    files = files or {"packs/index.json": b'{"packs":[]}\n'}
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


def test_compatibility_is_a_half_open_semantic_version_range():
    manifest = _manifest({"packs/index.json": b"{}"})
    assert check_core_compatibility(manifest, "0.1.0").compatible
    assert check_core_compatibility(manifest, "0.9.9").compatible
    assert not check_core_compatibility(manifest, "1.0.0").compatible


def test_a_signed_bundle_binds_the_exact_manifest_and_every_file(tmp_path):
    path, trusted = _write_bundle(tmp_path)
    bundle = verify_bundle(path, trusted_keys=trusted, core_version=CORE_VERSION)
    assert bundle.plugin_id == "ghostcursor.test"
    assert bundle.signed is True
    assert bundle.files["packs/index.json"] == b'{"packs":[]}\n'


def test_changing_a_file_without_the_signed_digest_is_rejected(tmp_path):
    files = {"packs/index.json": b"before"}
    manifest = _manifest(files)
    path, trusted = _write_bundle(
        tmp_path, manifest=manifest, files={"packs/index.json": b"after"}
    )
    with pytest.raises(BundleVerificationError, match="digest mismatch"):
        verify_bundle(path, trusted_keys=trusted, core_version=CORE_VERSION)


def test_changing_the_digest_list_after_signing_is_rejected(tmp_path):
    files = {"packs/index.json": b"before"}
    manifest = _manifest(files)
    path, trusted = _write_bundle(tmp_path, manifest=manifest, files=files)
    with zipfile.ZipFile(path, "r") as source:
        entries = {info.filename: source.read(info) for info in source.infolist()}
    changed = dict(manifest)
    changed["files"] = {"packs/index.json": hashlib.sha256(b"after").hexdigest()}
    entries["plugin.json"] = json.dumps(
        changed, sort_keys=True, separators=(",", ":")
    ).encode()
    with zipfile.ZipFile(path, "w") as target:
        for name, raw in entries.items():
            target.writestr(name, raw)
    with pytest.raises(BundleVerificationError, match="signature is invalid"):
        verify_bundle(path, trusted_keys=trusted, core_version=CORE_VERSION)


def test_unsigned_bundles_exist_only_in_explicit_developer_mode(tmp_path):
    files = {"packs/index.json": b"{}"}
    manifest = _manifest(files, signing_key_id=None)
    path, trusted = _write_bundle(tmp_path, manifest=manifest, files=files, sign=False)
    with pytest.raises(BundleVerificationError, match="forbidden in production"):
        verify_bundle(path, trusted_keys=trusted, core_version=CORE_VERSION)
    assert verify_bundle(
        path,
        trusted_keys=trusted,
        core_version=CORE_VERSION,
        developer_mode=True,
    ).signed is False


def test_an_incompatible_bundle_is_rejected(tmp_path):
    files = {"packs/index.json": b"{}"}
    manifest = _manifest(
        files,
        core_compatibility={"minimum": "2.0.0", "maximum_exclusive": "3.0.0"},
    )
    path, trusted = _write_bundle(tmp_path, manifest=manifest, files=files)
    with pytest.raises(BundleVerificationError, match="outside"):
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
