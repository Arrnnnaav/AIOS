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
