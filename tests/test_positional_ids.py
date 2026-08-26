"""Positional AutomationIds must never reach durable storage (D069).

VS Code's only non-empty AutomationIds are positional: `list_id_<n>_<n>` encodes
a list index, not a control. The command palette's list is recency-ordered, so
`list_id_5_0` means "most recently used command" and changes constantly.
Persisting one and hydrating it next run points at whatever now occupies that
index.

The guard lives at BOTH boundaries on purpose. `promote()` is the normal path,
but a future caller could reach `ObservationStore.record()` directly and bypass
it, so the store refuses these ids independently. These tests are isolated in
their own module (the D030 precedent) so each guard's mutation is individually
verifiable: deleting either one must fail a test here.
"""

from ghostcursor.memory.store import ObservationStore
from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.grounding import ground, promote
from ghostcursor.reasoning.schema import (
    ClaimedDescriptor,
    ConfirmedObservation,
    Risk,
    Step,
    TargetDescriptor,
    UserAction,
    VerificationKind,
    VerificationRule,
)

POSITIONAL_IDS = [
    "list_id_1_0",
    "list_id_2_1",
    "list_id_5_12",
]

# Non-empty ids that merely resemble the positional shape but are not it. These
# must still be promoted, or the guard is too broad and silently disables
# learning for legitimate controls.
STABLE_IDS = [
    "quickInput_list",
    "list_id_1",
    "list_idx_1_0",
    "list_id_1_0_extra",
    "workbench.list_id_1_0",
    "1001",
]


def _step(name="Open Chat"):
    return Step(
        user_action=UserAction.CLICK,
        target_descriptor=TargetDescriptor(claimed=ClaimedDescriptor(name=name)),
        instruction_text=f"Click {name}.",
        verification_rule=VerificationRule(kind=VerificationKind.USER_CONFIRMS),
        risk=Risk.NORMAL,
    )


def _obs(automation_id):
    return ConfirmedObservation(
        app_version="1.134.0",
        locales_observed=["en-US"],
        automation_id=automation_id,
        control_type="ListItem",
        last_seen_at="2026-08-26T00:00:00+00:00",
    )


# --- boundary 1: promote() -------------------------------------------------


def test_promote_refuses_a_positional_automation_id():
    for automation_id in POSITIONAL_IDS:
        step = _step()
        elements = [Element("Open Chat", "ListItem", automation_id, (10, 10, 110, 40))]
        grounded = ground(step, ".*", elements=elements)
        assert grounded is not None, f"fixture must ground for {automation_id}"
        assert grounded.automation_id == automation_id

        assert promote(step, grounded, app_version="1.134.0", locale="en-US") is False
        assert step.target_descriptor.confirmed == [], (
            f"{automation_id} is a list position, not a control, and must not persist"
        )


def test_promote_still_records_a_stable_automation_id():
    for automation_id in STABLE_IDS:
        step = _step()
        elements = [Element("Open Chat", "ListItem", automation_id, (10, 10, 110, 40))]
        grounded = ground(step, ".*", elements=elements)
        assert grounded is not None

        assert promote(step, grounded, app_version="1.134.0", locale="en-US") is True
        assert step.target_descriptor.confirmed[0].automation_id == automation_id


# --- boundary 2: ObservationStore.record() ---------------------------------


def test_store_refuses_a_positional_automation_id(tmp_path):
    store = ObservationStore(tmp_path / "kb.sqlite")
    for automation_id in POSITIONAL_IDS:
        store.record("step-key", "code.exe", _obs(automation_id))
        assert store.observations_for("step-key", "code.exe") == [], (
            f"{automation_id} must be refused even when promote() is bypassed"
        )


def test_store_still_records_a_stable_automation_id(tmp_path):
    store = ObservationStore(tmp_path / "kb.sqlite")
    for automation_id in STABLE_IDS:
        store.record(f"step-{automation_id}", "code.exe", _obs(automation_id))
        rows = store.observations_for(f"step-{automation_id}", "code.exe")
        assert [row.automation_id for row in rows] == [automation_id]
