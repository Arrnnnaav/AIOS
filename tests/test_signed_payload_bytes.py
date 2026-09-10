"""A signed payload must reach a fresh clone as the bytes that were signed.

The pin in `bundle.py` and every digest in `docs/evidence/` are computed from
the file on disk. Git, left to itself, does not promise to hand a fresh clone
those same bytes: `core.autocrlf=input` normalises CRLF to LF on the way into
the object store, so a working copy that has held CRLF since the file was
created keeps executing 17479 bytes while the repository stores 17176.

That is not a cosmetic difference. It means the reviewed bytes (what a
reviewer reads out of git) and the executed bytes (what the signed bundle
runs) are different files, which is exactly what D108 forbids -- and the
existing digest test cannot see it, because it hashes the same working copy
that produced the pin.

The invariant here is byte equality between the object store and the working
tree for every signed payload path. It *implies* the property, rather than
merely correlating with it: if the stored bytes equal the working-tree bytes,
then a fresh clone of that commit reproduces the file the pin, the signature
and the retained evidence all name (D031).
"""

import hashlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Everything the signed bundles are built from. `plugins/shared` holds the
#: canonical adapter source; each plugin's `payload/` is copied verbatim into
#: its bundle and hashed into the signed manifest.
SIGNED_GLOBS = (
    "plugins/shared/*.py",
    "plugins/sources/*/payload/**/*",
    "plugins/sources/*/index.json",
)


def _git(*args):
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )


def _tracked_signed_paths():
    listed = _git("ls-files", "-z", *SIGNED_GLOBS)
    if listed.returncode != 0:
        pytest.skip("not a git work tree")
    names = [n for n in listed.stdout.decode("utf-8").split("\0") if n]
    return sorted(names)


def test_there_are_signed_payload_paths_to_check():
    """Guards the two tests below against passing vacuously: a glob typo or a
    moved directory would otherwise make them assert over an empty list and
    report green while checking nothing (D018)."""

    paths = _tracked_signed_paths()
    assert len(paths) >= 10, paths
    assert "plugins/shared/uia_adapter.py" in paths


def test_committed_bytes_are_the_bytes_on_disk():
    """A fresh clone must execute the bytes that were signed and reviewed."""

    drifted = []
    for name in _tracked_signed_paths():
        on_disk = (ROOT / name).read_bytes()
        # The index, not HEAD: it holds exactly the bytes the next commit
        # will store, so an unstaged CRLF edit is still caught while a
        # correctly staged fix does not have to fail until it is committed.
        stored = _git("show", f":{name}").stdout
        if stored != on_disk:
            drifted.append(
                f"{name}: stored {hashlib.sha256(stored).hexdigest()[:12]} "
                f"({len(stored)} bytes) != on disk "
                f"{hashlib.sha256(on_disk).hexdigest()[:12]} ({len(on_disk)} bytes)"
            )
    assert not drifted, (
        "signed payload bytes differ between git and disk:\n" + "\n".join(drifted)
    )


def test_signed_payload_paths_are_exempt_from_eol_normalisation():
    """The mechanism that keeps the bytes equal, checked directly.

    Byte equality above is the property; this is the setting that holds it
    true for the *next* file someone adds on a Windows editor. Without it the
    two can drift apart again silently, and the drift only shows up on a
    machine that clones fresh.
    """

    unprotected = []
    for name in _tracked_signed_paths():
        attrs = _git("check-attr", "text", "--", name).stdout.decode("utf-8").strip()
        # `text: unset` is what `-text` produces: no conversion in either
        # direction, so the object store holds the bytes verbatim.
        if not attrs.endswith(": unset"):
            unprotected.append(attrs or name)
    assert not unprotected, (
        "these signed payload paths would be line-ending normalised:\n"
        + "\n".join(unprotected)
    )
