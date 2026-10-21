"""Signed revocation policy wiring (D186 Bucket-2): platform.signed_revoked_digests
loads a root-signed revocation list into PluginStore.revoked_digests. Not
configured -> empty; configured-but-broken -> fail closed (raise), never a
silent fall-back that would un-revoke a bundle.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ghostcursor.plugins.platform import signed_revoked_digests
from ghostcursor.plugins.trust import ReleaseTrustError

_DIGEST = "c" * 64


def _canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _b64raw(key) -> str:
    return base64.b64encode(
        key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    ).decode("ascii")


def _write_trust_dir(d: Path, digests=(_DIGEST,)):
    d.mkdir(parents=True, exist_ok=True)
    root = Ed25519PrivateKey.generate()
    release = Ed25519PrivateKey.generate()
    keys = {
        "schema_version": 1,
        "generated_at": "2026-01-01T00:00:00Z",
        "sequence": 1,
        "keys": [
            {
                "key_id": "release",
                "public_key": _b64raw(release.public_key()),
                "not_before": "2026-01-01T00:00:00Z",
                "not_after": "2030-01-01T00:00:00Z",
                "successor_key_ids": [],
                "predecessor_key_id": None,
            }
        ],
    }
    revs = {
        "schema_version": 1,
        "generated_at": "2026-01-01T00:00:00Z",
        "sequence": 1,
        "revoked": [],
        "revoked_bundles": [
            {
                "manifest_sha256": h,
                "revoked_at": "2026-01-01T00:00:00Z",
                "reason_code": "compromised",
            }
            for h in digests
        ],
    }
    kb, rb = _canonical(keys), _canonical(revs)
    (d / "root.b64").write_text(_b64raw(root.public_key()), encoding="utf-8")
    (d / "key-manifest.json").write_bytes(kb)
    (d / "key-manifest.sig").write_bytes(root.sign(kb))
    (d / "revocations.json").write_bytes(rb)
    (d / "revocations.sig").write_bytes(root.sign(rb))


def test_not_configured_means_no_revocations(tmp_path):
    assert signed_revoked_digests(tmp_path / "absent") == frozenset()


def test_valid_signed_policy_yields_the_revoked_digests(tmp_path):
    trust = tmp_path / "trust"
    _write_trust_dir(trust)
    assert signed_revoked_digests(trust) == frozenset({_DIGEST})


def test_tampered_revocation_list_fails_closed(tmp_path):
    trust = tmp_path / "trust"
    _write_trust_dir(trust)
    # flip a byte in the signed revocation body without re-signing
    body = (trust / "revocations.json").read_bytes()
    (trust / "revocations.json").write_bytes(body.replace(b"compromised", b"retired  "))
    with pytest.raises(ReleaseTrustError):
        signed_revoked_digests(trust)


def test_configured_but_missing_a_document_fails_closed(tmp_path):
    trust = tmp_path / "trust"
    _write_trust_dir(trust)
    (trust / "revocations.sig").unlink()  # present dir, missing file
    with pytest.raises((OSError, ReleaseTrustError)):
        signed_revoked_digests(trust)
