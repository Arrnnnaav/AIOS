"""Strict verification for signed ``.ghostplugin`` bundles.

API v1 remains data-only. API v2 may carry one first-party executable adapter,
but its entrypoint and closed operation registry are themselves signed file
inventory entries and are validated before extraction.
"""

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

from ghostcursor.plugins.compatibility import (
    CompatibilityResult,
    check_core_compatibility,
)


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
        raise BundleVerificationError(
            f"non-finite manifest number is forbidden: {value}"
        )

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
    if value["schema_version"] != 1 or value["plugin_api_version"] not in {1, 2}:
        raise BundleVerificationError("plugin schema/API version is unsupported")
    if (
        not isinstance(value["plugin_id"], str)
        or _PLUGIN_ID_RE.fullmatch(value["plugin_id"]) is None
    ):
        raise BundleVerificationError("plugin_id is not canonical")
    if (
        not isinstance(value["version"], str)
        or _SEMVER_RE.fullmatch(value["version"]) is None
    ):
        raise BundleVerificationError(
            "plugin version must be canonical MAJOR.MINOR.PATCH"
        )
    adapter = value["adapter_api"]
    if value["plugin_api_version"] == 1:
        if adapter is not None:
            raise BundleVerificationError("plugin API v1 forbids executable adapters")
    else:
        entrypoint, operations, plans, verifier, uia_entrypoint, live_verifier = (
            verify_adapter_shape(adapter)
        )
        if operations != "ghostcursor/operations.json":
            raise BundleVerificationError(
                "adapter operation registry path is not canonical"
            )
        if plans != "ghostcursor/action-plans.json":
            raise BundleVerificationError(
                "adapter action plan index path is not canonical"
            )
    if value["signing_key_id"] is not None and not isinstance(
        value["signing_key_id"], str
    ):
        raise BundleVerificationError("signing_key_id must be a string or null")
    applications = value["applications"]
    if not isinstance(applications, list) or not applications:
        raise BundleVerificationError(
            "plugin must own at least one application identity"
        )
    seen_apps: set[tuple[str, str]] = set()
    for app in applications:
        if not isinstance(app, dict) or set(app) != {"kind", "value"}:
            raise BundleVerificationError(
                "each application requires exactly kind and value"
            )
        if not all(isinstance(app[key], str) and app[key] for key in ("kind", "value")):
            raise BundleVerificationError(
                "application identity values must be non-empty strings"
            )
        identity = (app["kind"].casefold(), app["value"].casefold())
        if identity in seen_apps:
            raise BundleVerificationError("duplicate application identity in plugin")
        seen_apps.add(identity)
    files = value["files"]
    if not isinstance(files, dict) or not files:
        raise BundleVerificationError(
            "plugin file inventory must be a non-empty object"
        )
    folded: set[str] = set()
    for raw_name, digest in files.items():
        if not isinstance(raw_name, str):
            raise BundleVerificationError("plugin file names must be strings")
        name = _entry_name(raw_name)
        if name in _RESERVED:
            raise BundleVerificationError(
                f"reserved file cannot appear in inventory: {name}"
            )
        if name.casefold() in folded:
            raise BundleVerificationError("case-colliding file names in inventory")
        folded.add(name.casefold())
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise BundleVerificationError(f"invalid SHA-256 for {name}")
    if value["plugin_api_version"] == 2:
        for required_path in (
            value["adapter_api"]["entrypoint"],
            value["adapter_api"]["operations"],
            value["adapter_api"]["plans"],
            value["adapter_api"]["verifier"],
        ):
            if required_path not in files:
                raise BundleVerificationError(
                    f"adapter inventory is missing required file: {required_path}"
                )



#: sha256 of the canonical reviewed generic UIA adapter source
#: (`plugins/shared/uia_adapter.py`). A plugin carries a byte-identical copy,
#: so one review covers every copy -- and a copy that has drifted from the
#: reviewed bytes is refused rather than executed (D108).
CANONICAL_UIA_ADAPTER_SHA256 = "0752ebc2bef68f69f4dfc3ced66fc38eb71f58d08e2edc6c0fe6cca53205c465"


def verify_adapter_shape(adapter):
    """Validate one API-v2 adapter declaration and return its paths.

    Extracted so the rules can be exercised directly. They were inline in
    a much larger verification routine, which meant the only way to reach
    them was to build a whole bundle -- and rules nothing can reach
    cheaply are rules nothing tests.
    """

    required = {
        "entrypoint",
        "operations",
        "plans",
        "protocol_version",
        "verifier",
    }
    # `uia_entrypoint` is OPTIONAL so every bundle signed before generic
    # UIA support keeps verifying byte-for-byte. It carries the canonical
    # shared adapter (D108) alongside the plugin's own object-model
    # adapter, inside the same signed payload, so both execution paths are
    # digest-bound together and disabling the plugin removes both.
    if (
        not isinstance(adapter, dict)
        or not required <= set(adapter)
        or not set(adapter) <= required | {"uia_entrypoint", "live_verifier"}
    ):
        raise BundleVerificationError(
            "plugin API v2 requires one closed adapter declaration"
        )
    if adapter["protocol_version"] != 1:
        raise BundleVerificationError("adapter protocol version is unsupported")
    entrypoint = adapter["entrypoint"]
    operations = adapter["operations"]
    plans = adapter["plans"]
    verifier = adapter["verifier"]
    if not all(
        isinstance(path, str) for path in (entrypoint, operations, plans, verifier)
    ):
        raise BundleVerificationError("adapter paths must be strings")
    if _entry_name(entrypoint) != entrypoint or not entrypoint.startswith(
        "ghostcursor/adapter/"
    ):
        raise BundleVerificationError(
            "adapter entrypoint must live under ghostcursor/adapter/"
        )
    if not entrypoint.endswith(".py"):
        raise BundleVerificationError(
            "adapter entrypoint must be a Python source file"
        )
    if _entry_name(verifier) != verifier or not verifier.startswith(
        "ghostcursor/adapter/"
    ):
        raise BundleVerificationError(
            "adapter verifier must live under ghostcursor/adapter/"
        )
    if not verifier.endswith(".py") or verifier == entrypoint:
        raise BundleVerificationError(
            "adapter verifier must be a distinct Python source file"
        )
    uia_entrypoint = adapter.get("uia_entrypoint")
    if uia_entrypoint is not None:
        if not isinstance(uia_entrypoint, str):
            raise BundleVerificationError("adapter uia_entrypoint must be a string")
        if _entry_name(uia_entrypoint) != uia_entrypoint or not (
            uia_entrypoint.startswith("ghostcursor/adapter/")
            and uia_entrypoint.endswith(".py")
        ):
            raise BundleVerificationError(
                "adapter uia_entrypoint must be a Python source file under "
                "ghostcursor/adapter/"
            )
        # Distinct from BOTH other executables. Sharing a path with the
        # object-model adapter would let one file answer for two backends,
        # and sharing with the verifier would let the thing that checks an
        # effect also cause one.
        if uia_entrypoint in {entrypoint, verifier}:
            raise BundleVerificationError(
                "adapter uia_entrypoint must be distinct from the entrypoint "
                "and the verifier"
            )

    live_verifier = adapter.get("live_verifier")
    if live_verifier is not None:
        # Optional for the same reason `uia_entrypoint` is: every bundle
        # signed before live-state verification keeps verifying byte for
        # byte. It answers a different question from the artifact verifier --
        # what the RUNNING application is, not what a saved file contains --
        # and those carry different trust classes (LIVE_STATE against
        # ARTIFACT), so one file must never be able to answer for both.
        if not isinstance(live_verifier, str):
            raise BundleVerificationError("adapter live_verifier must be a string")
        if _entry_name(live_verifier) != live_verifier or not (
            live_verifier.startswith("ghostcursor/adapter/")
            and live_verifier.endswith(".py")
        ):
            raise BundleVerificationError(
                "adapter live_verifier must be a Python source file under "
                "ghostcursor/adapter/"
            )
        if live_verifier in {entrypoint, verifier, uia_entrypoint}:
            raise BundleVerificationError(
                "adapter live_verifier must be distinct from the entrypoint, "
                "the verifier and the uia_entrypoint"
            )

    return entrypoint, operations, plans, verifier, uia_entrypoint, live_verifier


def _check_backend_declarations(adapter, registry, file_bytes):
    """Every operation maps to exactly one declared, present backend.

    The failure this prevents is an operation whose backend nothing can
    dispatch: declared UIA with no UIA adapter shipped, or a UIA adapter
    shipped that no operation uses and that therefore nobody reviewed against
    a real operation.
    """

    uia_entrypoint = adapter.get("uia_entrypoint")
    needs_uia = sorted(
        operation_id
        for operation_id, spec in registry.operations.items()
        if spec.backend != "object_model"
    )
    if needs_uia and uia_entrypoint is None:
        raise BundleVerificationError(
            "operations declare a UIA backend but no uia_entrypoint is shipped: "
            + ", ".join(needs_uia)
        )
    if uia_entrypoint is not None and not needs_uia:
        # An unused executable is an unreviewed one: nothing exercises it and
        # nothing in the registry says what it is allowed to do.
        raise BundleVerificationError(
            "a uia_entrypoint is shipped but no operation declares a UIA backend"
        )
    live_verifier = adapter.get("live_verifier")
    if needs_uia and live_verifier is None:
        # A UIA operation whose effect nothing can verify is an operation that
        # can only be PERFORMED. The artifact verifier reads a saved file and
        # a UIA effect is live state, so shipping the backend without this is
        # shipping an action with no possible independent confirmation.
        raise BundleVerificationError(
            "operations declare a UIA backend but no live_verifier is shipped: "
            + ", ".join(needs_uia)
        )
    if live_verifier is not None and not needs_uia:
        raise BundleVerificationError(
            "a live_verifier is shipped but no operation declares a UIA backend"
        )
    if live_verifier is not None and live_verifier not in file_bytes:
        raise BundleVerificationError(
            "adapter live_verifier is not present in the signed payload"
        )
    if uia_entrypoint is None:
        return
    if uia_entrypoint not in file_bytes:
        raise BundleVerificationError(
            "adapter uia_entrypoint is not present in the signed payload"
        )
    actual = hashlib.sha256(file_bytes[uia_entrypoint]).hexdigest()
    if actual != CANONICAL_UIA_ADAPTER_SHA256:
        raise BundleVerificationError(
            "shipped UIA adapter bytes do not match the canonical reviewed "
            f"adapter ({actual} != {CANONICAL_UIA_ADAPTER_SHA256})"
        )

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
                raise BundleVerificationError(
                    f"symlink bundle entry is forbidden: {name}"
                )
            if name in names or name.casefold() in folded:
                raise BundleVerificationError(
                    f"duplicate or case-colliding bundle entry: {name}"
                )
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
                raise BundleVerificationError(
                    "unsigned plugins are forbidden in production"
                )
            if key_id is not None:
                raise BundleVerificationError(
                    "unsigned developer plugin must use null signing_key_id"
                )
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
                f"bundle entries disagree with signed inventory; missing={sorted(expected - actual)}, "
                f"extra={sorted(actual - expected)}"
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
        adapter = manifest["adapter_api"]
        if adapter is not None:
            # Executable adapters are never admitted unsigned, including the
            # physically separate developer store. Developer mode is for
            # inert data authoring, not arbitrary local code execution.
            if not signed:
                raise BundleVerificationError("executable adapters must be signed")
            from ghostcursor.action import (
                ActionValidationError,
                load_operation_registry,
            )

            entrypoint = adapter["entrypoint"]
            operations_path = adapter["operations"]
            try:
                registry = load_operation_registry(
                    file_bytes[operations_path],
                    plugin_id=manifest["plugin_id"],
                    plugin_version=manifest["version"],
                    adapter_sha256=hashlib.sha256(file_bytes[entrypoint]).hexdigest(),
                )
            except ActionValidationError as exc:
                raise BundleVerificationError(
                    f"plugin operation registry is invalid: {exc}"
                ) from exc

            _check_backend_declarations(adapter, registry, file_bytes)
            from ghostcursor.action_plans import (
                ActionPlanError,
                load_action_plan_templates,
            )

            try:
                load_action_plan_templates(
                    file_bytes[adapter["plans"]],
                    file_bytes,
                    plugin_id=manifest["plugin_id"],
                    plugin_version=manifest["version"],
                    adapter_sha256=registry.adapter_sha256,
                )
            except ActionPlanError as exc:
                raise BundleVerificationError(
                    f"plugin action plans are invalid: {exc}"
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
