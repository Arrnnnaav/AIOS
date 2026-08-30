from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ghostcursor.plugins.store import PluginEffectiveState, PluginStore, PluginStoreError


def _key():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return private, {"release": public}


def _bundle(
    root: Path,
    private: Ed25519PrivateKey,
    *,
    plugin_id="ghostcursor.one",
    version="1.0.0",
    executable="One.exe",
    minimum="0.1.0",
    maximum="1.0.0",
    files=None,
):
    files = files or {
        "ghostcursor/packs/index.json": b'{"packs":[],"schema_version":2}\n'
    }
    manifest = {
        "schema_version": 1,
        "plugin_id": plugin_id,
        "version": version,
        "plugin_api_version": 1,
        "core_compatibility": {
            "minimum": minimum,
            "maximum_exclusive": maximum,
        },
        "applications": [{"kind": "executable", "value": executable}],
        "signing_key_id": "release",
        "adapter_api": None,
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
    }
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    path = root / f"{plugin_id}-{version}.ghostplugin"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("plugin.json", raw)
        archive.writestr("signature.ed25519", private.sign(raw))
        for name, value in files.items():
            archive.writestr(name, value)
    return path


def _common_pack_files() -> dict[str, bytes]:
    project_root = Path(__file__).resolve().parent.parent
    files = {
        "ghostcursor/packs/index.json": (
            b'{"packs":[{"pack_id":"common","path":"common"}],'
            b'"schema_version":2}\n'
        )
    }
    source = project_root / "ghostcursor" / "packs" / "common"
    for path in source.rglob("*"):
        if path.is_file():
            files[
                "ghostcursor/packs/common/" + path.relative_to(source).as_posix()
            ] = path.read_bytes()
    return files


def test_install_enable_disable_and_uninstall_are_distinct(tmp_path):
    private, trusted = _key()
    bundle = _bundle(tmp_path, private)
    store = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")

    assert store.install(bundle).state is PluginEffectiveState.DISABLED
    assert store.enable("ghostcursor.one", "1.0.0").state is PluginEffectiveState.ENABLED_COMPATIBLE
    assert tuple(store.load_active_catalog().plugins) == ("ghostcursor.one",)
    store.disable("ghostcursor.one")
    assert store.list_installed()[0].state is PluginEffectiveState.DISABLED
    store.uninstall("ghostcursor.one", "1.0.0")
    assert store.list_installed() == ()


def test_core_upgrade_preserves_desired_enablement_as_blocked(tmp_path):
    private, trusted = _key()
    bundle = _bundle(tmp_path, private, maximum="0.2.0")
    base = tmp_path / "store"
    old = PluginStore(base, trusted_keys=trusted, core_version="0.1.0")
    old.install(bundle)
    old.enable("ghostcursor.one", "1.0.0")

    upgraded = PluginStore(base, trusted_keys=trusted, core_version="0.2.0")
    status = upgraded.list_installed()[0]
    assert status.state is PluginEffectiveState.BLOCKED_INCOMPATIBLE
    catalog = upgraded.load_active_catalog()
    assert catalog.plugins == {}
    assert tuple(catalog.blocked) == ("ghostcursor.one",)

    rolled_back = PluginStore(base, trusted_keys=trusted, core_version="0.1.0")
    assert rolled_back.list_installed()[0].state is PluginEffectiveState.ENABLED_COMPATIBLE


def test_application_identity_conflict_is_atomic(tmp_path):
    private, trusted = _key()
    first = _bundle(tmp_path, private, plugin_id="ghostcursor.one", executable="Same.exe")
    second = _bundle(tmp_path, private, plugin_id="ghostcursor.two", executable="same.EXE")
    store = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")
    store.install(first)
    store.install(second)
    store.enable("ghostcursor.one", "1.0.0")
    before = store.load_active_catalog()
    with pytest.raises(PluginStoreError, match="identity conflict"):
        store.enable("ghostcursor.two", "1.0.0")
    after = store.load_active_catalog()
    assert after.generation == before.generation
    assert tuple(after.plugins) == ("ghostcursor.one",)


def test_a_tampered_installed_bundle_fails_closed(tmp_path):
    private, trusted = _key()
    bundle = _bundle(tmp_path, private)
    store = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")
    installed = store.install(bundle)
    index = json.loads((store.root / "installed.json").read_text())
    relative = index["plugins"][installed.plugin_id]["versions"][installed.version]["path"]
    path = store.root / Path(*relative.split("/"))
    path.write_bytes(b"not a zip")
    with pytest.raises(PluginStoreError, match="failed verification"):
        store.list_installed()


def test_developer_and_production_stores_are_physically_separate(tmp_path):
    private, trusted = _key()
    bundle = _bundle(tmp_path, private)
    development = PluginStore(
        tmp_path / "store", trusted_keys=trusted, core_version="0.1.0", developer_mode=True
    )
    production = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")
    development.install(bundle)
    development.enable("ghostcursor.one", "1.0.0")
    assert development.developer_marker is True
    assert production.list_installed() == ()
    assert production.load_active_catalog().plugins == {}


def test_runtime_catalog_carries_plugin_provenance_and_active_generation(tmp_path):
    private, trusted = _key()
    bundle = _bundle(tmp_path, private, files=_common_pack_files())
    store = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")
    installed = store.install(bundle)
    store.enable(installed.plugin_id, installed.version)

    catalog = store.load_verified_catalog()

    assert catalog.root_valid
    assert catalog.generation == 1
    assert catalog.index_sha256 == store.load_active_catalog().active_index_sha256
    pack = catalog.packs["common"]
    assert (pack.plugin_id, pack.plugin_version, pack.plugin_manifest_sha256) == (
        installed.plugin_id,
        installed.version,
        installed.manifest_sha256,
    )


def test_active_index_stamp_changes_on_lifecycle_change_and_never_repairs_state(
    tmp_path,
):
    private, trusted = _key()
    store = PluginStore(
        tmp_path / "store", trusted_keys=trusted, core_version="0.1.0"
    )
    with pytest.raises(FileNotFoundError):
        store.current_active_index_sha256()
    assert not (store.root / "active.json").exists()

    installed = store.install(_bundle(tmp_path, private))
    disabled = store.current_active_index_sha256()
    store.enable(installed.plugin_id, installed.version)
    enabled = store.current_active_index_sha256()
    store.disable(installed.plugin_id)
    disabled_again = store.current_active_index_sha256()

    assert len({disabled, enabled, disabled_again}) == 3


def test_cross_plugin_pack_conflict_is_rejected_atomically(tmp_path):
    private, trusted = _key()
    files = _common_pack_files()
    first = _bundle(
        tmp_path,
        private,
        plugin_id="ghostcursor.one",
        executable="One.exe",
        files=files,
    )
    second = _bundle(
        tmp_path,
        private,
        plugin_id="ghostcursor.two",
        executable="Two.exe",
        files=files,
    )
    store = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")
    store.install(first)
    store.install(second)
    store.enable("ghostcursor.one", "1.0.0")
    before = store.load_active_catalog()

    with pytest.raises(PluginStoreError, match="more than one active plugin"):
        store.enable("ghostcursor.two", "1.0.0")

    after = store.load_active_catalog()
    assert after.generation == before.generation
    assert tuple(after.plugins) == ("ghostcursor.one",)


def test_runtime_rejects_a_tampered_extracted_payload(tmp_path):
    private, trusted = _key()
    bundle = _bundle(tmp_path, private, files=_common_pack_files())
    store = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")
    installed = store.install(bundle)
    store.enable(installed.plugin_id, installed.version)
    payload = (
        store.root
        / "catalogs"
        / installed.plugin_id
        / installed.version
        / installed.manifest_sha256
        / "ghostcursor"
        / "packs"
        / "index.json"
    )
    payload.write_bytes(b"tampered")

    with pytest.raises(PluginStoreError, match="payload changed"):
        store.load_verified_catalog()


def test_disable_retains_but_uninstall_clears_version_scoped_learning(tmp_path):
    from ghostcursor.memory.store import ObservationStore
    from ghostcursor.reasoning.schema import ConfirmedObservation

    private, trusted = _key()
    bundle = _bundle(tmp_path, private)
    db = tmp_path / "observations.sqlite"
    store = PluginStore(
        tmp_path / "store",
        trusted_keys=trusted,
        core_version="0.1.0",
        observation_store_path=db,
    )
    installed = store.install(bundle)
    store.enable(installed.plugin_id, installed.version)
    observation = ConfirmedObservation(
        app_version="1.0",
        locales_observed=["en-US"],
        automation_id="stable-id",
        control_type="Button",
        accessibility_path_hint=[],
        last_seen_at=None,
    )
    with ObservationStore(db) as memory:
        memory.record(
            "step",
            "one.exe",
            observation,
            plugin_id=installed.plugin_id,
            plugin_version=installed.version,
        )
    store.disable(installed.plugin_id)
    with ObservationStore(db) as memory:
        assert len(
            memory.observations_for(
                "step",
                "one.exe",
                plugin_id=installed.plugin_id,
                plugin_version=installed.version,
            )
        ) == 1

    store.uninstall(installed.plugin_id, installed.version)

    with ObservationStore(db) as memory:
        assert memory.observations_for(
            "step",
            "one.exe",
            plugin_id=installed.plugin_id,
            plugin_version=installed.version,
        ) == []
