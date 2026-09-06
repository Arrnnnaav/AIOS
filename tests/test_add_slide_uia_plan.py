"""The single-node UIA action plan, and what has to agree for it to run.

This is the plan that will exercise the control-driving path end to end: one
node, `powerpoint.new_slide_uia`, Invoke on the New Slide button. It exists so
a caller finally exercises the contracts D107 says are unfinished without one.

It is NOT adoption and NOT acceptance evidence. CLAUDE.md is explicit that no
`uia_pattern` operation may be adopted until it has an independent D032
review, externally signed bytes and a counted acceptance campaign. None of
those exist for this operation.

Everything here is hermetic: it reads the plugin SOURCE payload, never a
signed bundle, and starts no adapter.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ghostcursor.action import (
    ActionGraph,
    ActionNode,
    load_operation_registry,
    validate_action_graph,
)

PAYLOAD = Path("plugins/sources/powerpoint/payload/ghostcursor")
PLAN_ID = "add-slide-uia-v1"
OPERATION_ID = "powerpoint.new_slide_uia"
PLUGIN = "ghostcursor.powerpoint"
VERSION = "1.0.0"


def _index() -> dict:
    return json.loads((PAYLOAD / "action-plans.json").read_text(encoding="utf-8"))


def _plan_path() -> Path:
    entry = _index()["plans"][PLAN_ID]
    # The index names a path relative to the payload root, and the payload
    # root is `ghostcursor/`, so the entry already carries that prefix.
    return PAYLOAD.parent / entry["path"]


def _registry():
    return load_operation_registry(
        (PAYLOAD / "operations.json").read_bytes(),
        plugin_id=PLUGIN,
        plugin_version=VERSION,
        adapter_sha256="a" * 64,
    )


def test_the_index_digest_matches_the_plan_on_disk():
    """The index pins the plan's bytes. A plan whose digest drifted from its
    index entry is one the runtime would refuse -- better to learn that here
    than from a signed bundle that will not load."""

    entry = _index()["plans"][PLAN_ID]
    actual = hashlib.sha256(_plan_path().read_bytes()).hexdigest()
    assert actual == entry["sha256"]


def test_the_existing_deck_plan_was_not_disturbed():
    """Adding a plan must not change the one the 3/3 acceptance campaign was
    run against. Its digest is cited in docs/evidence/act-acceptance-campaign.md."""

    entry = _index()["plans"]["build-investor-deck-v1"]
    actual = hashlib.sha256(
        (PAYLOAD / "action-plans" / "build-investor-deck-v1.json").read_bytes()
    ).hexdigest()
    assert actual == entry["sha256"]
    assert entry["sha256"].startswith("84e39d0d2987e153")


def test_the_plan_validates_against_the_signed_operations():
    plan = json.loads(_plan_path().read_text(encoding="utf-8"))
    graph = ActionGraph(
        PLUGIN,
        VERSION,
        "a" * 64,
        tuple(
            ActionNode(n["node_id"], n["operation_id"], n.get("parameters", {}))
            for n in plan["nodes"]
        ),
        (),
    )
    validated = validate_action_graph(graph, _registry())

    assert [node.node_id for node in validated.ordered_nodes] == ["n001-new-slide"]


def test_the_plans_single_node_is_control_driving():
    """If it were object-model this plan would exercise nothing new: the
    255-node deck already covers that path, and an object-model node draws no
    pointer at all (D109)."""

    operation = _registry().operations[OPERATION_ID]

    assert operation.backend == "uia_pattern"
    assert operation.draws_a_pointer is True
    assert operation.uia_pattern == "Invoke"


def test_the_operation_pins_a_selector_that_exists_and_matches():
    """The operation names a selector by id AND by digest. The digest is what
    stops a selector file being swapped for one naming a different control
    after the operation was signed."""

    from ghostcursor.selectors import selector_path

    operation = _registry().operations[OPERATION_ID]
    policy = operation.identity
    assert policy is not None, "a control-driving operation with no identity policy"

    path = selector_path(PAYLOAD.parent, policy.selector_id)
    assert path.is_file(), f"the pinned selector is missing at {path}"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == policy.selector_sha256

    selector = json.loads(path.read_text(encoding="utf-8"))
    # An ACTION selector is EXACTLY_ONE: more than one match must refuse
    # rather than silently take the first (D069, D070).
    assert selector["cardinality"] == "exactly_one"
    assert selector["control_type"] == policy.control_type


def test_the_operation_requires_runtime_identity():
    """`runtime_id_required` is what makes the confirmation compare the same
    control the observation resolved, rather than one that merely shares a
    name."""

    policy = _registry().operations[OPERATION_ID].identity

    assert policy.identity_mode == "runtime_id_required"
    assert "runtime_id" in policy.required_fields


def test_the_postcondition_names_a_change_not_a_state():
    """A live verifier must answer a postcondition naming a CHANGE against
    the reading taken before the cue. A state such as `slide.exists` is
    satisfied by a node that did nothing."""

    operation = _registry().operations[OPERATION_ID]

    assert operation.postconditions == ("slide.count.increased_by_one",)
    for condition in operation.postconditions:
        assert "exists" not in condition


def test_the_effect_is_not_declared_safe_to_repeat():
    """Adding a slide twice adds two slides. Declaring it repeatable would
    let a retry double the effect."""

    raw = json.loads((PAYLOAD / "operations.json").read_text(encoding="utf-8"))
    assert raw["operations"][OPERATION_ID]["safe_to_repeat"] is False


def test_the_plugin_ships_the_live_verifier_this_backend_requires():
    """A plugin declaring a UIA backend must also ship a separately signed
    read-only live verifier: the artifact verifier reads a file, and a UIA
    effect reaches no file until somebody saves. Bundle verification refuses
    either half of that pairing alone."""

    assert (PAYLOAD / "adapter" / "powerpoint_live_verifier.py").is_file()


@pytest.mark.parametrize(
    "intent_id", [entry["intent_id"] for entry in _index()["plans"].values()]
)
def test_every_planned_intent_exists_in_the_pack(intent_id):
    activation = json.loads(
        (PAYLOAD / "packs" / "powerpoint" / "activation.json").read_text(
            encoding="utf-8"
        )
    )
    assert intent_id in activation["intents"]


def test_this_plan_is_not_adopted_and_claims_nothing():
    """Reusing ADD_SLIDE for both the guided recipe and this action plan is
    deliberate: a mode never grants authority, and the two paths reach
    different artifacts. What must stay true is that the action plan gains
    nothing from the recipe's adoption -- the action-plan path requires the
    plan and the signed operation registry, never an adoption record."""

    activation = json.loads(
        (PAYLOAD / "packs" / "powerpoint" / "activation.json").read_text(
            encoding="utf-8"
        )
    )
    entry = activation["intents"]["ADD_SLIDE"]
    assert entry["active_adoption_id"] is None, (
        "ADD_SLIDE is adopted now; this test pinned the assumption that the "
        "action plan does not depend on that, so re-read the action-plan path "
        "before changing it"
    )
