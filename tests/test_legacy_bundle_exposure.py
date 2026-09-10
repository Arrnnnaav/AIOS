"""Legacy signed bundles are inventoried, quarantined, and never silent.

Three `.ghostplugin` files are tracked in `plugins/bundled/`. Two of them ship
payload evidence printing a raw window handle, and neither can be re-signed:
the private keys for `ghostcursor-release-2026-1` and `-2026-2` are not
available. Deleting them is not an option either -- `platform.py` bootstraps
first-run installs from that directory.

So they are contained rather than fixed. `legacy-exposure.json` records each
one by path, plugin id, version, manifest digest, bundle digest, signing key,
and the exact files that carry an exposed field. The tests here make that
record load-bearing:

* an unlisted bundle fails, so a new one cannot arrive unnoticed;
* a listed digest that no longer matches fails, so the record cannot go stale;
* a bundle carrying an exposed field must be marked `legacy_exposed` AND must
  not be auto-enabled on first run.

This is containment with an expiry, not a privacy solution. D128 stays
**partially satisfied** until sanitised bundles replace these, which needs the
keys recovered or rotated (D129).
"""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "plugins" / "bundled"

#: The observed-value list, imported rather than copied. The first version of
#: this file duplicated six of the twelve values and described itself as a
#: mirror, so a value added to the real list would silently not be checked here
#: (D130).
from tests.test_evidence_hygiene import _OBSERVED  # noqa: E402


def _inventory():
    record = json.loads((BUNDLED / "legacy-exposure.json").read_text(encoding="utf-8"))
    return {row["path"]: row for row in record["bundles"]}


def _index():
    value = json.loads((BUNDLED / "index.json").read_text(encoding="utf-8"))
    return {row["path"]: row for row in value["bundles"]}


def _tracked_bundles():
    return sorted(path.name for path in BUNDLED.glob("*.ghostplugin"))


def test_there_are_bundles_to_account_for():
    """Non-vacuity: an empty directory would make every check below pass while
    accounting for nothing."""

    assert len(_tracked_bundles()) >= 3


def test_every_tracked_bundle_is_inventoried():
    """The scanner fails on an unlisted bundle, so one cannot arrive quietly."""

    assert set(_tracked_bundles()) == set(_inventory())


def test_every_inventoried_digest_still_matches_the_bytes():
    """A record that has drifted from the artifact it describes is worse than
    no record: it reads as a checked fact."""

    mismatched = []
    for name, row in _inventory().items():
        raw = (BUNDLED / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["bundle_sha256"]:
            mismatched.append(name)
        with zipfile.ZipFile(BUNDLED / name) as archive:
            manifest = json.loads(archive.read("plugin.json"))
        if (
            hashlib.sha256(archive_manifest_bytes(name)).hexdigest()
            != row["manifest_sha256"]
        ):
            mismatched.append(f"{name} (manifest)")
        if manifest["signing_key_id"] != row["signing_key_id"]:
            mismatched.append(f"{name} (key)")
    assert not mismatched, mismatched


def archive_manifest_bytes(name):
    with zipfile.ZipFile(BUNDLED / name) as archive:
        return archive.read("plugin.json")


def test_exposure_is_recorded_exactly_as_the_bytes_show_it():
    """The inventory's `status` must be derived from the artifact, not
    asserted. A bundle that carries a handle and is marked clean would be the
    record actively lying."""

    for name, row in _inventory().items():
        carries = []
        with zipfile.ZipFile(BUNDLED / name) as archive:
            for entry in archive.namelist():
                if not entry.endswith(".md"):
                    continue
                text = archive.read(entry).decode("utf-8", errors="ignore")
                if any(value in text for value in _OBSERVED):
                    carries.append(entry)
        assert sorted(carries) == sorted(row["exposed_files"]), name
        expected = "legacy_exposed" if carries else "clean"
        assert row["status"] == expected, name


def test_an_exposed_bundle_is_never_auto_enabled():
    """Containment: a quarantined bundle may remain installable, but a fresh
    machine must not switch it on by default."""

    index = _index()
    for name, row in _inventory().items():
        if row["status"] == "legacy_exposed":
            assert index[name]["enable_on_first_run"] is False, name


def test_a_clean_bundle_is_still_allowed_to_bootstrap():
    """Quarantine must not quietly disable everything -- that would look like
    containment while actually breaking first-run install."""

    index = _index()
    clean = [n for n, row in _inventory().items() if row["status"] == "clean"]
    assert clean
    assert any(index[name]["enable_on_first_run"] for name in clean)


@pytest.mark.parametrize(
    "field", ["plugin_id", "version", "manifest_sha256", "bundle_sha256"]
)
def test_the_inventory_records_the_fields_a_reader_needs(field):
    for row in _inventory().values():
        assert isinstance(row.get(field), str) and row[field], (field, row["path"])
