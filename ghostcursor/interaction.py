"""Canonical interaction-mode contracts shared by presentation surfaces.

Modes describe how the user and GhostCursor collaborate.  They do not grant
authority: executable work still crosses the plugin capability, authorization,
binding, and verification boundaries owned by the runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class InteractionMode(str, Enum):
    IDEATE = "ideate"
    PLAN = "plan"
    TEACH = "teach"
    ASSIST = "assist"
    ACT = "act"


@dataclass(frozen=True)
class ModeContract:
    label: str
    purpose: str
    available: bool
    may_request_execution: bool


MODE_CONTRACTS = {
    InteractionMode.IDEATE: ModeContract(
        "Ideate",
        "Explore options and refine the goal before creating a plan.",
        False,
        False,
    ),
    InteractionMode.PLAN: ModeContract(
        "Plan",
        "Build and review a complete plugin-scoped plan before anything starts.",
        True,
        False,
    ),
    InteractionMode.TEACH: ModeContract(
        "Teach",
        "Guide you step by step while you remain the operator.",
        True,
        False,
    ),
    InteractionMode.ASSIST: ModeContract(
        "Assist",
        "Give concise contextual help while you continue working.",
        False,
        False,
    ),
    InteractionMode.ACT: ModeContract(
        "Act",
        "Execute approved capabilities with permission checks and verification.",
        False,
        True,
    ),
}


MODE_ORDER = tuple(InteractionMode)


def mode_contract(mode: InteractionMode) -> ModeContract:
    """Return the one product contract for ``mode``."""

    if not isinstance(mode, InteractionMode):
        raise TypeError("interaction mode is invalid")
    return MODE_CONTRACTS[mode]


def mode_label(mode: InteractionMode) -> str:
    contract = mode_contract(mode)
    return contract.label if contract.available else f"{contract.label} · Preview"


def mode_can_start_guidance(mode: InteractionMode) -> bool:
    return mode is InteractionMode.TEACH and mode_contract(mode).available


def mode_can_propose_plan(mode: InteractionMode) -> bool:
    return mode is InteractionMode.PLAN and mode_contract(mode).available
