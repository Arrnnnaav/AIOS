from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ghostcursor.plugins.trust import (
    ReleaseTrustError,
    load_trust_policy,
    validate_resigning_provenance,
)


NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _signed_policy(*, revoked: bool = False, sequence: int = 1, revoked_bundles=None):
    root = Ed25519PrivateKey.generate()
    releases = [Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()]
    publics = [
        base64.b64encode(
            key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        ).decode("ascii")
        for key in releases
    ]
    keys = {
        "schema_version": 1,
        "generated_at": "2026-09-24T00:00:00Z",
        "sequence": sequence,
        "keys": [
            {
                "key_id": "release-1",
                "public_key": publics[0],
                "not_before": "2026-01-01T00:00:00Z",
                "not_after": "2027-01-01T00:00:00Z",
                "successor_key_ids": ["release-2"],
                "predecessor_key_id": None,
            },
            {
                "key_id": "release-2",
                "public_key": publics[1],
                "not_before": "2026-09-24T00:00:00Z",
                "not_after": "2027-09-24T00:00:00Z",
                "successor_key_ids": [],
                "predecessor_key_id": "release-1",
            },
        ],
    }
    revocations = {
        "schema_version": 1,
        "generated_at": "2026-09-24T00:00:00Z",
        "sequence": sequence,
        "revoked": (
            [
                {
                    "key_id": "release-1",
                    "revoked_at": "2026-09-24T00:00:00Z",
                    "reason_code": "retired",
                }
            ]
            if revoked
            else []
        ),
    }
    if revoked_bundles is not None:
        revocations["revoked_bundles"] = revoked_bundles
    key_bytes, revoke_bytes = _canonical(keys), _canonical(revocations)
    return (
        root.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ),
        key_bytes,
        root.sign(key_bytes),
        revoke_bytes,
        root.sign(revoke_bytes),
        root,
    )


def _load(*, revoked: bool = False, **overrides):
    root, keys, key_sig, revocations, revocation_sig, _root_private = _signed_policy(
        revoked=revoked
    )
    values = {
        "key_manifest_bytes": keys,
        "key_manifest_signature": key_sig,
        "revocations_bytes": revocations,
        "revocations_signature": revocation_sig,
        "root_public_key": root,
        "now": NOW,
    }
    values.update(overrides)
    return load_trust_policy(**values)


_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64


def test_revoked_bundles_are_exposed_as_digests():
    # a backward-compatible doc with no revoked_bundles -> empty set
    assert _load().revoked_bundle_digests == frozenset()

    root, keys, key_sig, rev, rev_sig, _ = _signed_policy(
        revoked_bundles=[
            {
                "manifest_sha256": _DIGEST_A,
                "revoked_at": "2026-09-24T00:00:00Z",
                "reason_code": "compromised",
            },
            {
                "manifest_sha256": _DIGEST_B,
                "revoked_at": "2026-09-20T00:00:00Z",
                "reason_code": "superseded",
            },
        ]
    )
    policy = load_trust_policy(
        key_manifest_bytes=keys,
        key_manifest_signature=key_sig,
        revocations_bytes=rev,
        revocations_signature=rev_sig,
        root_public_key=root,
        now=NOW,
    )
    assert policy.revoked_bundle_digests == frozenset({_DIGEST_A, _DIGEST_B})


@pytest.mark.parametrize(
    "bundles, match",
    [
        (
            [
                {
                    "manifest_sha256": "tooshort",
                    "revoked_at": "2026-09-24T00:00:00Z",
                    "reason_code": "retired",
                }
            ],
            "digest is invalid",
        ),
        (
            [
                {
                    "manifest_sha256": _DIGEST_A,
                    "revoked_at": "2026-09-24T00:00:00Z",
                    "reason_code": "nope",
                }
            ],
            "reason code is invalid",
        ),
        (
            [
                {
                    "manifest_sha256": _DIGEST_A,
                    "revoked_at": "2099-01-01T00:00:00Z",
                    "reason_code": "retired",
                }
            ],
            "dated in the future",
        ),
        (
            [{"manifest_sha256": _DIGEST_A, "revoked_at": "2026-09-24T00:00:00Z"}],
            "record schema is invalid",
        ),
        (
            [
                {
                    "manifest_sha256": _DIGEST_A,
                    "revoked_at": "2026-09-24T00:00:00Z",
                    "reason_code": "retired",
                },
                {
                    "manifest_sha256": _DIGEST_A,
                    "revoked_at": "2026-09-24T00:00:00Z",
                    "reason_code": "retired",
                },
            ],
            "repeated",
        ),
    ],
)
def test_revoked_bundles_bad_shapes_are_rejected(bundles, match):
    root, keys, key_sig, rev, rev_sig, _ = _signed_policy(revoked_bundles=bundles)
    with pytest.raises(ReleaseTrustError, match=match):
        load_trust_policy(
            key_manifest_bytes=keys,
            key_manifest_signature=key_sig,
            revocations_bytes=rev,
            revocations_signature=rev_sig,
            root_public_key=root,
            now=NOW,
        )


def test_revoked_bundles_tamper_breaks_the_signature():
    # adding revoked_bundles after signing (not re-signed) must be rejected
    root, keys, key_sig, rev, rev_sig, _ = _signed_policy()
    tampered = rev[:-2] + b',"revoked_bundles":[]}\n'  # not canonical / not signed
    with pytest.raises(ReleaseTrustError):
        load_trust_policy(
            key_manifest_bytes=keys,
            key_manifest_signature=key_sig,
            revocations_bytes=tampered,
            revocations_signature=rev_sig,
            root_public_key=root,
            now=NOW,
        )


def test_signed_policy_loads_only_in_window_unrevoked_keys():
    policy = _load()

    assert set(policy.trusted_keys) == {"release-1", "release-2"}
    assert policy.key_records["release-2"].predecessor_key_id == "release-1"


def test_tampered_key_manifest_or_revocation_list_is_rejected():
    root, keys, key_sig, revocations, revoke_sig, _root_private = _signed_policy()

    with pytest.raises(ReleaseTrustError, match="key manifest signature"):
        load_trust_policy(
            key_manifest_bytes=keys + b" ",
            key_manifest_signature=key_sig,
            revocations_bytes=revocations,
            revocations_signature=revoke_sig,
            root_public_key=root,
            now=NOW,
        )

    with pytest.raises(ReleaseTrustError, match="revocation signature"):
        load_trust_policy(
            key_manifest_bytes=keys,
            key_manifest_signature=key_sig,
            revocations_bytes=revocations + b" ",
            revocations_signature=revoke_sig,
            root_public_key=root,
            now=NOW,
        )


def test_expired_or_revoked_signing_keys_are_not_trusted():
    root, keys, key_sig, revocations, revoke_sig, _root_private = _signed_policy(
        revoked=True
    )
    policy = load_trust_policy(
        key_manifest_bytes=keys,
        key_manifest_signature=key_sig,
        revocations_bytes=revocations,
        revocations_signature=revoke_sig,
        root_public_key=root,
        now=NOW,
    )
    assert set(policy.trusted_keys) == {"release-2"}

    with pytest.raises(ReleaseTrustError, match="no currently trusted release keys"):
        _load(now=datetime(2028, 1, 1, tzinfo=timezone.utc))


def test_inconsistent_successor_relationship_is_rejected():
    root, keys, _key_sig, revocations, revoke_sig, root_private = _signed_policy()
    value = json.loads(keys)
    value["keys"][1]["predecessor_key_id"] = None
    changed = _canonical(value)
    with pytest.raises(ReleaseTrustError, match="predecessor relationship"):
        load_trust_policy(
            key_manifest_bytes=changed,
            key_manifest_signature=root_private.sign(changed),
            revocations_bytes=revocations,
            revocations_signature=revoke_sig,
            root_public_key=root,
            now=NOW,
        )


def test_rotation_requires_bundle_bound_previous_key_and_manifest_digest():
    policy = _load()
    manifest = {
        "signing_key_id": "release-2",
        "re_sign_provenance": {
            "previous_key_id": "release-1",
            "previous_manifest_sha256": hashlib.sha256(b"previous").hexdigest(),
        },
    }
    validate_resigning_provenance(manifest, policy.key_records)

    for bad in (
        None,
        {"previous_key_id": "release-2", "previous_manifest_sha256": "0" * 64},
        {"previous_key_id": "release-1", "previous_manifest_sha256": "not-a-digest"},
    ):
        with pytest.raises(ReleaseTrustError):
            validate_resigning_provenance(
                {**manifest, "re_sign_provenance": bad}, policy.key_records
            )


def test_a_key_naming_a_predecessor_that_does_not_list_it_is_rejected():
    """The other half of the lineage: release-2 claims release-1 as its
    predecessor, but release-1 no longer lists release-2 as a successor."""

    root, keys, _key_sig, revocations, revoke_sig, root_private = _signed_policy()
    value = json.loads(keys)
    value["keys"][0]["successor_key_ids"] = []
    changed = _canonical(value)
    with pytest.raises(ReleaseTrustError, match="predecessor relationship"):
        load_trust_policy(
            key_manifest_bytes=changed,
            key_manifest_signature=root_private.sign(changed),
            revocations_bytes=revocations,
            revocations_signature=revoke_sig,
            root_public_key=root,
            now=NOW,
        )


def test_replaying_an_older_revocation_list_is_refused():
    """A validly signed but older list would otherwise un-revoke a key."""

    newer = _load(revoked=True, **{})
    assert newer.revocations_sequence == 1
    root, keys, key_sig, revocations, revoke_sig, _root_private = _signed_policy(
        revoked=False
    )
    with pytest.raises(ReleaseTrustError, match="older than one already accepted"):
        load_trust_policy(
            key_manifest_bytes=keys,
            key_manifest_signature=key_sig,
            revocations_bytes=revocations,
            revocations_signature=revoke_sig,
            root_public_key=root,
            revocations_floor=2,
            now=NOW,
        )
    with pytest.raises(ReleaseTrustError, match="older than one already accepted"):
        load_trust_policy(
            key_manifest_bytes=keys,
            key_manifest_signature=key_sig,
            revocations_bytes=revocations,
            revocations_signature=revoke_sig,
            root_public_key=root,
            key_manifest_floor=2,
            now=NOW,
        )


@pytest.mark.parametrize("sequence", [0, -1])
def test_a_non_positive_sequence_is_rejected(sequence):
    root, keys, key_sig, revocations, revoke_sig, _ = _signed_policy(sequence=sequence)
    with pytest.raises(ReleaseTrustError, match="sequence is invalid"):
        load_trust_policy(
            key_manifest_bytes=keys,
            key_manifest_signature=key_sig,
            revocations_bytes=revocations,
            revocations_signature=revoke_sig,
            root_public_key=root,
            now=NOW,
        )


def test_the_accepted_sequences_are_returned_for_the_caller_to_persist():
    policy = _load()
    assert (policy.key_manifest_sequence, policy.revocations_sequence) == (1, 1)
