"""An operation must say how it acts, and prove it holds what it acts on.

The backend field decides whether a pointer may ever be drawn for an
operation (D109), so a registry that gets it wrong is a registry that can
show a cursor over a control nothing clicked.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from ghostcursor.action import (
    OPERATION_BACKENDS,
    UIA_PATTERNS,
    ActionValidationError,
    load_operation_registry,
)

ADAPTER = "b" * 64
SELECTOR = "c" * 64


def _uia(**overrides):
    block = {
        "control_type": "Button",
        "evidence_identity_fields": ["automation_id"],
        "identity_mode": "runtime_id_required",
        "pattern": "Invoke",
        "required_identity_fields": ["control_type", "name", "runtime_id"],
        "selector_id": "powerpoint.new-slide",
        "selector_sha256": SELECTOR,
    }
    block.update(overrides)
    return block


def _operation(**overrides):
    item = {
        "effect_key_fields": [],
        "parameters": {},
        "postconditions": [],
        "preconditions": [],
        "risk": "low",
        "safe_to_repeat": False,
        "timeout_s": 20.0,
    }
    item.update(overrides)
    return item


def _registry(operations):
    payload = {
        "operations": operations,
        "plugin_id": "ghostcursor.powerpoint",
        "plugin_version": "1.0.0",
        "schema_version": 1,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return load_operation_registry(
        raw,
        plugin_id="ghostcursor.powerpoint",
        plugin_version="1.0.0",
        adapter_sha256=ADAPTER,
    )


# --- backward compatibility is the whole reason the fields are optional ----


def test_a_registry_signed_before_uia_support_still_validates():
    """Making `backend` required would have changed the bytes of every signed
    registry and invalidated its digest."""

    registry = _registry({"powerpoint.add_slide": _operation()})
    spec = registry.operations["powerpoint.add_slide"]

    assert spec.backend == "object_model"
    assert spec.uia_pattern is None
    assert spec.identity is None


def test_the_real_powerpoint_registry_still_loads_unchanged():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "plugins/sources/powerpoint/payload/ghostcursor/operations.json"
    )
    raw = source.read_bytes()
    adapter = (
        Path(__file__).resolve().parents[1]
        / "plugins/sources/powerpoint/payload/ghostcursor/adapter/powerpoint_adapter.py"
    )
    registry = load_operation_registry(
        raw,
        plugin_id="ghostcursor.powerpoint",
        plugin_version="1.0.0",
        adapter_sha256=hashlib.sha256(adapter.read_bytes()).hexdigest(),
    )

    assert registry.operations
    assert all(spec.backend == "object_model" for spec in registry.operations.values())


# --- the pointer rule, at the schema level --------------------------------


def test_an_object_model_operation_may_never_draw_a_pointer():
    """D109: it has no control it is clicking, so a pointer over one would
    show an action where it did not happen."""

    registry = _registry({"powerpoint.add_text": _operation()})

    assert registry.operations["powerpoint.add_text"].draws_a_pointer is False


@pytest.mark.parametrize("backend", ["uia_pattern", "legacy_iaccessible"])
def test_a_control_driving_operation_may_draw_a_pointer(backend):
    pattern = "Invoke" if backend == "uia_pattern" else "DoDefaultAction"
    registry = _registry(
        {"powerpoint.new_slide": _operation(backend=backend, uia=_uia(pattern=pattern))}
    )

    assert registry.operations["powerpoint.new_slide"].draws_a_pointer is True


# --- the backend and its block must agree ---------------------------------


def test_an_object_model_operation_may_not_carry_a_uia_block():
    with pytest.raises(ActionValidationError, match="declares a uia block"):
        _registry({"powerpoint.add_text": _operation(uia=_uia())})


def test_a_uia_operation_without_its_block_is_refused():
    with pytest.raises(ActionValidationError, match="uia block is invalid"):
        _registry({"powerpoint.new_slide": _operation(backend="uia_pattern")})


def test_an_unknown_backend_is_refused():
    with pytest.raises(ActionValidationError, match="backend"):
        _registry({"powerpoint.new_slide": _operation(backend="vision")})


def test_an_unknown_field_is_still_refused():
    """The optional keys widen the set; they do not open it."""

    with pytest.raises(ActionValidationError, match="fields are invalid"):
        _registry({"powerpoint.add_text": _operation(colour="blue")})


def test_a_missing_required_field_is_still_refused():
    item = _operation()
    del item["risk"]

    with pytest.raises(ActionValidationError, match="fields are invalid"):
        _registry({"powerpoint.add_text": item})


# --- the pattern must be one the adapter can dispatch ---------------------


def test_a_pattern_the_adapter_cannot_dispatch_is_refused():
    """An operation naming a pattern nothing dispatches is an operation
    nothing can perform."""

    with pytest.raises(ActionValidationError, match="not a .*dispatchable"):
        _registry(
            {
                "powerpoint.new_slide": _operation(
                    backend="uia_pattern", uia=_uia(pattern="ExpandCollapse")
                )
            }
        )


def test_the_legacy_backend_must_name_the_default_action_not_a_pattern():
    """It is not a UIA pattern and must not borrow a pattern name it does not
    dispatch."""

    with pytest.raises(ActionValidationError, match="must declare DoDefaultAction"):
        _registry(
            {
                "powerpoint.new_slide": _operation(
                    backend="legacy_iaccessible", uia=_uia(pattern="Invoke")
                )
            }
        )


def test_a_true_pattern_may_not_be_declared_on_the_legacy_backend():
    registry = _registry(
        {
            "powerpoint.new_slide": _operation(
                backend="legacy_iaccessible", uia=_uia(pattern="DoDefaultAction")
            )
        }
    )

    assert registry.operations["powerpoint.new_slide"].uia_pattern == "DoDefaultAction"


@pytest.mark.parametrize("pattern", sorted(UIA_PATTERNS))
def test_every_declared_pattern_is_accepted(pattern):
    registry = _registry(
        {"powerpoint.op": _operation(backend="uia_pattern", uia=_uia(pattern=pattern))}
    )

    assert registry.operations["powerpoint.op"].uia_pattern == pattern


# --- the identity policy is parsed, not merely carried --------------------


def test_the_signed_identity_policy_reaches_the_spec():
    registry = _registry(
        {"powerpoint.new_slide": _operation(backend="uia_pattern", uia=_uia())}
    )
    identity = registry.operations["powerpoint.new_slide"].identity

    assert identity.control_type == "Button"
    assert identity.identity_mode == "runtime_id_required"
    assert identity.required_fields == ("control_type", "name", "runtime_id")
    assert identity.evidence_fields == ("automation_id",)
    assert identity.selector_sha256 == SELECTOR


def test_an_identity_policy_the_module_would_refuse_is_refused_here_too():
    """runtime_id_required that does not require runtime_id."""

    with pytest.raises(ActionValidationError, match="identity policy is invalid"):
        _registry(
            {
                "powerpoint.new_slide": _operation(
                    backend="uia_pattern",
                    uia=_uia(required_identity_fields=["control_type", "name"]),
                )
            }
        )


def test_a_malformed_uia_block_shape_is_refused():
    block = _uia()
    del block["control_type"]

    with pytest.raises(ActionValidationError, match="uia block is invalid"):
        _registry(
            {"powerpoint.new_slide": _operation(backend="uia_pattern", uia=block)}
        )


@pytest.mark.parametrize(
    "label", ["required_identity_fields", "evidence_identity_fields"]
)
def test_identity_fields_must_be_a_list_of_strings(label):
    with pytest.raises(ActionValidationError):
        _registry(
            {
                "powerpoint.new_slide": _operation(
                    backend="uia_pattern", uia=_uia(**{label: "control_type"})
                )
            }
        )


def test_the_backend_vocabulary_is_closed():
    assert OPERATION_BACKENDS == {
        "object_model",
        "uia_pattern",
        "legacy_iaccessible",
    }
