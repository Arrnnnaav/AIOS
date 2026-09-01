import pytest

from ghostcursor.interaction import (
    MODE_ORDER,
    InteractionMode,
    mode_can_propose_plan,
    mode_can_start_guidance,
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


def test_only_implemented_modes_can_start_runtime_work():
    assert mode_can_start_guidance(InteractionMode.TEACH)
    assert mode_can_propose_plan(InteractionMode.PLAN)
    assert not mode_can_start_guidance(InteractionMode.PLAN)
    assert not mode_can_propose_plan(InteractionMode.TEACH)
    assert not any(
        mode_can_start_guidance(mode) or mode_can_propose_plan(mode)
        for mode in (
            InteractionMode.IDEATE,
            InteractionMode.ASSIST,
            InteractionMode.ACT,
        )
    )


def test_act_describes_future_authority_without_granting_it():
    contract = mode_contract(InteractionMode.ACT)
    assert contract.may_request_execution
    assert not contract.available
    assert mode_label(InteractionMode.ACT) == "Act · Preview"


def test_mode_contract_refuses_untyped_values():
    with pytest.raises(TypeError, match="interaction mode"):
        mode_contract("teach")
