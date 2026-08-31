"""Strict verification for signed, data-only ``.ghostplugin`` bundles."""

from __future__ import annotations

import hashlib
import json
import math
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ghostcursor.plugins.compatibility import CompatibilityResult, check_core_compatibility


_PLUGIN_ID_RE = re.compile(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SEMVER_RE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
_RESERVED = frozenset({"plugin.json", "signature.ed25519"})


class BundleVerificationError(ValueError):
    """A bundle failed before any byte was admitted to the plugin store."""


@dataclass(frozen=True)
class VerifiedBundle:
    path: Path
    plugin_id: str
    version: str
    manifest_sha256: str
    manifest_bytes: bytes
    manifest: Mapping[str, Any]
    files: Mapping[str, bytes]
    compatibility: CompatibilityResult
    signed: bool

    @property
    def storage_digest(self) -> str:
        """Identity of the attested manifest and therefore its signed inventory."""

        return self.manifest_sha256


def _strict_json(raw: bytes) -> dict[str, Any]:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise BundleVerificationError("plugin manifest must not contain a UTF-8 BOM")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BundleVerificationError("plugin manifest is not valid UTF-8") from exc

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise BundleVerificationError(f"duplicate manifest key: {key}")
            value[key] = item
        return value

    def constant(value: str) -> None:
        raise BundleVerificationError(f"non-finite manifest number is forbidden: {value}")

    def number(value: str) -> float:
        result = float(value)
        if not math.isfinite(result):
            raise BundleVerificationError("non-finite manifest number is forbidden")
        return result

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=constant,
            parse_float=number,
        )
    except json.JSONDecodeError as exc:
        raise BundleVerificationError("plugin manifest is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise BundleVerificationError("plugin manifest must be an object")
    return parsed


def _entry_name(name: str) -> str:
    if not name or "\\" in name or name.startswith("/") or name.endswith("/"):
        raise BundleVerificationError(f"non-canonical bundle entry: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BundleVerificationError(f"unsafe bundle entry: {name!r}")
    canonical = path.as_posix()
    if canonical != name:
        raise BundleVerificationError(f"non-canonical bundle entry: {name!r}")
    return canonical


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _validate_manifest(value: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "plugin_id",
        "version",
        "plugin_api_version",
        "core_compatibility",
        "applications",
        "signing_key_id",
        "adapter_api",
        "files",
    }
    if set(value) != required:
        missing, extra = sorted(required - set(value)), sorted(set(value) - required)
        raise BundleVerificationError(
            f"plugin manifest fields disagree; missing={missing}, extra={extra}"
        )
    if value["schema_version"] != 1 or value["plugin_api_version"] != 1:
        raise BundleVerificationError("only plugin schema/API version 1 is supported")
    if not isinstance(value["plugin_id"], str) or _PLUGIN_ID_RE.fullmatch(value["plugin_id"]) is None:
        raise BundleVerificationError("plugin_id is not canonical")
    if not isinstance(value["version"], str) or _SEMVER_RE.fullmatch(value["version"]) is None:
        raise BundleVerificationError("plugin version must be canonical MAJOR.MINOR.PATCH")
    if value["adapter_api"] is not None:
        raise BundleVerificationError("plugin API v1 forbids executable adapters")
    if value["signing_key_id"] is not None and not isinstance(value["signing_key_id"], str):
        raise BundleVerificationError("signing_key_id must be a string or null")
    applications = value["applications"]
    if not isinstance(applications, list) or not applications:
        raise BundleVerificationError("plugin must own at least one application identity")
    seen_apps: set[tuple[str, str]] = set()
    for app in applications:
        if not isinstance(app, dict) or set(app) != {"kind", "value"}:
            raise BundleVerificationError("each application requires exactly kind and value")
        if not all(isinstance(app[key], str) and app[key] for key in ("kind", "value")):
            raise BundleVerificationError("application identity values must be non-empty strings")
        identity = (app["kind"].casefold(), app["value"].casefold())
        if identity in seen_apps:
            raise BundleVerificationError("duplicate application identity in plugin")
        seen_apps.add(identity)
    files = value["files"]
    if not isinstance(files, dict) or not files:
        raise BundleVerificationError("plugin file inventory must be a non-empty object")
    folded: set[str] = set()
    for raw_name, digest in files.items():
        if not isinstance(raw_name, str):
            raise BundleVerificationError("plugin file names must be strings")
        name = _entry_name(raw_name)
        if name in _RESERVED:
            raise BundleVerificationError(f"reserved file cannot appear in inventory: {name}")
        if name.casefold() in folded:
            raise BundleVerificationError("case-colliding file names in inventory")
        folded.add(name.casefold())
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise BundleVerificationError(f"invalid SHA-256 for {name}")


def verify_bundle(
    path: Path,
    *,
    trusted_keys: Mapping[str, bytes],
    core_version: str,
    developer_mode: bool = False,
    require_compatible: bool = True,
) -> VerifiedBundle:
    """Verify one bundle completely without writing any of its contents."""

    path = Path(path)
    if path.suffix != ".ghostplugin" or not path.is_file():
        raise BundleVerificationError("plugin must be an existing .ghostplugin file")
    try:
        archive = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise BundleVerificationError("plugin is not a readable ZIP archive") from exc
    with archive:
        infos = archive.infolist()
        names: dict[str, zipfile.ZipInfo] = {}
        folded: set[str] = set()
        for info in infos:
            name = _entry_name(info.filename)
            if _is_symlink(info):
                raise BundleVerificationError(f"symlink bundle entry is forbidden: {name}")
            if name in names or name.casefold() in folded:
                raise BundleVerificationError(f"duplicate or case-colliding bundle entry: {name}")
            names[name] = info
            folded.add(name.casefold())
        if "plugin.json" not in names:
            raise BundleVerificationError("bundle is missing plugin.json")
        manifest_bytes = archive.read(names["plugin.json"])
        manifest = _strict_json(manifest_bytes)
        _validate_manifest(manifest)
        signed = "signature.ed25519" in names
        key_id = manifest["signing_key_id"]
        if not signed:
            if not developer_mode:
                raise BundleVerificationError("unsigned plugins are forbidden in production")
            if key_id is not None:
                raise BundleVerificationError("unsigned developer plugin must use null signing_key_id")
        else:
            if key_id is None or key_id not in trusted_keys:
                raise BundleVerificationError("plugin signing key is not trusted")
            signature = archive.read(names["signature.ed25519"])
            try:
                Ed25519PublicKey.from_public_bytes(trusted_keys[key_id]).verify(
                    signature, manifest_bytes
                )
            except (ValueError, InvalidSignature) as exc:
                raise BundleVerificationError("plugin signature is invalid") from exc
        inventory = manifest["files"]
        expected = {"plugin.json", *inventory}
        if signed:
            expected.add("signature.ed25519")
        actual = set(names)
        if actual != expected:
            raise BundleVerificationError(
                f"bundle entries disagree with signed inventory; missing={sorted(expected-actual)}, "
                f"extra={sorted(actual-expected)}"
            )
        file_bytes: dict[str, bytes] = {}
        for name, digest in inventory.items():
            raw = archive.read(names[name])
            if hashlib.sha256(raw).hexdigest() != digest:
                raise BundleVerificationError(f"plugin file digest mismatch: {name}")
            file_bytes[name] = raw
        if "ghostcursor/packs/index.json" not in file_bytes:
            raise BundleVerificationError(
                "plugin inventory is missing ghostcursor/packs/index.json"
            )
        from ghostcursor.task_graph import (
            CAPABILITY_ARTIFACT_PATH,
            TaskGraphValidationError,
            load_capability_registry,
        )

        capability_bytes = file_bytes.get(CAPABILITY_ARTIFACT_PATH)
        if capability_bytes is not None:
            try:
                load_capability_registry(
                    capability_bytes,
                    plugin_id=manifest["plugin_id"],
                    plugin_version=manifest["version"],
                    catalog_sha256="0" * 64,
                    catalog_generation=1,
                )
            except TaskGraphValidationError as exc:
                raise BundleVerificationError(
                    f"plugin capability artifact is invalid: {exc}"
                ) from exc
    try:
        compatibility = check_core_compatibility(manifest, core_version)
    except ValueError as exc:
        raise BundleVerificationError(str(exc)) from exc
    if require_compatible and not compatibility.compatible:
        raise BundleVerificationError(compatibility.reason)
    return VerifiedBundle(
        path=path.resolve(),
        plugin_id=manifest["plugin_id"],
        version=manifest["version"],
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        manifest_bytes=manifest_bytes,
        manifest=MappingProxyType(manifest),
        files=MappingProxyType(file_bytes),
        compatibility=compatibility,
        signed=signed,
    )
