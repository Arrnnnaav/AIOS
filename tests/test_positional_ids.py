"""Positional AutomationIds must never reach durable storage (D069).

VS Code's only non-empty AutomationIds are positional: `list_id_<n>_<n>` encodes
a list index, not a control. The command palette's list is recency-ordered, so
`list_id_5_0` means "most recently used command" and changes constantly.
Persisting one and hydrating it next run points at whatever now occupies that
index.

The guard lives at THREE boundaries on purpose, and each holds alone.
`promote()` is the normal runtime path, but a future caller could reach
`ObservationStore.record()` directly and bypass it, so the store refuses these
ids independently. The compiler refuses them a step earlier still, so a recipe
carrying one never reaches either runtime guard rather than depending on one of
them having caught it. These tests are isolated in their own module (the D030
precedent) so each guard's mutation is individually verifiable: deleting any one
of the three must fail a test here.
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


# --- boundary 3: the recipe compiler ---------------------------------------


def _v2_recipe(automation_id):
    """A schema-v2 recipe whose only defect is the positional id."""
    selector = {
        "strategy": "bounded_descendants",
        "control_type": "Button",
        "names": ["Open Chat"],
        "normalise": "none",
        "cardinality": "exactly_one",
        "result_limit": 4,
    }
    return {
        "schema_version": 2,
        "intent_id": "OPEN_CHAT",
        "step_key_namespace": "vscode.open_chat",
        "selectors": {"chat": selector},
        "context_selectors": [],
        "steps": [
            {
                "user_action": "click",
                "target_selector": "chat",
                "target_descriptor": {
                    "claimed": {
                        "name": "Open Chat",
                        "name_synonyms": [],
                        "ocr_text": None,
                        "visual_description": None,
                    },
                    "confirmed": [],
                },
                "instruction_text": "Click Open Chat.",
                "verification_rule": {
                    "kind": "focus_moves_to",
                    "args": {"automation_id": automation_id},
                    "timeout_s": 20.0,
                },
                "risk": "normal",
                "preconditions": [],
                "provenance": {
                    "source_urls": [],
                    "source_tier": "trusted",
                    "model": "none",
                    "prompt_version": "none",
                    "created_at": "2026-08-27T00:00:00Z",
                },
            }
        ],
    }


def test_every_boundary_refuses_independently_of_the_others(tmp_path):
    """Each guard is sufficient on its own, not merely correlated with safety.

    Asserting the three together is what proves the property: removing any one
    of them still leaves a positional id unable to reach durable storage. A test
    that only exercised the boundary a value happens to hit first would pass
    unchanged after the other two were deleted.
    """
    from ghostcursor.packs.compile import RecipeCompileError, compile_recipe

    for automation_id in POSITIONAL_IDS:
        # compiler -- refuses before the recipe can ever be executed
        try:
            compile_recipe(_v2_recipe(automation_id))
        except RecipeCompileError as exc:
            assert automation_id in str(exc)
        else:  # pragma: no cover - reported by the assertion below
            raise AssertionError(f"the compiler accepted {automation_id}")

        # promote() -- refuses the runtime path
        step = _step()
        elements = [Element("Open Chat", "ListItem", automation_id, (10, 10, 110, 40))]
        grounded = ground(step, ".*", elements=elements)
        assert promote(step, grounded, app_version="1.134.0", locale="en-US") is False

        # the store -- refuses even when promote() is bypassed entirely
        store = ObservationStore(tmp_path / f"kb-{automation_id}.sqlite")
        store.record("step-key", "code.exe", _obs(automation_id))
        assert store.observations_for("step-key", "code.exe") == []
