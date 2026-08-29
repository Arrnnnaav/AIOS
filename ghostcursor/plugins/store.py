"""Atomic local installation and activation for verified plugin bundles."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

from ghostcursor.plugins.bundle import BundleVerificationError, VerifiedBundle, verify_bundle
from ghostcursor.plugins.compatibility import CompatibilityResult, check_core_compatibility


class PluginStoreError(ValueError):
    """A requested lifecycle transition failed without changing active state."""


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
    ) -> None:
        self.base_root = Path(base_root).resolve()
        self.developer_mode = developer_mode
        self.root = self.base_root / ("developer" if developer_mode else "production")
        self.trusted_keys = MappingProxyType(dict(trusted_keys))
        self.core_version = core_version

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
        if value.get("schema_version") != 1 or not isinstance(value.get("plugins"), dict):
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
            raise PluginStoreError(f"plugin {plugin_id} {version} is not installed") from exc
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
            raise PluginStoreError(f"installed plugin failed verification: {exc}") from exc
        if bundle.manifest_sha256 != entry["manifest_sha256"]:
            raise PluginStoreError("installed bundle digest disagrees with installed index")
        if bundle.plugin_id != plugin_id or bundle.version != version:
            raise PluginStoreError("installed bundle identity disagrees with installed index")
        return bundle

    def inspect(self, bundle_path: Path) -> VerifiedBundle:
        return verify_bundle(
            bundle_path,
            trusted_keys=self.trusted_keys,
            core_version=self.core_version,
            developer_mode=self.developer_mode,
        )

    def install(self, bundle_path: Path) -> InstalledPlugin:
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
        self._write_index("installed.json", {"schema_version": 1, "plugins": plugins})
        return InstalledPlugin(
            plugin_id=bundle.plugin_id,
            version=bundle.version,
            manifest_sha256=bundle.manifest_sha256,
            state=PluginEffectiveState.DISABLED,
            compatibility=bundle.compatibility,
            signed=bundle.signed,
        )

    def _prospective_plugins(self, active: Mapping[str, Any]) -> dict[str, VerifiedBundle]:
        bundles: dict[str, VerifiedBundle] = {}
        identities: dict[tuple[str, str], str] = {}
        for plugin_id, ref in active.items():
            if not isinstance(ref, dict) or set(ref) != {"version", "manifest_sha256"}:
                raise PluginStoreError("active plugin entry is malformed")
            bundle = self._installed_bundle(plugin_id, ref["version"])
            if bundle.manifest_sha256 != ref["manifest_sha256"]:
                raise PluginStoreError("active plugin digest disagrees with installed bundle")
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
        return bundles

    def enable(self, plugin_id: str, version: str) -> InstalledPlugin:
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
            raise PluginStoreError("refusing to remove a path outside installed root") from exc
        version_root = bundle_path.parent
        if version_root.exists():
            shutil.rmtree(version_root)
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

    def list_installed(self) -> tuple[InstalledPlugin, ...]:
        installed, _ = self._read_index("installed.json")
        active, _ = self._read_index("active.json")
        result: list[InstalledPlugin] = []
        for plugin_id in sorted(installed["plugins"]):
            versions = installed["plugins"][plugin_id]["versions"]
            for version in sorted(versions):
                bundle = self._installed_bundle(plugin_id, version)
                compatibility = check_core_compatibility(bundle.manifest, self.core_version)
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
