"""Stage and cue declarations must be refused whole, before anything runs.

Every case here is a way a plan could reach execution with a node running
under the wrong label, no label, or a cue promising a trust class nothing can
deliver.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostcursor.stages import (
    MAX_CUES_PER_PLAN,
    MAX_CUES_PER_STAGE,
    MAX_NODES_PER_STAGE,
    MAX_STAGES_PER_PLAN,
    Cue,
    Stage,
    StagePlanError,
    validate_stage_plan,
)


NODES = tuple(f"n{index:03d}" for index in range(1, 11))


def _cue(cue_id: str, before: str, backend: str = "object_model", **kw) -> Cue:
    return Cue(cue_id, f"text for {cue_id}", backend, before, **kw)


def _stage(stage_id: str, node_ids, cues=(), risk: str = "low") -> Stage:
    return Stage(stage_id, f"label {stage_id}", tuple(node_ids), risk, tuple(cues))


# --- coverage --------------------------------------------------------------


def test_a_complete_contiguous_declaration_validates():
    plan = validate_stage_plan(
        [_stage("setup", NODES[:3]), _stage("body", NODES[3:])], NODES
    )

    assert plan.stage_count == 2
    assert plan.cue_count == 0
    assert plan.rail_only_node_ids == NODES


def test_a_node_belonging_to_no_stage_refuses_the_whole_plan():
    """It would run showing the previous stage's label while a different
    operation took effect."""

    with pytest.raises(StagePlanError, match="belong to no stage"):
        validate_stage_plan([_stage("setup", NODES[:9])], NODES)


def test_there_is_no_catch_all_stage_to_absorb_the_remainder():
    with pytest.raises(StagePlanError, match="no catch-all stage"):
        validate_stage_plan([_stage("setup", NODES[:5])], NODES)


def test_a_node_claimed_by_two_stages_refuses():
    with pytest.raises(StagePlanError, match="claimed by both"):
        validate_stage_plan([_stage("a", NODES[:5]), _stage("b", NODES[4:])], NODES)


def test_an_unknown_node_id_refuses():
    with pytest.raises(StagePlanError, match="unknown node"):
        validate_stage_plan(
            [_stage("a", NODES[:5] + ("ghost",)), _stage("b", NODES[5:])], NODES
        )


# --- ordering and contiguity ----------------------------------------------


def test_stages_may_not_interleave():
    """Nodes 1,2 then 5,6 then 3,4 would show stage labels out of sequence
    while the executor ran the plan in its own order."""

    with pytest.raises(StagePlanError, match="interleave"):
        validate_stage_plan(
            [
                _stage("a", NODES[:2]),
                _stage("b", NODES[4:6]),
                _stage("c", NODES[2:4] + NODES[6:]),
            ],
            NODES,
        )


def test_a_stage_listing_its_nodes_out_of_plan_order_refuses():
    with pytest.raises(StagePlanError, match="out of plan order"):
        validate_stage_plan(
            [_stage("a", (NODES[1], NODES[0])), _stage("b", NODES[2:])], NODES
        )


def test_a_stage_that_skips_a_node_refuses_even_when_another_stage_claims_it():
    with pytest.raises(StagePlanError, match="interleave|contiguous"):
        validate_stage_plan(
            [
                _stage("a", (NODES[0], NODES[2])),
                _stage("b", (NODES[1],) + NODES[3:]),
            ],
            NODES,
        )


def test_a_repeated_stage_id_refuses():
    with pytest.raises(StagePlanError, match="declared twice"):
        validate_stage_plan([_stage("a", NODES[:5]), _stage("a", NODES[5:])], NODES)


# --- limits ----------------------------------------------------------------


def test_a_stage_larger_than_the_ceiling_refuses():
    nodes = tuple(f"x{i}" for i in range(MAX_NODES_PER_STAGE + 1))

    with pytest.raises(StagePlanError, match=f"not {len(nodes)}"):
        validate_stage_plan([_stage("a", nodes)], nodes)


def test_a_stage_at_exactly_the_ceiling_is_allowed():
    nodes = tuple(f"x{i}" for i in range(MAX_NODES_PER_STAGE))

    assert validate_stage_plan([_stage("a", nodes)], nodes).stage_count == 1


def test_more_stages_than_the_ceiling_refuses():
    nodes = tuple(f"x{i}" for i in range(MAX_STAGES_PER_PLAN + 1))
    stages = [_stage(f"s{i}", (node,)) for i, node in enumerate(nodes)]

    with pytest.raises(StagePlanError, match="stages, not"):
        validate_stage_plan(stages, nodes)


def test_zero_stages_refuses():
    with pytest.raises(StagePlanError, match="stages, not 0"):
        validate_stage_plan([], NODES)


def test_the_plan_cue_cap_is_derived_from_the_two_limits_it_comes_from():
    """A separately maintained third number could drift out of agreement."""

    assert MAX_CUES_PER_PLAN == MAX_STAGES_PER_PLAN * MAX_CUES_PER_STAGE


# --- cues ------------------------------------------------------------------


def test_cues_partition_their_stage_into_display_groups():
    plan = validate_stage_plan(
        [
            _stage(
                "a",
                NODES,
                cues=[_cue("c1", NODES[0]), _cue("c2", NODES[4]), _cue("c3", NODES[7])],
            )
        ],
        NODES,
    )

    assert [group.node_ids for group in plan.groups] == [
        NODES[0:4],
        NODES[4:7],
        NODES[7:10],
    ]
    assert plan.rail_only_node_ids == ()


def test_a_stage_with_no_cues_is_rail_only_rather_than_invalid():
    plan = validate_stage_plan(
        [_stage("a", NODES[:5], cues=[_cue("c1", NODES[0])]), _stage("b", NODES[5:])],
        NODES,
    )

    assert plan.rail_only_node_ids == NODES[5:]
    assert plan.cue_count == 1


def test_a_stage_with_cues_must_anchor_its_first_node():
    """Otherwise the nodes before the first cue run with no presentation at
    all, inside a stage that promised some."""

    with pytest.raises(StagePlanError, match="not anchored"):
        validate_stage_plan([_stage("a", NODES, cues=[_cue("c1", NODES[3])])], NODES)


def test_cue_anchors_must_increase_through_the_stage():
    with pytest.raises(StagePlanError, match="must increase"):
        validate_stage_plan(
            [_stage("a", NODES, cues=[_cue("c1", NODES[0]), _cue("c2", NODES[0])])],
            NODES,
        )


def test_a_cue_anchoring_backwards_refuses():
    with pytest.raises(StagePlanError, match="must increase"):
        validate_stage_plan(
            [
                _stage(
                    "a",
                    NODES,
                    cues=[
                        _cue("c1", NODES[0]),
                        _cue("c2", NODES[5]),
                        _cue("c3", NODES[2]),
                    ],
                )
            ],
            NODES,
        )


def test_a_cue_anchoring_outside_its_own_stage_refuses():
    with pytest.raises(StagePlanError, match="not \n?in stage|not in stage"):
        validate_stage_plan(
            [
                _stage(
                    "a", NODES[:5], cues=[_cue("c1", NODES[0]), _cue("c2", NODES[7])]
                ),
                _stage("b", NODES[5:]),
            ],
            NODES,
        )


def test_more_cues_than_the_stage_ceiling_refuses():
    cues = [_cue(f"c{i}", NODES[i]) for i in range(MAX_CUES_PER_STAGE + 1)]

    with pytest.raises(StagePlanError, match="more than"):
        validate_stage_plan([_stage("a", NODES, cues=cues)], NODES)


def test_more_cues_than_nodes_refuses():
    nodes = NODES[:2]
    cues = [_cue("c1", nodes[0]), _cue("c2", nodes[1]), _cue("c3", nodes[1])]

    with pytest.raises(
        StagePlanError, match="more cues than it has nodes|must increase"
    ):
        validate_stage_plan([_stage("a", nodes, cues=cues)], nodes)


def test_a_repeated_cue_id_across_different_stages_refuses():
    with pytest.raises(StagePlanError, match="cue 'c1' is declared twice"):
        validate_stage_plan(
            [
                _stage("a", NODES[:5], cues=[_cue("c1", NODES[0])]),
                _stage("b", NODES[5:], cues=[_cue("c1", NODES[5])]),
            ],
            NODES,
        )


def test_an_unknown_backend_refuses_because_it_promises_a_trust_colour():
    with pytest.raises(StagePlanError, match="backend"):
        validate_stage_plan(
            [_stage("a", NODES, cues=[_cue("c1", NODES[0], backend="vision")])],
            NODES,
        )


def test_a_rail_only_cue_may_not_declare_a_visual_target():
    """Rail-only means there is nothing trustworthy to point at; carrying a
    target would let a renderer draw one anyway."""

    with pytest.raises(StagePlanError, match="rail-only but declares"):
        validate_stage_plan(
            [
                _stage(
                    "a",
                    NODES,
                    cues=[
                        Cue(
                            "c1",
                            "text",
                            "rail_only",
                            NODES[0],
                            target={"selector": "x"},
                        )
                    ],
                )
            ],
            NODES,
        )


def test_an_unknown_risk_class_refuses():
    with pytest.raises(StagePlanError, match="risk"):
        validate_stage_plan([_stage("a", NODES, risk="catastrophic")], NODES)


@pytest.mark.parametrize("bad", ["", "   ", "x" * 300])
def test_an_empty_or_oversized_label_refuses(bad):
    with pytest.raises(StagePlanError):
        validate_stage_plan([Stage("a", bad, NODES, "low", ())], NODES)


# --- the real plan ---------------------------------------------------------


def test_the_real_investor_plan_can_be_staged_the_way_the_plan_describes():
    """22 stages: setup, composition and motion per slide, finalization.

    Measured against the actual 255-node plan rather than assumed: the largest
    composition stage holds 32 nodes, which is why the ceiling is 40 and not
    24.
    """

    source = (
        Path(__file__).resolve().parents[1]
        / "plugins/sources/powerpoint/payload/ghostcursor"
        / "action-plans/build-investor-deck-v1.json"
    )
    nodes = json.loads(source.read_text(encoding="utf-8"))["nodes"]
    order = tuple(node["node_id"] for node in nodes)
    motion_ops = {"powerpoint.add_animation", "powerpoint.set_transition"}

    stages: list[Stage] = []
    current: list[str] = []
    current_key: tuple | None = None
    for node in nodes:
        slide = node.get("parameters", {}).get("slide_id")
        key = (slide, node["operation_id"] in motion_ops) if slide else ("deck", False)
        if key != current_key and current:
            stages.append(_stage(f"s{len(stages)}", current))
            current = []
        current_key = key
        current.append(node["node_id"])
    if current:
        stages.append(_stage(f"s{len(stages)}", current))

    plan = validate_stage_plan(stages, order)

    assert len(order) == 255
    assert plan.stage_count <= MAX_STAGES_PER_PLAN
    assert max(len(stage.node_ids) for stage in plan.stages) <= MAX_NODES_PER_STAGE
