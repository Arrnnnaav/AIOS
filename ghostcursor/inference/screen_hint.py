"""Screen-aware, bounded next-hint inference.

The model sees only a goal and frozen UI primitives. It can select an observed
AutomationId, never a path, coordinate, recipe, or executable action.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

from ghostcursor.inference.ollama import (
    DEFAULT_MODEL,
    GenerateResponse,
    generate_structured,
)
from ghostcursor.perception.uia import Element


@dataclass(frozen=True)
class HintDecision:
    automation_id: str | None
    confidence: float
    explanation: str
    source: str  # "model", "fallback", or "invalid-model"


@dataclass(frozen=True)
class HintInference:
    decision: HintDecision
    generation: GenerateResponse


MAX_CANDIDATES = 32
MAX_EXPLANATION_CHARS = 512


def _fallback(elements: list[Element], allowed_names: tuple[str, ...]) -> HintDecision:
    names = {name.casefold() for name in allowed_names}
    for element in elements:
        if element.source == "uia" and element.name.casefold() in names:
            return HintDecision(element.automation_id, 0.95, "matched the trusted target name", "fallback")
    return HintDecision(None, 0.0, "no trusted observed target matched", "fallback")


def _eligible_candidates(
    elements: list[Element], allowed_names: tuple[str, ...]
) -> tuple[Element, ...]:
    allowed = {name.casefold() for name in allowed_names if name}
    matching = [
        element
        for element in elements
        if element.source == "uia"
        and bool(element.automation_id)
        and element.name.casefold() in allowed
    ]
    counts = Counter(element.automation_id for element in matching)
    return tuple(
        sorted(
            (element for element in matching if counts[element.automation_id] == 1),
            key=lambda element: element.automation_id,
        )
    )


def hint_response_schema(candidate_ids: tuple[str, ...]) -> dict:
    if not candidate_ids:
        raise ValueError("hint candidates must not be empty")
    return {
        "type": "object",
        "properties": {
            "automation_id": {"type": "string", "enum": list(candidate_ids)},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "explanation": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_EXPLANATION_CHARS,
            },
        },
        "required": ["automation_id", "confidence", "explanation"],
        "additionalProperties": False,
    }


def _parse(raw: object, candidate_ids: tuple[str, ...]) -> HintDecision:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict) or set(raw) != {
        "automation_id", "confidence", "explanation"
    }:
        raise ValueError("model response did not have the exact hint fields")
    automation_id = raw["automation_id"]
    confidence = raw["confidence"]
    explanation = raw["explanation"]
    if (
        not isinstance(automation_id, str)
        or automation_id not in candidate_ids
        or not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0 <= float(confidence) <= 1
        or not isinstance(explanation, str)
        or not explanation.strip()
        or len(explanation) > MAX_EXPLANATION_CHARS
    ):
        raise ValueError("model selected an untrusted target or returned invalid fields")
    return HintDecision(automation_id, float(confidence), explanation.strip(), "model")


def infer_hint(
    goal: str,
    candidates: tuple[Element, ...],
    *,
    endpoint: str,
    model: str,
    timeout: float,
) -> HintInference:
    candidate_ids = tuple(element.automation_id for element in candidates)
    prompt = (
        "Choose the recipe-approved observed control that best advances the goal. "
        "Return only automation_id, confidence, and explanation.\n"
        f"Goal: {goal}\nEligible UI controls: "
        + json.dumps([
            {
                "name": element.name,
                "control_type": element.control_type,
                "automation_id": element.automation_id,
            }
            for element in candidates
        ], ensure_ascii=False)
    )
    generation = generate_structured(
        endpoint=endpoint,
        model=model,
        prompt=prompt,
        schema=hint_response_schema(candidate_ids),
        timeout=timeout,
    )
    return HintInference(_parse(generation.payload, candidate_ids), generation)


def decide_next_hint(
    goal: str,
    elements: list[Element],
    allowed_names: tuple[str, ...],
    *,
    endpoint: str = "http://127.0.0.1:11434",
    model: str = DEFAULT_MODEL,
    timeout: float = 15.0,
    use_model: bool = True,
) -> HintDecision:
    fallback = _fallback(elements, allowed_names)
    if not use_model:
        return fallback
    candidates = _eligible_candidates(elements, allowed_names)
    if not candidates or len(candidates) > MAX_CANDIDATES:
        return fallback
    try:
        return infer_hint(
            goal, candidates, endpoint=endpoint, model=model, timeout=timeout
        ).decision
    except (OSError, TimeoutError, ConnectionError):
        return fallback
    except (ValueError, KeyError, json.JSONDecodeError):
        return HintDecision(fallback.automation_id, fallback.confidence, "model output was invalid; used trusted fallback", "invalid-model")
