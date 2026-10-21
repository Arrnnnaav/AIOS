"""First-party marketplace catalog (D186): a read-only, verified listing of
available .ghostplugin bundles. It reuses the store's verify_bundle, so a
tampered/unsigned/incompatible bundle is reported honestly, and a revoked
digest is marked. It must never install or change verification.
"""

from __future__ import annotations

import hashlib
import json
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ghostcursor.plugins.marketplace import (
    build_index,
    catalog,
    search,
    updates_available,
)

CORE = "1.0.0"


def _key():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return private, {"release": public}


def _bundle(
    root,
    private,
    *,
    plugin_id="ghostcursor.one",
    version="1.0.0",
    maximum="2.0.0",
    sign=True,
):
    files = {"ghostcursor/packs/index.json": b'{"packs":[],"schema_version":2}\n'}
    manifest = {
        "schema_version": 1,
        "plugin_id": plugin_id,
        "version": version,
        "plugin_api_version": 1,
        "core_compatibility": {"minimum": "0.1.0", "maximum_exclusive": maximum},
        "applications": [{"kind": "executable", "value": "One.exe"}],
        "signing_key_id": "release",
        "adapter_api": None,
        "files": {n: hashlib.sha256(r).hexdigest() for n, r in files.items()},
    }
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    path = root / f"{plugin_id}-{version}.ghostplugin"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("plugin.json", raw)
        if sign:
            archive.writestr("signature.ed25519", private.sign(raw))
        for n, r in files.items():
            archive.writestr(n, r)
    return path


def test_catalog_lists_verified_bundles_and_flags_incompatible(tmp_path):
    private, trusted = _key()
    _bundle(tmp_path, private, plugin_id="ghostcursor.one", version="1.0.0")
    # maximum below core -> verifies but incompatible
    _bundle(
        tmp_path, private, plugin_id="ghostcursor.two", version="1.0.0", maximum="0.9.0"
    )

    entries = {
        e.plugin_id: e
        for e in catalog(tmp_path, trusted_keys=trusted, core_version=CORE)
    }
    assert entries["ghostcursor.one"].signed and entries["ghostcursor.one"].compatible
    assert entries["ghostcursor.one"].applications == ("One.exe",)
    assert entries["ghostcursor.two"].compatible is False  # outside core range
    assert all(e.error == "" for e in entries.values())


def test_catalog_marks_revoked_and_reports_unreadable(tmp_path):
    private, trusted = _key()
    good = _bundle(tmp_path, private, plugin_id="ghostcursor.one")
    # a non-bundle file with the extension -> listed with an error, not dropped
    (tmp_path / "broken.ghostplugin").write_bytes(b"not a zip")

    # revoke the good bundle by its digest
    import zipfile as zf

    with zf.ZipFile(good) as a:
        raw = a.read("plugin.json")
    digest = hashlib.sha256(raw).hexdigest()

    entries = {
        e.plugin_id: e
        for e in catalog(
            tmp_path, trusted_keys=trusted, core_version=CORE, revoked=[digest]
        )
    }
    assert entries["ghostcursor.one"].revoked is True
    broken = [
        e for e in catalog(tmp_path, trusted_keys=trusted, core_version=CORE) if e.error
    ]
    assert broken and "broken" in broken[0].plugin_id


def test_catalog_does_not_trust_an_unsigned_bundle(tmp_path):
    private, trusted = _key()
    _bundle(tmp_path, private, plugin_id="ghostcursor.unsigned", sign=False)
    entries = catalog(tmp_path, trusted_keys=trusted, core_version=CORE)
    # unsigned bundle fails verification in the production trust path -> error row
    assert entries and entries[0].error


def test_is_latest_updates_and_index(tmp_path):
    private, trusted = _key()
    _bundle(tmp_path, private, plugin_id="ghostcursor.one", version="1.0.0")
    _bundle(tmp_path, private, plugin_id="ghostcursor.one", version="1.2.0")
    entries = catalog(tmp_path, trusted_keys=trusted, core_version=CORE)

    latest = {
        e.version: e.is_latest for e in entries if e.plugin_id == "ghostcursor.one"
    }
    assert latest == {"1.0.0": False, "1.2.0": True}  # highest semver wins

    # installed 1.0.0 -> an update to 1.2.0 is offered
    ups = updates_available(entries, {"ghostcursor.one": "1.0.0"})
    assert ups == [("ghostcursor.one", "1.0.0", "1.2.0")]
    assert updates_available(entries, {"ghostcursor.one": "1.2.0"}) == []  # current

    index = build_index(entries)
    assert index["index_schema_version"] == 1
    one_latest = [e for e in index["entries"] if e["version"] == "1.2.0"][0]
    assert one_latest["verified"]["is_latest"] is True
    assert one_latest["verified"]["status"] == "active"
    # author text is a separate untrusted block, verified facts are recomputed
    assert "publisher_provided" in one_latest and "verified" in one_latest


def test_search_matches_id_and_presentation(tmp_path):
    private, trusted = _key()
    path = _bundle(tmp_path, private, plugin_id="ghostcursor.slides")
    entries = catalog(tmp_path, trusted_keys=trusted, core_version=CORE)
    digest = entries[0].manifest_sha256
    pres = {digest: {"display_name": "Deck Helper", "keywords": ["powerpoint"]}}

    assert search(entries, "slides")  # matches plugin_id
    assert search(entries, "deck", presentation=pres)  # matches display_name
    assert search(entries, "powerpoint", presentation=pres)  # matches a keyword
    assert search(entries, "nomatch", presentation=pres) == []
