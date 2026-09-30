"""Root-authenticated release-key policy for signed plugin bundles.

The root public key is pinned by the application. Release-key metadata is
data, but it is accepted only when both policy documents have valid detached
signatures from that root. Callers reload it at catalog admission and while
monitoring a running workflow; cached key maps are not revocation policy.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


_KEY_ID_RE = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_REASONS = frozenset({"compromised", "retired", "superseded"})


class ReleaseTrustError(ValueError):
    """Release trust metadata is invalid, stale, or refuses this key."""


@dataclass(frozen=True)
class ReleaseKey:
    key_id: str
    public_key: bytes
    not_before: datetime
    not_after: datetime
    successor_key_ids: tuple[str, ...]
    predecessor_key_id: str | None


@dataclass(frozen=True)
class ReleaseTrustPolicy:
    trusted_keys: Mapping[str, bytes]
    key_records: Mapping[str, ReleaseKey]
    key_manifest_sha256: str
    revocations_sha256: str


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _strict_json(raw: bytes, label: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ReleaseTrustError(f"{label} contains a duplicate field")
            result[key] = value
        return result

    def reject_number(_value):
        raise ReleaseTrustError(f"{label} must not contain floating-point numbers")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(
                ReleaseTrustError(f"{label} contains a non-finite number")
            ),
            parse_float=reject_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseTrustError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict) or _canonical(value) != raw:
        raise ReleaseTrustError(f"{label} is not a canonical JSON object")
    return value


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReleaseTrustError(f"{label} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ReleaseTrustError(f"{label} must be a UTC timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ReleaseTrustError(f"{label} must be a UTC timestamp")
    return parsed


def _verify_root_signature(
    raw: bytes, signature: bytes, root_public_key: bytes, label: str
) -> None:
    if not isinstance(root_public_key, bytes) or len(root_public_key) != 32:
        raise ReleaseTrustError("pinned trust-root key is invalid")
    if not isinstance(signature, bytes) or len(signature) != 64:
        raise ReleaseTrustError(f"{label} signature is invalid")
    try:
        Ed25519PublicKey.from_public_bytes(root_public_key).verify(signature, raw)
    except (ValueError, InvalidSignature) as exc:
        raise ReleaseTrustError(f"{label} signature is invalid") from exc


def load_trust_policy(
    *,
    key_manifest_bytes: bytes,
    key_manifest_signature: bytes,
    revocations_bytes: bytes,
    revocations_signature: bytes,
    root_public_key: bytes,
    now: datetime | None = None,
) -> ReleaseTrustPolicy:
    """Verify root-signed metadata and return only currently trusted keys."""

    _verify_root_signature(
        key_manifest_bytes, key_manifest_signature, root_public_key, "key manifest"
    )
    _verify_root_signature(
        revocations_bytes, revocations_signature, root_public_key, "revocation"
    )
    key_doc = _strict_json(key_manifest_bytes, "key manifest")
    revocation_doc = _strict_json(revocations_bytes, "revocation list")
    if (
        set(key_doc) != {"schema_version", "generated_at", "keys"}
        or type(key_doc["schema_version"]) is not int
        or key_doc["schema_version"] != 1
    ):
        raise ReleaseTrustError("key manifest schema is invalid")
    if (
        set(revocation_doc) != {"schema_version", "generated_at", "revoked"}
        or type(revocation_doc["schema_version"]) is not int
        or revocation_doc["schema_version"] != 1
    ):
        raise ReleaseTrustError("revocation list schema is invalid")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() != timezone.utc.utcoffset(current):
        raise ReleaseTrustError("current time must be timezone-aware UTC")
    if _timestamp(key_doc["generated_at"], "key manifest generated_at") > current:
        raise ReleaseTrustError("key manifest is dated in the future")
    if _timestamp(revocation_doc["generated_at"], "revocation generated_at") > current:
        raise ReleaseTrustError("revocation list is dated in the future")
    if not isinstance(key_doc["keys"], list) or not key_doc["keys"]:
        raise ReleaseTrustError("key manifest has no release keys")

    records: dict[str, ReleaseKey] = {}
    for item in key_doc["keys"]:
        fields = {
            "key_id",
            "public_key",
            "not_before",
            "not_after",
            "successor_key_ids",
            "predecessor_key_id",
        }
        if not isinstance(item, dict) or set(item) != fields:
            raise ReleaseTrustError("release-key record schema is invalid")
        key_id = item["key_id"]
        if not isinstance(key_id, str) or not _KEY_ID_RE.fullmatch(key_id):
            raise ReleaseTrustError("release key id is invalid")
        if key_id in records:
            raise ReleaseTrustError("key manifest contains duplicate key ids")
        try:
            public = base64.b64decode(item["public_key"], validate=True)
        except (TypeError, ValueError) as exc:
            raise ReleaseTrustError("release public key encoding is invalid") from exc
        if len(public) != 32:
            raise ReleaseTrustError("release public key length is invalid")
        starts = _timestamp(item["not_before"], f"{key_id} not_before")
        ends = _timestamp(item["not_after"], f"{key_id} not_after")
        if ends <= starts:
            raise ReleaseTrustError("release-key validity window is invalid")
        successors = item["successor_key_ids"]
        predecessor = item["predecessor_key_id"]
        if (
            not isinstance(successors, list)
            or any(not isinstance(value, str) for value in successors)
            or len(successors) != len(set(successors))
            or (predecessor is not None and not isinstance(predecessor, str))
            or predecessor == key_id
            or key_id in successors
        ):
            raise ReleaseTrustError("release-key lineage is invalid")
        records[key_id] = ReleaseKey(
            key_id, public, starts, ends, tuple(successors), predecessor
        )

    for record in records.values():
        if any(value not in records for value in record.successor_key_ids):
            raise ReleaseTrustError("release-key successor is not declared")
        if any(
            records[value].predecessor_key_id != record.key_id
            for value in record.successor_key_ids
        ):
            raise ReleaseTrustError("release-key predecessor relationship disagrees")
        if record.predecessor_key_id is not None:
            previous = records.get(record.predecessor_key_id)
            if previous is None or record.key_id not in previous.successor_key_ids:
                raise ReleaseTrustError(
                    "release-key predecessor relationship disagrees"
                )

    def visit(key_id: str, visiting: set[str], visited: set[str]) -> None:
        if key_id in visiting:
            raise ReleaseTrustError("release-key lineage contains a cycle")
        if key_id in visited:
            return
        visiting.add(key_id)
        for successor in records[key_id].successor_key_ids:
            visit(successor, visiting, visited)
        visiting.remove(key_id)
        visited.add(key_id)

    visited: set[str] = set()
    for key_id in records:
        visit(key_id, set(), visited)

    if not isinstance(revocation_doc["revoked"], list):
        raise ReleaseTrustError("revocation list entries are invalid")
    revoked: set[str] = set()
    for item in revocation_doc["revoked"]:
        if not isinstance(item, dict) or set(item) != {
            "key_id",
            "revoked_at",
            "reason_code",
        }:
            raise ReleaseTrustError("revocation record schema is invalid")
        key_id = item["key_id"]
        if not isinstance(key_id, str) or key_id not in records or key_id in revoked:
            raise ReleaseTrustError("revocation references an unknown or repeated key")
        if (
            not isinstance(item["reason_code"], str)
            or item["reason_code"] not in _REASONS
        ):
            raise ReleaseTrustError("revocation reason code is invalid")
        if _timestamp(item["revoked_at"], "revoked_at") > current:
            raise ReleaseTrustError("revocation is dated in the future")
        revoked.add(key_id)

    active = {
        key_id: record.public_key
        for key_id, record in records.items()
        if record.not_before <= current <= record.not_after and key_id not in revoked
    }
    if not active:
        raise ReleaseTrustError("no currently trusted release keys")
    return ReleaseTrustPolicy(
        MappingProxyType(active),
        MappingProxyType(records),
        hashlib.sha256(key_manifest_bytes).hexdigest(),
        hashlib.sha256(revocations_bytes).hexdigest(),
    )


def validate_resigning_provenance(
    manifest: Mapping[str, object], key_records: Mapping[str, ReleaseKey]
) -> None:
    """Require successor-signed bundles to name their prior key and manifest."""

    key_id = manifest.get("signing_key_id")
    record = key_records.get(key_id) if isinstance(key_id, str) else None
    if record is None:
        raise ReleaseTrustError("bundle signer has no signed key-manifest record")
    provenance = manifest.get("re_sign_provenance")
    if record.predecessor_key_id is None:
        if provenance is not None:
            raise ReleaseTrustError(
                "initial signing key cannot claim re-sign provenance"
            )
        return
    if not isinstance(provenance, dict) or set(provenance) != {
        "previous_key_id",
        "previous_manifest_sha256",
    }:
        raise ReleaseTrustError("re-signed bundle provenance is required")
    if provenance["previous_key_id"] != record.predecessor_key_id:
        raise ReleaseTrustError("re-signed bundle previous key does not match lineage")
    digest = provenance["previous_manifest_sha256"]
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise ReleaseTrustError("re-signed bundle previous manifest digest is invalid")
