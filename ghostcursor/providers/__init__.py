"""Orbyn's provider gateway: System One (Jev) and System Two (chat models).

Teach slice 1 (D159, D164). No UI is wired to this package yet.
"""

from ghostcursor.providers.envelope import Envelope, Tainted, sanitize
from ghostcursor.providers.errors import FailureKind, ProviderError
from ghostcursor.providers.gateway import Budget, Gateway
from ghostcursor.providers.schemas import (
    ABSTAIN,
    CREW_PLAN_SCHEMA,
    CRITIQUE_SCHEMA,
    DECK_SPEC_SCHEMA,
    INTENT_SCHEMA,
    NOTES_SCHEMA,
    RESEARCH_PLAN_SCHEMA,
    Choice,
    Critique,
    DeckSpec,
    ExpectedChange,
    NotesSummary,
    PlanStep,
    Slide,
    SlideLayout,
    TeachPlan,
    parse_choice,
    parse_crew_plan,
    parse_critique,
    parse_deck_spec,
    parse_intent,
    parse_notes,
    parse_research_plan,
    parse_teach_plan,
    strict_json,
)
from ghostcursor.providers.slot import RequestSlot, SlotResult

__all__ = [
    "ABSTAIN",
    "Budget",
    "Choice",
    "CREW_PLAN_SCHEMA",
    "CRITIQUE_SCHEMA",
    "Critique",
    "DECK_SPEC_SCHEMA",
    "INTENT_SCHEMA",
    "NOTES_SCHEMA",
    "NotesSummary",
    "RESEARCH_PLAN_SCHEMA",
    "DeckSpec",
    "Envelope",
    "ExpectedChange",
    "FailureKind",
    "Gateway",
    "PlanStep",
    "ProviderError",
    "RequestSlot",
    "Slide",
    "SlideLayout",
    "SlotResult",
    "Tainted",
    "TeachPlan",
    "parse_choice",
    "parse_crew_plan",
    "parse_critique",
    "parse_deck_spec",
    "parse_intent",
    "parse_notes",
    "parse_research_plan",
    "parse_teach_plan",
    "sanitize",
    "strict_json",
]
