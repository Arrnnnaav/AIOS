"""A bundle must be reproducible from a clean checkout of its sources.

The 10 September PowerPoint bundle shipped two signed
`__pycache__/*.pyc` entries. `__pycache__` is untracked, so a clean checkout
has none and rebuilding there produced a different manifest: the digest bound
into a live run's authority could not be reproduced from source. A `.pyc` also
embeds the source's mtime and size, so even two builds on the same machine need
not agree.

That is D125's defect in a third guise -- bytes that depend on the machine
rather than on the tracked sources -- and it is the same reason a digest must
never be taken over something git does not store.
"""

import base64
import json
import sys
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import build_ghostplugin  # noqa: E402


@pytest.fixture()
def key(tmp_path):
    path = tmp_path / "key.b64"
    private = Ed25519PrivateKey.generate()
    raw = private.private_bytes_raw()
    path.write_text(base64.b64encode(raw).decode("ascii"), encoding="ascii")
    return path


def _payload(root: Path) -> Path:
    adapter = root / "payload" / "ghostcursor" / "adapter"
    adapter.mkdir(parents=True)
    (adapter / "thing_adapter.py").write_bytes(b"# adapter\n")
    cache = adapter / "__pycache__"
    cache.mkdir()
    (cache / "thing_adapter.cpython-312.pyc").write_bytes(b"\x00compiled\x00")
    return root


def _spec(root: Path) -> Path:
    path = root / "plugin-source.json"
    path.write_text(
        json.dumps(
            {
                "plugin_id": "ghostcursor.thing",
                "version": "1.0.0",
                "core_compatibility": {
                    "minimum": "1.0.0",
                    "maximum_exclusive": "2.0.0",
                },
                "applications": [{"kind": "executable", "value": "thing.exe"}],
                "signing_key_id": "test-key",
                "files": [],
                "trees": [
                    {
                        "source": "payload/ghostcursor/adapter",
                        "destination": "ghostcursor/adapter",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_interpreter_build_products_never_reach_a_signed_bundle(
    tmp_path, key, monkeypatch
):
    root = _payload(tmp_path)
    monkeypatch.setattr(build_ghostplugin.Path, "resolve", lambda self: self)
    monkeypatch.setattr(
        build_ghostplugin, "__file__", str(root / "tools" / "build_ghostplugin.py")
    )
    output = tmp_path / "thing.ghostplugin"

    build_ghostplugin.build(_spec(root), key, output)

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("plugin.json"))

    assert "ghostcursor/adapter/thing_adapter.py" in names
    assert not [name for name in names if ".pyc" in name or "__pycache__" in name]
    assert not [name for name in manifest["files"] if ".pyc" in name]


def test_a_payload_that_names_a_build_product_outright_is_refused():
    """A tree sweep can skip them, but a file entry naming one is a mistake in
    the specification and should say so rather than silently produce a bundle
    without the file it asked for."""

    assert build_ghostplugin._is_build_product(Path("a/__pycache__/x.cpython-312.pyc"))
    assert build_ghostplugin._is_build_product(Path("a/x.pyc"))
    assert not build_ghostplugin._is_build_product(Path("a/x.py"))


def test_the_same_sources_build_the_same_manifest_twice(tmp_path, key, monkeypatch):
    """Reproducibility is the property; excluding build products is only the
    mechanism. If a second build of untouched sources disagreed, the digest a
    live run binds would not mean anything."""

    root = _payload(tmp_path)
    monkeypatch.setattr(build_ghostplugin.Path, "resolve", lambda self: self)
    monkeypatch.setattr(
        build_ghostplugin, "__file__", str(root / "tools" / "build_ghostplugin.py")
    )
    spec = _spec(root)

    first, _ = build_ghostplugin.build(spec, key, tmp_path / "one.ghostplugin")
    # A local test run would create these between builds.
    (
        root / "payload" / "ghostcursor" / "adapter" / "__pycache__" / "later.pyc"
    ).write_bytes(b"\x00new\x00")
    second, _ = build_ghostplugin.build(spec, key, tmp_path / "two.ghostplugin")

    assert first == second
