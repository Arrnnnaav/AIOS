"""Orbyn's provider gateway: System One (Jev) and System Two (chat models).

Teach slice 1 (D159, D164). No UI is wired to this package yet.
"""

from ghostcursor.providers.envelope import Envelope, Tainted, sanitize
from ghostcursor.providers.errors import FailureKind, ProviderError
from ghostcursor.providers.gateway import Budget, Gateway
from ghostcursor.providers.schemas import (
    ABSTAIN,
    Choice,
    ExpectedChange,
    PlanStep,
    TeachPlan,
    parse_choice,
    parse_teach_plan,
    strict_json,
)
from ghostcursor.providers.slot import RequestSlot, SlotResult

__all__ = [
    "ABSTAIN",
    "Budget",
    "Choice",
    "Envelope",
    "ExpectedChange",
    "FailureKind",
    "Gateway",
    "PlanStep",
    "ProviderError",
    "RequestSlot",
    "SlotResult",
    "Tainted",
    "TeachPlan",
    "parse_choice",
    "parse_teach_plan",
    "sanitize",
    "strict_json",
]
