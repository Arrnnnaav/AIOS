from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ghostcursor.action import load_operation_registry
from ghostcursor.action_plans import (
    ActionPlanError,
    load_action_plan_templates,
    materialize_action_plan,
)


ROOT = (
    Path(__file__).resolve().parent.parent
    / "plugins"
    / "sources"
    / "powerpoint"
    / "payload"
    / "ghostcursor"
)
ADAPTER = ROOT / "adapter" / "powerpoint_adapter.py"
PLAN_PATH = ROOT / "action-plans" / "build-investor-deck-v1.json"
INDEX_PATH = ROOT / "action-plans.json"
OPERATIONS_PATH = ROOT / "operations.json"


def _files():
    return {
        **{f"ghostcursor/action-plans/{path.name}": path.read_bytes()
           for path in (ROOT / "action-plans").glob("*.json")},
        "ghostcursor/action-plans.json": INDEX_PATH.read_bytes(),
        "ghostcursor/operations.json": OPERATIONS_PATH.read_bytes(),
    }


def _registry():
    digest = hashlib.sha256(ADAPTER.read_bytes()).hexdigest()
    return load_operation_registry(
        OPERATIONS_PATH.read_bytes(),
        plugin_id="ghostcursor.powerpoint",
        plugin_version="1.0.0",
        adapter_sha256=digest,
    )


def _templates(files=None):
    files = files or _files()
    return load_action_plan_templates(
        files["ghostcursor/action-plans.json"],
        files,
        plugin_id="ghostcursor.powerpoint",
        plugin_version="1.0.0",
        adapter_sha256=hashlib.sha256(ADAPTER.read_bytes()).hexdigest(),
    )


def test_investor_deck_is_one_signed_declarative_255_action_plan(tmp_path):
    template = _templates()["build-investor-deck-v1"]
    output = tmp_path / "ghostcursor-investor-deck.pptx"

    validated = materialize_action_plan(
        template, {"output_path": str(output)}, _registry()
    )

    assert template.intent_id == "BUILD_INVESTOR_DECK"
    assert len(validated.ordered_nodes) == 255
    assert validated.ordered_nodes[0].operation_id == "powerpoint.create_presentation"
    assert validated.ordered_nodes[-1].operation_id == "powerpoint.inspect_presentation"
    assert {
        node.parameters["slide_id"]
        for node in validated.ordered_nodes
        if node.operation_id == "powerpoint.add_slide"
    } == {f"slide-{index:02d}" for index in range(1, 11)}


def test_reviewed_placeholders_motion_and_notes_survive_as_data(tmp_path):
    validated = materialize_action_plan(
        _templates()["build-investor-deck-v1"],
        {"output_path": str(tmp_path / "deck.pptx")},
        _registry(),
    )
    nodes = validated.ordered_nodes
    text = "\n".join(
        node.parameters["text"]
        for node in nodes
        if node.operation_id == "powerpoint.add_text"
    )
    assert "[MONTHLY NEW-HIRE COHORT]" in text
    assert "[ROUND SIZE]" in text
    assert "[FOUNDER NAME, ROLE, RELEVANT CREDIBILITY]" in text
    notes = [node for node in nodes if node.operation_id == "powerpoint.add_notes"]
    assert len(notes) == 10
    assert all(node.parameters["text"].startswith("[Sources]\n") for node in notes)
    transitions = [
        node.parameters["effect"]
        for node in nodes
        if node.operation_id == "powerpoint.set_transition"
    ]
    assert transitions.count("morph") == 2
    assert transitions.count("fade") == 8
    effects = {
        node.parameters["effect"]
        for node in nodes
        if node.operation_id == "powerpoint.add_animation"
    }
    assert effects <= {"fade", "fly_in", "pulse", "wipe", "zoom"}
    assert "spin" not in effects


def test_action_plan_bytes_and_nested_parameters_are_immutable_and_digest_bound():
    files = _files()
    template = _templates(files)["build-investor-deck-v1"]
    with pytest.raises(TypeError):
        template.nodes[0]["parameters"]["output_path"]["$parameter"] = "other"

    changed = dict(files)
    changed["ghostcursor/action-plans/build-investor-deck-v1.json"] += b" "
    with pytest.raises(ActionPlanError, match="digest disagrees"):
        _templates(changed)


def test_action_plan_parameters_are_closed_before_graph_materialization(tmp_path):
    template = _templates()["build-investor-deck-v1"]
    with pytest.raises(ActionPlanError, match="arguments disagree"):
        materialize_action_plan(template, {}, _registry())
    with pytest.raises(ActionPlanError, match="extra"):
        materialize_action_plan(
            template,
            {"output_path": str(tmp_path / "deck.pptx"), "macro": "run"},
            _registry(),
        )
