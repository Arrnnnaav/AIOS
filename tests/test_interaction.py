import pytest

from ghostcursor.interaction import (
    MODE_ORDER,
    InteractionMode,
    mode_can_propose_plan,
    mode_can_start_guidance,
    mode_can_start_act,
    mode_contract,
    mode_label,
)


def test_mode_order_is_a_small_stable_panel_vocabulary():
    assert MODE_ORDER == (
        InteractionMode.IDEATE,
        InteractionMode.PLAN,
        InteractionMode.TEACH,
        InteractionMode.ASSIST,
        InteractionMode.ACT,
    )


def test_only_implemented_modes_can_start_their_owned_runtime_work():
    assert mode_can_start_guidance(InteractionMode.TEACH)
    assert mode_can_propose_plan(InteractionMode.PLAN)
    assert mode_can_start_act(InteractionMode.ACT)
    assert not mode_can_start_guidance(InteractionMode.PLAN)
    assert not mode_can_propose_plan(InteractionMode.TEACH)
    assert not any(
        mode_can_start_guidance(mode) or mode_can_propose_plan(mode)
        for mode in (
            InteractionMode.IDEATE,
            InteractionMode.ASSIST,
        )
    )
    assert not mode_can_start_act(InteractionMode.TEACH)


def test_act_is_shipped_but_still_describes_the_authority_it_requires():
    contract = mode_contract(InteractionMode.ACT)
    assert contract.may_request_execution
    assert contract.available
    assert mode_label(InteractionMode.ACT) == "Act"


def test_mode_contract_refuses_untyped_values():
    with pytest.raises(TypeError, match="interaction mode"):
        mode_contract("teach")
