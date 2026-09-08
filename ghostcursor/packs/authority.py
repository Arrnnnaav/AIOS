"""Opaque execution authority minted only by the planner's policy gate."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthorizedIntent:
    """The exact catalog facts one intent was authorized against.

    This is not an executable workflow. ``bind_workflow`` independently reloads
    current authority and compares every field before it is allowed to resolve
    a live target or compile selectors.
    """

    plugin_id: str
    plugin_version: str
    plugin_manifest_sha256: str
    pack_id: str
    intent_id: str
    catalog_sha256: str
    catalog_generation: int
    activation_generation: int
    activation_sha256: str
    pack_sha256: str
    intent_sha256: str
    adoption_id: str
    recipe_sha256: str
    evidence_sha256: str


@dataclass(frozen=True)
class AuthorizedActionIntent:
    """Exact signed-plan authority for an Act proposal.

    An action plan is not an adopted Teach recipe.  This token therefore binds
    the verified catalog intent to one signed plan and adapter without carrying
    fictional adoption/evidence fields.  It cannot be consumed by
    ``bind_workflow``; Act still needs whole-graph approval and fresh per-node
    authorization before an effect can run.
    """

    plugin_id: str
    plugin_version: str
    plugin_manifest_sha256: str
    pack_id: str
    intent_id: str
    catalog_sha256: str
    catalog_generation: int
    activation_generation: int
    activation_sha256: str
    pack_sha256: str
    intent_sha256: str
    plan_id: str
    plan_sha256: str
    adapter_sha256: str
