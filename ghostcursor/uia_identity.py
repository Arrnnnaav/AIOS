"""What a signed operation must prove about the control it is about to drive.

A UIA action names a control by selector, but a selector is a query and a
query can start matching something else. Between the moment Act observes a
control and the moment it acts on it there is a cue, a confirmation, and a
process boundary -- and the tree is free to change throughout. This decides
what has to still be true at the instant of the call.

**The policy is per operation and signed.** It is not a global rule, because
what identifies a control is a property of the application: Excel's
`Add Sheet` holds a stable RuntimeId across the cue dwell (measured 100/100,
`docs/evidence/act-phase-b-uia-feasibility.md`), while D037 measured VS Code's
element set churning ~10% in steady state with no user action. A single rule
would either refuse Excel needlessly or accept VS Code unsafely.

**A field is either required or evidence.** Required fields are compared
immediately before the pattern call and any difference refuses. Evidence
fields are recorded so a run record can be read afterwards, and are never
compared -- recording an unstable value and then comparing it is how a
correct refusal becomes a flaky one.

**Positional AutomationIds are refused outright**, in either role. They encode
a list index rather than a control (D069), so a match proves only that
something still occupies that position.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ghostcursor.reasoning.schema import is_positional_automation_id

#: Identity fields an operation may name. Closed: a policy naming a field the
#: observer never captures would be satisfied by its absence.
IDENTITY_FIELDS = frozenset(
    {
        "automation_id",
        "control_type",
        "legacy_child_id",
        "legacy_role",
        "name",
        "native_window_handle",
        "runtime_id",
    }
)

#: Always compared, whatever the operation says. These are the boundary the
#: approval itself was bound to; an operation cannot opt out of them.
ALWAYS_REQUIRED = ("control_type",)

#: How a control is allowed to be identified when RuntimeId cannot be.
IDENTITY_MODES = frozenset({"runtime_id_required", "semantic_exactly_one"})


class IdentityPolicyError(ValueError):
    """A policy or a comparison that must refuse before any effect."""


@dataclass(frozen=True)
class IdentityPolicy:
    """One signed operation's rule for proving it holds its target."""

    operation_id: str
    selector_id: str
    selector_sha256: str
    control_type: str
    identity_mode: str
    required_fields: tuple[str, ...]
    evidence_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.operation_id or not self.selector_id:
            raise IdentityPolicyError("identity policy needs an operation and selector")
        if len(self.selector_sha256) != 64:
            raise IdentityPolicyError("identity policy selector digest is invalid")
        if self.identity_mode not in IDENTITY_MODES:
            raise IdentityPolicyError(
                f"identity mode {self.identity_mode!r} is unknown"
            )
        unknown = (
            set(self.required_fields) | set(self.evidence_fields)
        ) - IDENTITY_FIELDS
        if unknown:
            raise IdentityPolicyError(
                "identity policy names unknown field(s) " + ", ".join(sorted(unknown))
            )
        both = set(self.required_fields) & set(self.evidence_fields)
        if both:
            # A field cannot be the thing that refuses and the thing that is
            # merely noted. Allowing both makes the stronger role decorative.
            raise IdentityPolicyError(
                "identity policy makes "
                + ", ".join(sorted(both))
                + " both required and evidence-only"
            )
        missing = set(ALWAYS_REQUIRED) - set(self.required_fields)
        if missing:
            raise IdentityPolicyError(
                "identity policy must require " + ", ".join(sorted(missing))
            )
        if self.identity_mode == "runtime_id_required":
            if "runtime_id" not in self.required_fields:
                raise IdentityPolicyError("runtime_id_required must require runtime_id")
        elif "runtime_id" in self.required_fields:
            # Requiring an identity the mode says is not dependable turns a
            # measured instability into an intermittent refusal.
            raise IdentityPolicyError(
                "semantic_exactly_one must not require runtime_id; measure it "
                "and change the mode instead"
            )
        if (
            self.identity_mode == "semantic_exactly_one"
            and "name" not in self.required_fields
        ):
            raise IdentityPolicyError(
                "semantic_exactly_one rests on the trusted name and must require it"
            )


def _comparable(value: Any) -> Any:
    """Normalise for comparison without making unlike things alike."""

    if isinstance(value, (list, tuple)):
        return tuple(value)
    return value


def compare_identity(
    policy: IdentityPolicy,
    baseline: Mapping[str, Any],
    observed: Mapping[str, Any],
    *,
    match_count: int,
) -> tuple[str, ...]:
    """Every reason the resolved control is not the authorized one.

    Empty means the pattern call may proceed. Checked immediately before the
    call, against the identity captured when the action was authorized.
    """

    reasons: list[str] = []
    if match_count != 1:
        reasons.append(
            f"selector {policy.selector_id!r} matched {match_count} controls, "
            "not exactly one"
        )
    for field in policy.required_fields:
        if field not in baseline:
            reasons.append(f"the authorized identity carries no {field}")
            continue
        if field not in observed:
            reasons.append(f"the resolved control exposes no {field}")
            continue
        want, got = _comparable(baseline[field]), _comparable(observed[field])
        if want != got:
            reasons.append(f"{field} is {got!r}, authorized {want!r}")
    for field in ("automation_id",):
        value = observed.get(field)
        if isinstance(value, str) and is_positional_automation_id(value):
            reasons.append(
                f"AutomationId {value!r} is positional and is refused as identity"
            )
    return tuple(reasons)


def identity_evidence(
    policy: IdentityPolicy, observed: Mapping[str, Any]
) -> dict[str, Any]:
    """The identity a run record keeps: what was required, and what was noted.

    Kept separate on purpose. A reader has to be able to tell which values a
    refusal would have fired on from which were only recorded.
    """

    return {
        "evidence": {
            field: observed.get(field) for field in sorted(policy.evidence_fields)
        },
        "identity_mode": policy.identity_mode,
        "required": {
            field: observed.get(field) for field in sorted(policy.required_fields)
        },
        "selector_id": policy.selector_id,
        "selector_sha256": policy.selector_sha256,
    }


__all__ = [
    "ALWAYS_REQUIRED",
    "IDENTITY_FIELDS",
    "IDENTITY_MODES",
    "IdentityPolicy",
    "IdentityPolicyError",
    "compare_identity",
    "identity_evidence",
]
