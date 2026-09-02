"""A selector is a query, and a query can start matching something else.

Every case here is a way Act could resolve a different control than the one
its approval was bound to and act on it anyway. The measured policy is Excel's
`Add Sheet` (docs/evidence/act-phase-b-uia-feasibility.md): Button,
AutomationId SheetTab, InvokePattern, RuntimeId stable 100/100 across the cue
dwell.
"""

from __future__ import annotations

import pytest

from ghostcursor.uia_identity import (
    IDENTITY_FIELDS,
    IdentityPolicy,
    IdentityPolicyError,
    compare_identity,
    identity_evidence,
)


DIGEST = "a" * 64


def _policy(**overrides) -> IdentityPolicy:
    values = {
        "control_type": "Button",
        "evidence_fields": ("automation_id", "native_window_handle"),
        "identity_mode": "runtime_id_required",
        "operation_id": "uia.invoke",
        "required_fields": ("control_type", "name", "runtime_id"),
        "selector_id": "excel.add-sheet",
        "selector_sha256": DIGEST,
    }
    values.update(overrides)
    return IdentityPolicy(**values)


def _observed(**overrides):
    values = {
        "automation_id": "SheetTab",
        "control_type": "Button",
        "name": "Add Sheet",
        "native_window_handle": None,
        "runtime_id": (7, 197698, 4, 1),
    }
    values.update(overrides)
    return values


# --- the measured Excel policy ---------------------------------------------


def test_the_measured_excel_control_passes_its_own_policy():
    assert compare_identity(_policy(), _observed(), _observed(), match_count=1) == ()


def test_a_moved_runtime_id_refuses_when_the_mode_requires_it():
    """Excel measured 100/100 stable, so a change here is a real substitution,
    not the churn D037 measured in VS Code."""

    reasons = compare_identity(
        _policy(), _observed(), _observed(runtime_id=(7, 197698, 4, 2)), match_count=1
    )

    assert any("runtime_id" in reason for reason in reasons)


def test_a_different_control_with_the_same_name_refuses_on_control_type():
    reasons = compare_identity(
        _policy(), _observed(), _observed(control_type="TabItem"), match_count=1
    )

    assert any("control_type" in reason for reason in reasons)


def test_a_renamed_control_refuses():
    reasons = compare_identity(
        _policy(), _observed(), _observed(name="Insert Worksheet"), match_count=1
    )

    assert any("name" in reason for reason in reasons)


@pytest.mark.parametrize("count", [0, 2, 7])
def test_a_selector_that_stopped_matching_exactly_one_refuses(count):
    reasons = compare_identity(_policy(), _observed(), _observed(), match_count=count)

    assert any("not exactly one" in reason for reason in reasons)


def test_a_runtime_id_list_and_tuple_are_the_same_identity():
    """The wire carries a list; the observer captures a tuple. That is a
    serialization difference, not a substitution."""

    assert (
        compare_identity(
            _policy(),
            _observed(runtime_id=[7, 197698, 4, 1]),
            _observed(runtime_id=(7, 197698, 4, 1)),
            match_count=1,
        )
        == ()
    )


# --- evidence fields never refuse ------------------------------------------


def test_an_evidence_field_that_changed_does_not_refuse():
    """Recording an unstable value and then comparing it is how a correct
    refusal becomes a flaky one."""

    assert (
        compare_identity(
            _policy(), _observed(), _observed(native_window_handle=999), match_count=1
        )
        == ()
    )


def test_a_missing_required_field_refuses_on_either_side():
    baseline = _observed()
    del baseline["runtime_id"]

    assert compare_identity(_policy(), baseline, _observed(), match_count=1) != ()

    observed = _observed()
    del observed["runtime_id"]

    assert compare_identity(_policy(), _observed(), observed, match_count=1) != ()


def test_a_positional_automation_id_refuses_even_as_evidence_only():
    """It encodes a list index, so a match proves only that something still
    occupies that position (D069)."""

    reasons = compare_identity(
        _policy(), _observed(), _observed(automation_id="list_id_2_3"), match_count=1
    )

    assert any("positional" in reason for reason in reasons)


# --- the policy itself is constrained --------------------------------------


def test_runtime_id_required_must_actually_require_runtime_id():
    with pytest.raises(IdentityPolicyError, match="must require runtime_id"):
        _policy(required_fields=("control_type", "name"))


def test_semantic_mode_may_not_require_the_identity_it_says_is_unstable():
    """Requiring it turns a measured instability into an intermittent
    refusal."""

    with pytest.raises(IdentityPolicyError, match="must not require runtime_id"):
        _policy(
            identity_mode="semantic_exactly_one",
            required_fields=("control_type", "name", "runtime_id"),
            evidence_fields=(),
        )


def test_semantic_mode_rests_on_the_trusted_name():
    with pytest.raises(IdentityPolicyError, match="must require it"):
        _policy(
            identity_mode="semantic_exactly_one",
            required_fields=("control_type",),
            evidence_fields=(),
        )


def test_a_semantic_policy_is_accepted_when_it_names_what_it_rests_on():
    policy = _policy(
        identity_mode="semantic_exactly_one",
        required_fields=("control_type", "name"),
        evidence_fields=("runtime_id", "automation_id"),
    )

    assert policy.identity_mode == "semantic_exactly_one"


def test_control_type_can_never_be_opted_out_of():
    with pytest.raises(IdentityPolicyError, match="must require"):
        _policy(required_fields=("name", "runtime_id"))


def test_a_field_may_not_be_both_required_and_evidence_only():
    """Allowing both makes the stronger role decorative."""

    with pytest.raises(IdentityPolicyError, match="both required and evidence"):
        _policy(evidence_fields=("name",))


def test_an_unknown_identity_field_is_refused():
    """A policy naming a field the observer never captures would be satisfied
    by its absence."""

    with pytest.raises(IdentityPolicyError, match="unknown field"):
        _policy(required_fields=("control_type", "name", "runtime_id", "colour"))


def test_an_unknown_identity_mode_is_refused():
    with pytest.raises(IdentityPolicyError, match="identity mode"):
        _policy(identity_mode="trust_me")


def test_a_malformed_selector_digest_is_refused():
    with pytest.raises(IdentityPolicyError, match="digest"):
        _policy(selector_sha256="short")


# --- the run record separates what refuses from what is noted --------------


def test_evidence_records_required_and_evidence_fields_separately():
    """A reader has to be able to tell which values a refusal would have fired
    on from which were only recorded."""

    record = identity_evidence(_policy(), _observed())

    assert set(record["required"]) == {"control_type", "name", "runtime_id"}
    assert set(record["evidence"]) == {"automation_id", "native_window_handle"}
    assert record["identity_mode"] == "runtime_id_required"
    assert record["selector_sha256"] == DIGEST


def test_every_declared_identity_field_is_one_the_probe_can_observe():
    """Binds this vocabulary to what Phase B actually measured."""

    from ghostcursor.devtools.uia_feasibility import ObservedTarget

    observable = set(ObservedTarget.__dataclass_fields__)
    # legacy_* are read from the LegacyIAccessible pattern rather than being
    # ObservedTarget fields; everything else must be directly observable.
    assert IDENTITY_FIELDS - {"legacy_child_id", "legacy_role"} <= observable | {
        "native_window_handle"
    }
