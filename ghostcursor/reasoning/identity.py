"""A durable identity for "this step of this recipe" (spec §9).

Persisting what a step learned needs a key that survives editing the recipe.
`(intent, step_index)` is unusable: inserting a step silently re-attaches
every learned observation to a different instruction.

The key hashes the intent (as namespace) plus the step's CLAIMED descriptor:
`name`, `ocr_text` and `visual_description`.

  - `name_synonyms` is excluded. Synonyms are alternate spellings of the same
    target, so adding one must not discard what the step has learned.
  - `visual_description` is included. It is what separates two steps sharing a
    name but differing in location ("Delete in the toolbar" versus "Delete in
    the dialog") — exactly the collision that would otherwise let one step's
    observations mis-ground the other.

Editing any of the three orphans that step's observations. That is correct,
not unfortunate: the step now describes a different target, and inherited
evidence about the old one would be wrong.
"""

from __future__ import annotations

import hashlib

from ghostcursor.reasoning.schema import Step


def _normalize(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def step_key(intent: str, step: Step) -> str:
    claimed = step.target_descriptor.claimed
    parts = [
        _normalize(intent),
        _normalize(claimed.name),
        _normalize(claimed.ocr_text),
        _normalize(claimed.visual_description),
    ]
    # \x1f (unit separator) cannot appear in normalized text, so distinct
    # field values can never combine into the same digest input.
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
