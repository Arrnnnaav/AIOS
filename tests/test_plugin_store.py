from __future__ import annotations

import hashlib
import json
import multiprocessing
import zipfile
from pathlib import Path

import pytest
import win32event
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ghostcursor.plugins.bundle import CANONICAL_UIA_ADAPTER_SHA256
from ghostcursor.plugins.store import PluginEffectiveState, PluginStore, PluginStoreError
from ghostcursor.action import OPERATION_ARTIFACT_PATH
from ghostcursor.task_graph import CAPABILITY_ARTIFACT_PATH


def _abandon_named_mutex(name, ready):
    win32event.CreateMutex(None, True, name)
    ready.set()
    # Model a process dying in its critical section. Windows owns the mutex
    # lifetime and marks it abandoned when this process disappears.
    import os

    os._exit(7)


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
    adapter_api=None,
):
    files = files or {
        "ghostcursor/packs/index.json": b'{"packs":[],"schema_version":2}\n'
    }
    manifest = {
        "schema_version": 1,
        "plugin_id": plugin_id,
        "version": version,
        "plugin_api_version": 2 if adapter_api else 1,
        "core_compatibility": {
            "minimum": minimum,
            "maximum_exclusive": maximum,
        },
        "applications": [{"kind": "executable", "value": executable}],
        "signing_key_id": "release",
        "adapter_api": adapter_api,
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


def _excel_pack_files() -> dict[str, bytes]:
    project_root = Path(__file__).resolve().parent.parent
    files = {
        "ghostcursor/packs/index.json": (
            project_root / "plugins" / "sources" / "excel" / "index.json"
        ).read_bytes()
    }
    source = project_root / "plugins" / "sources" / "excel" / "payload"
    for path in source.rglob("*"):
        if path.is_file():
            files[path.relative_to(source).as_posix()] = path.read_bytes()
    return files


def _capabilities(*, intent_id="ADD_WORKSHEET", goal="add a worksheet in excel"):
    value = {
        "schema_version": 1,
        "plugin_id": "ghostcursor.excel",
        "plugin_version": "1.0.0",
        "capabilities": {
            "ADD_WORKSHEET": {
                "authorization_goal": goal,
                "intent_id": intent_id,
                "parameters": {},
                "postconditions": ["workbook.sheet_added"],
                "preconditions": ["workbook.open"],
                "safe_to_repeat": True,
            }
        },
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _powerpoint_adapter_files():
    root = (
        Path(__file__).resolve().parent.parent
        / "plugins"
        / "sources"
        / "powerpoint"
        / "payload"
        / "ghostcursor"
    )
    return {
        "ghostcursor/packs/index.json": b'{"packs":[],"schema_version":2}',
        "ghostcursor/adapter/powerpoint_adapter.py": (
            root / "adapter" / "powerpoint_adapter.py"
        ).read_bytes(),
        "ghostcursor/adapter/powerpoint_verifier.py": (
            root / "adapter" / "powerpoint_verifier.py"
        ).read_bytes(),
        "ghostcursor/action-plans.json": (root / "action-plans.json").read_bytes(),
        **{f"ghostcursor/action-plans/{path.name}": path.read_bytes()
           for path in (root / "action-plans").glob("*.json")},
        OPERATION_ARTIFACT_PATH: (root / "operations.json").read_bytes(),
    }


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


def test_empty_store_issues_the_composition_context_it_loads(tmp_path):
    store = PluginStore(
        tmp_path / "store",
        trusted_keys={},
        core_version="0.1.0",
    )
    # Initialize the explicit empty indexes, then exercise the real loader.
    assert store.list_installed() == ()

    context = store.load_composition_context()

    assert store.owns_composition_context(context)


def test_composition_reverifies_and_exposes_both_signed_adapter_processes(tmp_path):
    private, trusted = _key()
    files = _powerpoint_adapter_files()
    # The real registry declares a UIA operation, so the bundle must also ship
    # the canonical shared adapter -- bundle verification refuses either half
    # of that pairing on its own (D108).
    files["ghostcursor/adapter/uia_adapter.py"] = (
        Path(__file__).resolve().parents[1] / "plugins/shared/uia_adapter.py"
    ).read_bytes()
    # ...and a live-state verifier, by the same pairing rule: the file-reading
    # verifier cannot answer for an effect that exists only in the running
    # application.
    files["ghostcursor/adapter/powerpoint_live_verifier.py"] = b"# live state"
    adapter_api = {
        "entrypoint": "ghostcursor/adapter/powerpoint_adapter.py",
        "live_verifier": "ghostcursor/adapter/powerpoint_live_verifier.py",
        "operations": OPERATION_ARTIFACT_PATH,
        "plans": "ghostcursor/action-plans.json",
        "protocol_version": 1,
        "uia_entrypoint": "ghostcursor/adapter/uia_adapter.py",
        "verifier": "ghostcursor/adapter/powerpoint_verifier.py",
    }
    bundle = _bundle(
        tmp_path,
        private,
        plugin_id="ghostcursor.powerpoint",
        executable="powerpnt.exe",
        files=files,
        adapter_api=adapter_api,
    )
    store = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")
    store.install(bundle)
    store.enable("ghostcursor.powerpoint", "1.0.0")

    context = store.load_composition_context()
    assert store.owns_composition_context(context)
    descriptor = context.adapters["ghostcursor.powerpoint"]

    assert descriptor.entrypoint.name == "powerpoint_adapter.py"
    assert descriptor.verifier.name == "powerpoint_verifier.py"
    assert descriptor.adapter_sha256 == hashlib.sha256(files[adapter_api["entrypoint"]]).hexdigest()
    assert descriptor.verifier_sha256 == hashlib.sha256(files[adapter_api["verifier"]]).hexdigest()
    assert descriptor.uia_entrypoint.name == "uia_adapter.py"
    assert descriptor.uia_adapter_sha256 == CANONICAL_UIA_ADAPTER_SHA256


def test_descriptor_digests_come_from_signed_bytes_not_a_mutable_second_read(
    tmp_path, monkeypatch
):
    private, trusted = _key()
    files = _powerpoint_adapter_files()
    files["ghostcursor/adapter/uia_adapter.py"] = (
        Path(__file__).resolve().parents[1] / "plugins/shared/uia_adapter.py"
    ).read_bytes()
    files["ghostcursor/adapter/powerpoint_live_verifier.py"] = b"# live state"
    adapter_api = {
        "entrypoint": "ghostcursor/adapter/powerpoint_adapter.py",
        "live_verifier": "ghostcursor/adapter/powerpoint_live_verifier.py",
        "operations": OPERATION_ARTIFACT_PATH,
        "plans": "ghostcursor/action-plans.json",
        "protocol_version": 1,
        "uia_entrypoint": "ghostcursor/adapter/uia_adapter.py",
        "verifier": "ghostcursor/adapter/powerpoint_verifier.py",
    }
    bundle_path = _bundle(
        tmp_path,
        private,
        plugin_id="ghostcursor.powerpoint",
        executable="powerpnt.exe",
        files=files,
        adapter_api=adapter_api,
    )
    store = PluginStore(
        tmp_path / "store", trusted_keys=trusted, core_version="0.1.0"
    )
    store.install(bundle_path)
    store.enable("ghostcursor.powerpoint", "1.0.0")
    with store._transaction():
        active = store._load_active_catalog()

    original_verify = store._verify_payload

    def verify_then_replace(bundle):
        root = original_verify(bundle)
        (root / adapter_api["entrypoint"]).write_bytes(b"print('replacement ran')\n")
        return root

    monkeypatch.setattr(store, "_verify_payload", verify_then_replace)
    descriptors = store._adapter_descriptors(active.plugins)

    expected = hashlib.sha256(files[adapter_api["entrypoint"]]).hexdigest()
    replacement = hashlib.sha256(b"print('replacement ran')\n").hexdigest()
    assert descriptors["ghostcursor.powerpoint"].adapter_sha256 == expected
    assert expected != replacement


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


def test_composition_context_binds_signed_capabilities_to_one_catalog_epoch(tmp_path):
    private, trusted = _key()
    files = _excel_pack_files()
    files[CAPABILITY_ARTIFACT_PATH] = _capabilities()
    bundle = _bundle(
        tmp_path,
        private,
        plugin_id="ghostcursor.excel",
        executable="excel.exe",
        files=files,
    )
    store = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")
    installed = store.install(bundle)
    store.enable(installed.plugin_id, installed.version)

    context = store.load_composition_context()

    registry = context.registries["ghostcursor.excel"]
    assert registry.catalog_sha256 == context.catalog.index_sha256
    assert registry.catalog_generation == context.catalog.generation == 1
    assert registry.capabilities["ADD_WORKSHEET"].intent_id == "ADD_WORKSHEET"


def test_capability_must_name_its_own_active_intent_before_enable_is_published(tmp_path):
    private, trusted = _key()
    files = _excel_pack_files()
    files[CAPABILITY_ARTIFACT_PATH] = _capabilities(intent_id="FICTIONAL_INTENT")
    bundle = _bundle(
        tmp_path,
        private,
        plugin_id="ghostcursor.excel",
        executable="excel.exe",
        files=files,
    )
    store = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")
    installed = store.install(bundle)

    with pytest.raises(PluginStoreError, match="own active intent"):
        store.enable(installed.plugin_id, installed.version)
    assert store.list_installed()[0].state is PluginEffectiveState.DISABLED


def test_capability_authorization_goal_must_be_an_exact_trusted_phrase(tmp_path):
    private, trusted = _key()
    files = _excel_pack_files()
    files[CAPABILITY_ARTIFACT_PATH] = _capabilities(goal="please create another sheet in excel")
    bundle = _bundle(
        tmp_path,
        private,
        plugin_id="ghostcursor.excel",
        executable="excel.exe",
        files=files,
    )
    store = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")
    installed = store.install(bundle)

    with pytest.raises(PluginStoreError, match="not an exact match"):
        store.enable(installed.plugin_id, installed.version)


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


def test_the_same_store_root_has_one_process_independent_mutex(tmp_path):
    _, trusted = _key()
    first = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")
    second = PluginStore(tmp_path / "store" / ".", trusted_keys=trusted, core_version="0.1.0")
    developer = PluginStore(
        tmp_path / "store",
        trusted_keys=trusted,
        core_version="0.1.0",
        developer_mode=True,
    )

    assert first.mutex_name == second.mutex_name
    assert first.mutex_name != developer.mutex_name


def test_a_contended_store_fails_closed_instead_of_reading_between_writes(tmp_path):
    _, trusted = _key()
    store = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")
    handle = win32event.CreateMutex(None, True, store.mutex_name)
    try:
        # A different thread is what makes a Windows mutex genuinely
        # contended; mutex acquisition is recursive for its owning thread.
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(store.list_installed)
            with pytest.raises(PluginStoreError, match="plugin store is busy"):
                future.result(timeout=1.0)
    finally:
        win32event.ReleaseMutex(handle)
        handle.Close()


def test_a_crashed_process_cannot_strand_the_plugin_store(tmp_path):
    _, trusted = _key()
    store = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    child = context.Process(
        target=_abandon_named_mutex,
        args=(store.mutex_name, ready),
    )
    child.start()
    try:
        assert ready.wait(5.0)
        child.join(5.0)
        assert not child.is_alive()
        assert child.exitcode == 7
        assert store.list_installed() == ()
    finally:
        if child.is_alive():
            child.terminate()
        child.join(5.0)


def test_a_revoked_digest_is_refused_at_install(tmp_path):
    private, trusted = _key()
    bundle = _bundle(tmp_path, private)
    digest = PluginStore(
        tmp_path / "probe", trusted_keys=trusted, core_version="0.1.0"
    ).inspect(bundle).manifest_sha256

    store = PluginStore(
        tmp_path / "store",
        trusted_keys=trusted,
        core_version="0.1.0",
        revoked_digests=frozenset({digest}),
    )
    with pytest.raises(PluginStoreError, match="revoked"):
        store.install(bundle)
    assert store.list_installed() == ()


def test_a_revoked_digest_cannot_be_reactivated(tmp_path):
    private, trusted = _key()
    bundle = _bundle(tmp_path, private)
    base = tmp_path / "store"
    # install while not revoked
    PluginStore(base, trusted_keys=trusted, core_version="0.1.0").install(bundle)
    digest = PluginStore(
        tmp_path / "probe", trusted_keys=trusted, core_version="0.1.0"
    ).inspect(bundle).manifest_sha256

    # a later store that knows the digest is revoked refuses to enable it
    revoked = PluginStore(
        base,
        trusted_keys=trusted,
        core_version="0.1.0",
        revoked_digests=frozenset({digest}),
    )
    with pytest.raises(PluginStoreError, match="revoked"):
        revoked.enable("ghostcursor.one", "1.0.0")


def test_a_revoked_digest_drops_from_the_active_catalog(tmp_path):
    private, trusted = _key()
    bundle = _bundle(tmp_path, private)
    base = tmp_path / "store"
    live = PluginStore(base, trusted_keys=trusted, core_version="0.1.0")
    live.install(bundle)
    live.enable("ghostcursor.one", "1.0.0")
    assert tuple(live.load_active_catalog().plugins) == ("ghostcursor.one",)

    digest = PluginStore(
        tmp_path / "probe", trusted_keys=trusted, core_version="0.1.0"
    ).inspect(bundle).manifest_sha256
    # a store that knows the digest is revoked serves it from NO active catalog,
    # even though it is still recorded active in active.json
    revoked = PluginStore(
        base,
        trusted_keys=trusted,
        core_version="0.1.0",
        revoked_digests=frozenset({digest}),
    )
    assert tuple(revoked.load_active_catalog().plugins) == ()



def test_a_differently_signed_bundle_of_an_installed_version_is_refused(tmp_path):
    private, trusted = _key()
    store = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")
    first = _bundle(tmp_path, private)
    store.install(first)
    store.enable("ghostcursor.one", "1.0.0")
    other = tmp_path / "other"
    other.mkdir()
    changed = _bundle(
        other,
        private,
        files={"ghostcursor/packs/index.json": b'{"packs":[],"schema_version":2} \n'},
    )
    store.install(first)  # the same bytes again is fine
    with pytest.raises(PluginStoreError, match="different contents"):
        store.install(changed)
    assert tuple(store.load_active_catalog().plugins) == ("ghostcursor.one",)


def test_a_bundle_swapped_after_verifying_is_not_installed(tmp_path, monkeypatch):
    import shutil as _shutil

    private, trusted = _key()
    store = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")
    bundle = _bundle(tmp_path, private)
    real = _shutil.copyfile

    def swap(source, target, *a, **k):
        real(source, target, *a, **k)
        Path(target).write_bytes(b"not the verified bundle")

    monkeypatch.setattr("ghostcursor.plugins.store.shutil.copyfile", swap)
    with pytest.raises(PluginStoreError, match="changed while"):
        store.install(bundle)


def test_one_faulty_plugin_is_left_out_and_the_others_still_load(tmp_path, monkeypatch):
    # Owner decision (23 Nov): a plugin whose own catalog no longer loads is
    # left out alone; enabling one is still refused, tampering stays loud.
    from ghostcursor.plugins.store import CatalogInvalid

    private, trusted = _key()
    store = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")
    one = store.install(_bundle(tmp_path, private, files=_common_pack_files()))
    two = store.install(
        _bundle(tmp_path, private, plugin_id="ghostcursor.two", executable="Two.exe")
    )
    store.enable(one.plugin_id, one.version)
    store.enable(two.plugin_id, two.version)

    real = store._bundle_catalog

    def catalog(bundle):
        if bundle.plugin_id == "ghostcursor.two":
            raise CatalogInvalid("plugin ghostcursor.two pack catalog is invalid: expired")
        return real(bundle)

    monkeypatch.setattr(store, "_bundle_catalog", catalog)
    context = store.load_composition_context()
    assert "common" in context.catalog.packs  # the good plugin still works
    assert "ghostcursor.two" in store.skipped_plugins
    assert "ghostcursor.two" not in context.registries


def test_enabling_a_faulty_plugin_is_still_refused(tmp_path, monkeypatch):
    from ghostcursor.plugins.store import CatalogInvalid

    private, trusted = _key()
    store = PluginStore(tmp_path / "store", trusted_keys=trusted, core_version="0.1.0")
    one = store.install(_bundle(tmp_path, private, files=_common_pack_files()))

    def catalog(bundle):
        raise CatalogInvalid("plugin ghostcursor.one pack catalog is invalid: bad")

    monkeypatch.setattr(store, "_bundle_catalog", catalog)
    with pytest.raises(CatalogInvalid):
        store.enable(one.plugin_id, one.version)

