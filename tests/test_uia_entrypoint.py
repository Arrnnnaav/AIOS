"""One plugin, two signed adapters, and no way for them to disagree.

PowerPoint owns its application, capabilities, selectors, plans and
verification. It ships an object-model adapter and, when any operation
declares a UIA backend, the canonical shared adapter alongside it — both
inside the same signed payload, so both execution paths are digest-bound
together and disabling the plugin removes both (D108).

Core selects between them by the OPERATION's signed backend declaration. Never
by anything a model produced.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ghostcursor.plugins.bundle import (
    CANONICAL_UIA_ADAPTER_SHA256,
    BundleVerificationError,
    _check_backend_declarations,
)

SHARED = Path(__file__).resolve().parents[1] / "plugins" / "shared" / "uia_adapter.py"


class _Spec:
    def __init__(self, backend):
        self.backend = backend


class _Registry:
    def __init__(self, backends):
        self.operations = {
            f"powerpoint.op{index}": _Spec(backend)
            for index, backend in enumerate(backends)
        }


def _files(uia_bytes=None, path="ghostcursor/adapter/uia_adapter.py"):
    files = {"ghostcursor/adapter/powerpoint_adapter.py": b"# object model"}
    if uia_bytes is not None:
        files[path] = uia_bytes
    return files


def _adapter(uia_entrypoint=None):
    adapter = {
        "entrypoint": "ghostcursor/adapter/powerpoint_adapter.py",
        "operations": "ghostcursor/operations.json",
        "plans": "ghostcursor/action-plans.json",
        "protocol_version": 1,
        "verifier": "ghostcursor/adapter/powerpoint_verifier.py",
    }
    if uia_entrypoint is not None:
        adapter["uia_entrypoint"] = uia_entrypoint
    return adapter


# --- the canonical digest is a real property of the shared source ---------


def test_the_pinned_digest_is_the_canonical_sources_own_digest():
    """If these drift, every plugin shipping the shared adapter is refused --
    which is the correct direction, but the pin has to be maintained with the
    source rather than guessed."""

    assert (
        CANONICAL_UIA_ADAPTER_SHA256 == hashlib.sha256(SHARED.read_bytes()).hexdigest()
    )


# --- the entrypoint is allowed only when an operation needs it ------------


def test_a_plugin_with_no_uia_operation_ships_no_uia_adapter():
    _check_backend_declarations(
        _adapter(), _Registry(["object_model", "object_model"]), _files()
    )


def test_declaring_a_uia_backend_without_shipping_the_adapter_is_refused():
    """An operation whose backend nothing can dispatch."""

    with pytest.raises(BundleVerificationError, match="no uia_entrypoint is shipped"):
        _check_backend_declarations(
            _adapter(), _Registry(["object_model", "uia_pattern"]), _files()
        )


def test_shipping_the_adapter_with_no_uia_operation_is_refused():
    """An unused executable is an unreviewed one: nothing exercises it and
    nothing in the registry says what it may do."""

    with pytest.raises(
        BundleVerificationError, match="no operation declares a UIA backend"
    ):
        _check_backend_declarations(
            _adapter("ghostcursor/adapter/uia_adapter.py"),
            _Registry(["object_model"]),
            _files(SHARED.read_bytes()),
        )


@pytest.mark.parametrize("backend", ["uia_pattern", "legacy_iaccessible"])
def test_either_control_driving_backend_requires_the_adapter(backend):
    with pytest.raises(BundleVerificationError, match="no uia_entrypoint"):
        _check_backend_declarations(_adapter(), _Registry([backend]), _files())


# --- the shipped bytes must be the reviewed bytes -------------------------


def test_a_matching_copy_of_the_canonical_adapter_is_accepted():
    _check_backend_declarations(
        _adapter("ghostcursor/adapter/uia_adapter.py"),
        _Registry(["uia_pattern"]),
        _files(SHARED.read_bytes()),
    )


def test_a_drifted_copy_of_the_shared_adapter_is_refused():
    """One review covers every copy only while every copy is identical."""

    drifted = SHARED.read_bytes() + b"\n# local tweak\n"

    with pytest.raises(BundleVerificationError, match="do not match the canonical"):
        _check_backend_declarations(
            _adapter("ghostcursor/adapter/uia_adapter.py"),
            _Registry(["uia_pattern"]),
            _files(drifted),
        )


def test_a_declared_adapter_absent_from_the_payload_is_refused():
    with pytest.raises(BundleVerificationError, match="not present in the signed"):
        _check_backend_declarations(
            _adapter("ghostcursor/adapter/uia_adapter.py"),
            _Registry(["uia_pattern"]),
            _files(),
        )


# --- the manifest-level shape --------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("ghostcursor/adapter/powerpoint_adapter.py", "distinct from the entrypoint"),
        ("ghostcursor/adapter/powerpoint_verifier.py", "distinct from the entrypoint"),
    ],
)
def test_the_uia_entrypoint_may_not_reuse_another_executables_path(path, expected):
    """Sharing the entrypoint would let one file answer for two backends;
    sharing the verifier would let the thing that checks an effect cause one."""

    from ghostcursor.plugins.bundle import (
        BundleVerificationError,
        verify_adapter_shape,
    )

    with pytest.raises(BundleVerificationError, match=expected):
        verify_adapter_shape(_adapter(path))


@pytest.mark.parametrize(
    "path",
    [
        "ghostcursor/uia_adapter.py",
        "ghostcursor/adapter/uia_adapter.txt",
        "../uia_adapter.py",
        "ghostcursor/adapter/../../escape.py",
    ],
)
def test_the_uia_entrypoint_must_resolve_inside_the_signed_adapter_directory(path):
    from ghostcursor.plugins.bundle import (
        BundleVerificationError,
        verify_adapter_shape,
    )

    # Two guards can catch these: the generic unsafe-entry check rejects a
    # traversal before the uia_entrypoint rule is reached. Both are correct
    # refusals, so the property under test is that it is refused at all.
    with pytest.raises(
        BundleVerificationError, match="uia_entrypoint|unsafe bundle entry"
    ):
        verify_adapter_shape(_adapter(path))


def test_a_non_string_uia_entrypoint_is_refused():
    from ghostcursor.plugins.bundle import (
        BundleVerificationError,
        verify_adapter_shape,
    )

    with pytest.raises(BundleVerificationError, match="must be a string"):
        verify_adapter_shape(_adapter(42))


def test_an_unknown_adapter_field_is_still_refused():
    """The optional key widens the set; it does not open it."""

    from ghostcursor.plugins.bundle import (
        BundleVerificationError,
        verify_adapter_shape,
    )

    adapter = _adapter("ghostcursor/adapter/uia_adapter.py")
    adapter["extra"] = "x"

    with pytest.raises(BundleVerificationError, match="closed adapter declaration"):
        verify_adapter_shape(adapter)


def test_a_bundle_without_the_optional_key_still_verifies():
    from ghostcursor.plugins.bundle import verify_adapter_shape

    verify_adapter_shape(_adapter())


@pytest.mark.parametrize(
    "field", ["entrypoint", "operations", "plans", "protocol_version", "verifier"]
)
def test_a_missing_required_adapter_field_is_refused(field):
    """Widening the set for `uia_entrypoint` must not have made the required
    ones optional."""

    from ghostcursor.plugins.bundle import (
        BundleVerificationError,
        verify_adapter_shape,
    )

    adapter = _adapter()
    del adapter[field]

    with pytest.raises(BundleVerificationError, match="closed adapter declaration"):
        verify_adapter_shape(adapter)
