"""Atomic local installation and activation for verified plugin bundles."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Iterator, Mapping

import win32api
import win32event

from ghostcursor.plugins.bundle import (
    BundleVerificationError,
    VerifiedBundle,
    verify_bundle,
)
from ghostcursor.plugins.compatibility import (
    CompatibilityResult,
    check_core_compatibility,
)


class PluginStoreError(ValueError):
    """A requested lifecycle transition failed without changing active state."""


# The runtime authority monitor reads the active index every 0.25 seconds and
# must abort within D020's 0.5-second ceiling. Waiting seconds for a lifecycle
# writer would turn a coherent store into an unresponsive safety gate, so a
# contended store is an immediate fail-closed answer instead.
STORE_LOCK_TIMEOUT_MS = 100


class PluginEffectiveState(str, Enum):
    DISABLED = "disabled"
    ENABLED_COMPATIBLE = "enabled_compatible"
    BLOCKED_INCOMPATIBLE = "blocked_incompatible"


@dataclass(frozen=True)
class InstalledPlugin:
    plugin_id: str
    version: str
    manifest_sha256: str
    state: PluginEffectiveState
    compatibility: CompatibilityResult
    signed: bool


@dataclass(frozen=True)
class ActivePluginCatalog:
    """The exact compatible plugin set named by one active-index generation."""

    generation: int
    active_index_sha256: str
    plugins: Mapping[str, VerifiedBundle]
    blocked: Mapping[str, CompatibilityResult]


@dataclass(frozen=True)
class CompositionContext:
    """One atomic view of executable intents and their capability vocabulary."""

    catalog: Any
    registries: Mapping[str, Any]
    adapters: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class AdapterDescriptor:
    """One re-verified first-party adapter bound to signed payload bytes."""

    plugin_id: str
    plugin_version: str
    manifest_sha256: str
    payload_root: Path
    entrypoint: Path
    adapter_sha256: str
    verifier: Path
    verifier_sha256: str
    registry: Any
    plans: Mapping[str, Any]
    #: The canonical shared UIA adapter, when this plugin ships one. Core
    #: selects between the two by the OPERATION's signed backend declaration
    #: and never by anything a model produced (D108).
    uia_entrypoint: Path | None = None
    uia_adapter_sha256: str | None = None


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise PluginStoreError(f"{label} must not contain a UTF-8 BOM")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PluginStoreError(f"{label} is not valid UTF-8") from exc

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise PluginStoreError(f"duplicate key in {label}: {key}")
            value[key] = item
        return value

    try:
        value = json.loads(text, object_pairs_hook=pairs)
    except json.JSONDecodeError as exc:
        raise PluginStoreError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise PluginStoreError(f"{label} must be an object")
    return value


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


class PluginStore:
    """The sole lifecycle authority for one production or developer store."""

    def __init__(
        self,
        base_root: Path,
        *,
        trusted_keys: Mapping[str, bytes],
        core_version: str,
        developer_mode: bool = False,
        observation_store_path: Path | None = None,
    ) -> None:
        self.base_root = Path(base_root).resolve()
        self.developer_mode = developer_mode
        self.root = self.base_root / ("developer" if developer_mode else "production")
        self.trusted_keys = MappingProxyType(dict(trusted_keys))
        self.core_version = core_version
        self.observation_store_path = observation_store_path
        root_identity = str(self.root).casefold().encode("utf-8")
        self._mutex_name = (
            "Local\\GhostCursor.PluginStore."
            + hashlib.sha256(root_identity).hexdigest()[:24]
        )

    @property
    def mutex_name(self) -> str:
        """The process-independent transaction identity for this exact store."""

        return self._mutex_name

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """Serialize one coherent store operation across Windows processes.

        Atomic index replacement prevents torn JSON, but it does not prevent
        two processes from reading generation N and each publishing a different
        generation N+1.  The named mutex closes that lost-update window.  A
        Windows mutex is released when its owner process dies, so a crashed CLI
        cannot strand the manager behind a stale lock file.
        """

        handle = win32event.CreateMutex(None, False, self._mutex_name)
        acquired = False
        try:
            outcome = win32event.WaitForSingleObject(handle, STORE_LOCK_TIMEOUT_MS)
            if outcome not in (win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED):
                raise PluginStoreError("plugin store is busy; try again")
            acquired = True
            yield
        finally:
            if acquired:
                win32event.ReleaseMutex(handle)
            win32api.CloseHandle(handle)

    @property
    def developer_marker(self) -> bool:
        """A UI/runtime marker, not an inferred property of installed content."""

        return self.developer_mode

    def _ensure_layout(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "installed").mkdir(exist_ok=True)
        (self.root / "staging").mkdir(exist_ok=True)
        if not (self.root / "installed.json").exists():
            self._write_index("installed.json", {"schema_version": 1, "plugins": {}})
        if not (self.root / "active.json").exists():
            self._write_index(
                "active.json", {"schema_version": 1, "generation": 0, "plugins": {}}
            )

    def _read_index(self, name: str) -> tuple[dict[str, Any], bytes]:
        self._ensure_layout()
        path = self.root / name
        raw = path.read_bytes()
        value = _strict_json(raw, name)
        if value.get("schema_version") != 1 or not isinstance(
            value.get("plugins"), dict
        ):
            raise PluginStoreError(f"{name} has an invalid schema")
        return value, raw

    def _write_index(self, name: str, value: Mapping[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / name
        temporary = self.root / f".{name}.{uuid.uuid4().hex}.tmp"
        raw = _canonical(value)
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)

    def _entry(self, plugin_id: str, version: str) -> dict[str, Any]:
        installed, _ = self._read_index("installed.json")
        try:
            entry = installed["plugins"][plugin_id]["versions"][version]
        except (KeyError, TypeError) as exc:
            raise PluginStoreError(
                f"plugin {plugin_id} {version} is not installed"
            ) from exc
        if not isinstance(entry, dict) or set(entry) != {"manifest_sha256", "path"}:
            raise PluginStoreError("installed plugin entry is malformed")
        return entry

    def _installed_bundle(self, plugin_id: str, version: str) -> VerifiedBundle:
        entry = self._entry(plugin_id, version)
        relative = entry["path"]
        if not isinstance(relative, str):
            raise PluginStoreError("installed plugin path is malformed")
        posix = PurePosixPath(relative)
        if posix.is_absolute() or ".." in posix.parts or "\\" in relative:
            raise PluginStoreError("installed plugin path is unsafe")
        path = (self.root / Path(*posix.parts)).resolve()
        try:
            path.relative_to((self.root / "installed").resolve())
        except ValueError as exc:
            raise PluginStoreError("installed plugin path escapes the store") from exc
        try:
            bundle = verify_bundle(
                path,
                trusted_keys=self.trusted_keys,
                core_version=self.core_version,
                developer_mode=self.developer_mode,
                require_compatible=False,
            )
        except (BundleVerificationError, OSError) as exc:
            raise PluginStoreError(
                f"installed plugin failed verification: {exc}"
            ) from exc
        if bundle.manifest_sha256 != entry["manifest_sha256"]:
            raise PluginStoreError(
                "installed bundle digest disagrees with installed index"
            )
        if bundle.plugin_id != plugin_id or bundle.version != version:
            raise PluginStoreError(
                "installed bundle identity disagrees with installed index"
            )
        return bundle

    def _payload_root(self, bundle: VerifiedBundle) -> Path:
        return (
            self.root
            / "catalogs"
            / bundle.plugin_id
            / bundle.version
            / bundle.manifest_sha256
        )

    def _stage_payload(self, bundle: VerifiedBundle) -> None:
        """Publish the signed file inventory as one immutable directory."""

        target = self._payload_root(bundle)
        if target.exists():
            self._verify_payload(bundle)
            return
        staging = self.root / "staging" / f"payload-{uuid.uuid4().hex}"
        staging.mkdir(parents=True)
        try:
            for name, raw in bundle.files.items():
                destination = staging / Path(*PurePosixPath(name).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(staging, target)
            except OSError:
                if not target.exists():
                    raise
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        self._verify_payload(bundle)

    def _verify_payload(self, bundle: VerifiedBundle) -> Path:
        """Re-bind every extracted runtime byte to the signed inventory."""

        root = self._payload_root(bundle)
        if not root.is_dir() or root.is_symlink():
            raise PluginStoreError("installed plugin payload is missing or unsafe")
        actual: dict[str, Path] = {}
        folded: set[str] = set()
        for path in root.rglob("*"):
            if path.is_symlink():
                raise PluginStoreError("installed plugin payload contains a symlink")
            if path.is_file():
                name = path.relative_to(root).as_posix()
                if name.casefold() in folded:
                    raise PluginStoreError(
                        "installed plugin payload has case-colliding files"
                    )
                folded.add(name.casefold())
                actual[name] = path
        if set(actual) != set(bundle.files):
            raise PluginStoreError(
                "installed plugin payload disagrees with signed inventory"
            )
        for name, expected in bundle.files.items():
            if actual[name].read_bytes() != expected:
                raise PluginStoreError(f"installed plugin payload changed: {name}")
        index = root / "ghostcursor" / "packs" / "index.json"
        if not index.is_file():
            raise PluginStoreError(
                "plugin payload is missing ghostcursor/packs/index.json"
            )
        return root

    def _bundle_catalog(self, bundle: VerifiedBundle):
        from ghostcursor.packs.activation import load_catalog

        catalog = load_catalog(self._verify_payload(bundle))
        if not catalog.root_valid or catalog.diagnostics:
            detail = "; ".join(item.detail for item in catalog.diagnostics)
            raise PluginStoreError(
                f"plugin {bundle.plugin_id} pack catalog is invalid: "
                f"{detail or 'invalid root'}"
            )
        return catalog

    def inspect(self, bundle_path: Path) -> VerifiedBundle:
        return verify_bundle(
            bundle_path,
            trusted_keys=self.trusted_keys,
            core_version=self.core_version,
            developer_mode=self.developer_mode,
        )

    def install(self, bundle_path: Path) -> InstalledPlugin:
        with self._transaction():
            return self._install(bundle_path)

    def _install(self, bundle_path: Path) -> InstalledPlugin:
        bundle = self.inspect(bundle_path)
        self._ensure_layout()
        relative = PurePosixPath(
            "installed",
            bundle.plugin_id,
            bundle.version,
            bundle.manifest_sha256,
            "bundle.ghostplugin",
        ).as_posix()
        target = self.root / Path(*PurePosixPath(relative).parts)
        if not target.exists():
            staging = self.root / "staging" / uuid.uuid4().hex
            staging.mkdir()
            staged_bundle = staging / "bundle.ghostplugin"
            shutil.copyfile(bundle.path, staged_bundle)
            # The digest directory itself is the atomic rename target. Creating
            # it first turns an atomic publication into an invalid directory-
            # over-directory replacement on Windows.
            target.parent.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(staging, target.parent)
            except OSError:
                if not target.exists():
                    raise
                shutil.rmtree(staging, ignore_errors=True)
        installed, _ = self._read_index("installed.json")
        plugins = dict(installed["plugins"])
        plugin = dict(plugins.get(bundle.plugin_id, {"versions": {}}))
        versions = dict(plugin.get("versions", {}))
        versions[bundle.version] = {
            "manifest_sha256": bundle.manifest_sha256,
            "path": relative,
        }
        plugin["versions"] = versions
        plugins[bundle.plugin_id] = plugin
        self._stage_payload(bundle)
        self._write_index("installed.json", {"schema_version": 1, "plugins": plugins})
        return InstalledPlugin(
            plugin_id=bundle.plugin_id,
            version=bundle.version,
            manifest_sha256=bundle.manifest_sha256,
            state=PluginEffectiveState.DISABLED,
            compatibility=bundle.compatibility,
            signed=bundle.signed,
        )

    def _prospective_plugins(
        self, active: Mapping[str, Any]
    ) -> dict[str, VerifiedBundle]:
        bundles: dict[str, VerifiedBundle] = {}
        identities: dict[tuple[str, str], str] = {}
        for plugin_id, ref in active.items():
            if not isinstance(ref, dict) or set(ref) != {"version", "manifest_sha256"}:
                raise PluginStoreError("active plugin entry is malformed")
            bundle = self._installed_bundle(plugin_id, ref["version"])
            if bundle.manifest_sha256 != ref["manifest_sha256"]:
                raise PluginStoreError(
                    "active plugin digest disagrees with installed bundle"
                )
            compatibility = check_core_compatibility(bundle.manifest, self.core_version)
            if not compatibility.compatible:
                continue
            for app in bundle.manifest["applications"]:
                identity = (app["kind"].casefold(), app["value"].casefold())
                previous = identities.get(identity)
                if previous is not None:
                    raise PluginStoreError(
                        f"application identity conflict between {previous} and {plugin_id}"
                    )
                identities[identity] = plugin_id
            bundles[plugin_id] = bundle
        self._merge_catalogs(bundles, generation=0, active_index_sha256="0" * 64)
        return bundles

    def _merge_catalogs(
        self,
        bundles: Mapping[str, VerifiedBundle],
        *,
        generation: int,
        active_index_sha256: str,
    ):
        from ghostcursor.packs.activation import merge_catalogs

        catalogs = {
            plugin_id: self._bundle_catalog(bundle)
            for plugin_id, bundle in bundles.items()
        }
        metadata = {
            plugin_id: (bundle.version, bundle.manifest_sha256)
            for plugin_id, bundle in bundles.items()
        }
        merged = merge_catalogs(
            catalogs,
            index_sha256=active_index_sha256,
            generation=generation,
            plugin_metadata=metadata,
        )
        if not merged.root_valid:
            detail = "; ".join(item.detail for item in merged.diagnostics)
            raise PluginStoreError(f"active plugin catalog conflicts: {detail}")
        self._capability_registries(
            bundles,
            merged,
            generation=generation,
            active_index_sha256=active_index_sha256,
        )
        return merged

    def _capability_registries(
        self,
        bundles: Mapping[str, VerifiedBundle],
        catalog,
        *,
        generation: int,
        active_index_sha256: str,
    ) -> Mapping[str, Any]:
        """Validate optional signed registries against the merged active catalog."""

        from ghostcursor.packs.activation import IntentAvailability
        from ghostcursor.packs.compile import EXACT_CONFIDENCE, compile_matcher
        from ghostcursor.task_graph import (
            CAPABILITY_ARTIFACT_PATH,
            TaskGraphValidationError,
            load_capability_registry,
        )

        active_intents = {
            (pack.plugin_id, intent_id)
            for pack in catalog.packs.values()
            for intent_id, intent in pack.intents.items()
            if intent.availability is IntentAvailability.ACTIVE
        }
        matcher = compile_matcher(catalog)
        registries = {}
        for plugin_id, bundle in bundles.items():
            raw = bundle.files.get(CAPABILITY_ARTIFACT_PATH)
            if raw is None:
                continue
            try:
                registry = load_capability_registry(
                    raw,
                    plugin_id=plugin_id,
                    plugin_version=bundle.version,
                    catalog_sha256=active_index_sha256,
                    catalog_generation=generation,
                )
            except TaskGraphValidationError as exc:
                raise PluginStoreError(
                    f"plugin {plugin_id} capability registry is invalid: {exc}"
                ) from exc
            for capability in registry.capabilities.values():
                if (plugin_id, capability.intent_id) not in active_intents:
                    raise PluginStoreError(
                        f"plugin {plugin_id} capability {capability.capability_id} "
                        f"does not map to its own active intent {capability.intent_id}"
                    )
                outcome = matcher.classify(capability.authorization_goal)
                if (
                    outcome.intent_id != capability.intent_id
                    or outcome.confidence != EXACT_CONFIDENCE
                ):
                    raise PluginStoreError(
                        f"plugin {plugin_id} capability {capability.capability_id} "
                        "authorization_goal is not an exact match for its intent"
                    )
            registries[plugin_id] = registry
        return MappingProxyType(registries)

    def _adapter_descriptors(
        self, bundles: Mapping[str, VerifiedBundle]
    ) -> Mapping[str, AdapterDescriptor]:
        """Load signed executable adapters from the same store transaction.

        The payload is byte-reverified on every composition load. Returning a
        path without that recheck would let an extracted adapter drift while
        its signed bundle continued to look healthy.
        """

        from ghostcursor.action import load_operation_registry
        from ghostcursor.action_plans import load_action_plan_templates

        adapters: dict[str, AdapterDescriptor] = {}
        for plugin_id, bundle in bundles.items():
            adapter = bundle.manifest["adapter_api"]
            if adapter is None:
                continue
            root = self._verify_payload(bundle)
            entrypoint = root / Path(*PurePosixPath(adapter["entrypoint"]).parts)
            operations = root / Path(*PurePosixPath(adapter["operations"]).parts)
            verifier = root / Path(*PurePosixPath(adapter["verifier"]).parts)
            entrypoint_bytes = entrypoint.read_bytes()
            verifier_bytes = verifier.read_bytes()
            adapter_sha256 = hashlib.sha256(entrypoint_bytes).hexdigest()
            registry = load_operation_registry(
                operations.read_bytes(),
                plugin_id=plugin_id,
                plugin_version=bundle.version,
                adapter_sha256=adapter_sha256,
            )
            plans = load_action_plan_templates(
                (root / Path(*PurePosixPath(adapter["plans"]).parts)).read_bytes(),
                bundle.files,
                plugin_id=plugin_id,
                plugin_version=bundle.version,
                adapter_sha256=adapter_sha256,
            )
            uia_declared = adapter.get("uia_entrypoint")
            uia_entrypoint = None
            uia_adapter_sha256 = None
            if uia_declared is not None:
                uia_entrypoint = root / Path(*PurePosixPath(uia_declared).parts)
                uia_adapter_sha256 = hashlib.sha256(
                    uia_entrypoint.read_bytes()
                ).hexdigest()
            adapters[plugin_id] = AdapterDescriptor(
                plugin_id=plugin_id,
                plugin_version=bundle.version,
                manifest_sha256=bundle.manifest_sha256,
                payload_root=root,
                entrypoint=entrypoint,
                adapter_sha256=adapter_sha256,
                verifier=verifier,
                verifier_sha256=hashlib.sha256(verifier_bytes).hexdigest(),
                registry=registry,
                plans=plans,
                uia_entrypoint=uia_entrypoint,
                uia_adapter_sha256=uia_adapter_sha256,
            )
        return MappingProxyType(adapters)

    def enable(self, plugin_id: str, version: str) -> InstalledPlugin:
        with self._transaction():
            return self._enable(plugin_id, version)

    def _enable(self, plugin_id: str, version: str) -> InstalledPlugin:
        bundle = self._installed_bundle(plugin_id, version)
        compatibility = check_core_compatibility(bundle.manifest, self.core_version)
        if not compatibility.compatible:
            raise PluginStoreError(compatibility.reason)
        active, _ = self._read_index("active.json")
        plugins = dict(active["plugins"])
        plugins[plugin_id] = {
            "version": version,
            "manifest_sha256": bundle.manifest_sha256,
        }
        self._prospective_plugins(plugins)
        self._write_index(
            "active.json",
            {
                "schema_version": 1,
                "generation": int(active.get("generation", 0)) + 1,
                "plugins": plugins,
            },
        )
        return InstalledPlugin(
            plugin_id=plugin_id,
            version=version,
            manifest_sha256=bundle.manifest_sha256,
            state=PluginEffectiveState.ENABLED_COMPATIBLE,
            compatibility=compatibility,
            signed=bundle.signed,
        )

    def disable(self, plugin_id: str) -> None:
        with self._transaction():
            self._disable(plugin_id)

    def _disable(self, plugin_id: str) -> None:
        active, _ = self._read_index("active.json")
        plugins = dict(active["plugins"])
        if plugin_id not in plugins:
            return
        del plugins[plugin_id]
        self._write_index(
            "active.json",
            {
                "schema_version": 1,
                "generation": int(active.get("generation", 0)) + 1,
                "plugins": plugins,
            },
        )

    def uninstall(self, plugin_id: str, version: str) -> None:
        with self._transaction():
            self._uninstall(plugin_id, version)

    def _uninstall(self, plugin_id: str, version: str) -> None:
        active, _ = self._read_index("active.json")
        if plugin_id in active["plugins"]:
            raise PluginStoreError("disable a plugin before uninstalling it")
        entry = self._entry(plugin_id, version)
        relative = PurePosixPath(entry["path"])
        bundle_path = (self.root / Path(*relative.parts)).resolve()
        install_root = (self.root / "installed").resolve()
        try:
            bundle_path.relative_to(install_root)
        except ValueError as exc:
            raise PluginStoreError(
                "refusing to remove a path outside installed root"
            ) from exc
        version_root = bundle_path.parent
        if version_root.exists():
            shutil.rmtree(version_root)
        catalog_version = self.root / "catalogs" / plugin_id / version
        if catalog_version.exists():
            shutil.rmtree(catalog_version)
        installed, _ = self._read_index("installed.json")
        plugins = dict(installed["plugins"])
        plugin = dict(plugins[plugin_id])
        versions = dict(plugin["versions"])
        del versions[version]
        if versions:
            plugin["versions"] = versions
            plugins[plugin_id] = plugin
        else:
            del plugins[plugin_id]
        self._write_index("installed.json", {"schema_version": 1, "plugins": plugins})
        if self.observation_store_path is not None:
            from ghostcursor.memory.store import ObservationStore

            with ObservationStore(self.observation_store_path) as observations:
                observations.purge_plugin(plugin_id, version)

    def list_installed(self) -> tuple[InstalledPlugin, ...]:
        with self._transaction():
            return self._list_installed()

    def _list_installed(self) -> tuple[InstalledPlugin, ...]:
        installed, _ = self._read_index("installed.json")
        active, _ = self._read_index("active.json")
        result: list[InstalledPlugin] = []
        for plugin_id in sorted(installed["plugins"]):
            versions = installed["plugins"][plugin_id]["versions"]
            for version in sorted(versions):
                bundle = self._installed_bundle(plugin_id, version)
                compatibility = check_core_compatibility(
                    bundle.manifest, self.core_version
                )
                desired = active["plugins"].get(plugin_id)
                if desired is None or desired.get("version") != version:
                    state = PluginEffectiveState.DISABLED
                elif compatibility.compatible:
                    state = PluginEffectiveState.ENABLED_COMPATIBLE
                else:
                    state = PluginEffectiveState.BLOCKED_INCOMPATIBLE
                result.append(
                    InstalledPlugin(
                        plugin_id=plugin_id,
                        version=version,
                        manifest_sha256=bundle.manifest_sha256,
                        state=state,
                        compatibility=compatibility,
                        signed=bundle.signed,
                    )
                )
        return tuple(result)

    def load_active_catalog(self) -> ActivePluginCatalog:
        with self._transaction():
            return self._load_active_catalog()

    def _load_active_catalog(self) -> ActivePluginCatalog:
        active, raw = self._read_index("active.json")
        generation = active.get("generation")
        if not isinstance(generation, int) or generation < 0:
            raise PluginStoreError("active generation is invalid")
        compatible = self._prospective_plugins(active["plugins"])
        blocked: dict[str, CompatibilityResult] = {}
        for plugin_id, ref in active["plugins"].items():
            bundle = self._installed_bundle(plugin_id, ref["version"])
            outcome = check_core_compatibility(bundle.manifest, self.core_version)
            if not outcome.compatible:
                blocked[plugin_id] = outcome
        return ActivePluginCatalog(
            generation=generation,
            active_index_sha256=hashlib.sha256(raw).hexdigest(),
            plugins=MappingProxyType(compatible),
            blocked=MappingProxyType(blocked),
        )

    def current_active_index_sha256(self) -> str:
        """Read the lifecycle stamp without creating or repairing store state.

        The running-tour monitor calls this four times a second. It is not a
        second catalog loader: planning and bind-time revalidation already
        verify every signed payload byte. This stamp answers only whether a
        lifecycle operation changed the active authority after launch.

        Missing or malformed state raises. A security check must never turn a
        deleted index into a fresh empty one merely by checking it.
        """

        with self._transaction():
            path = self.root / "active.json"
            raw = path.read_bytes()
            active = _strict_json(raw, "active.json")
            if (
                active.get("schema_version") != 1
                or not isinstance(active.get("plugins"), dict)
                or not isinstance(active.get("generation"), int)
                or active["generation"] < 0
            ):
                raise PluginStoreError("active.json has an invalid schema")
            return hashlib.sha256(raw).hexdigest()

    def load_verified_catalog(self):
        """Return the one merged executable catalog for compatible plugins."""

        with self._transaction():
            active = self._load_active_catalog()
            return self._merge_catalogs(
                active.plugins,
                generation=active.generation,
                active_index_sha256=active.active_index_sha256,
            )

    def load_composition_context(self) -> CompositionContext:
        """Load catalog and capability registries under one store transaction."""

        with self._transaction():
            active = self._load_active_catalog()
            catalog = self._merge_catalogs(
                active.plugins,
                generation=active.generation,
                active_index_sha256=active.active_index_sha256,
            )
            registries = self._capability_registries(
                active.plugins,
                catalog,
                generation=active.generation,
                active_index_sha256=active.active_index_sha256,
            )
            adapters = self._adapter_descriptors(active.plugins)
            return CompositionContext(
                catalog=catalog,
                registries=registries,
                adapters=adapters,
            )
