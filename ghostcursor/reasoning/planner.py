"""Bounded natural-language planning for GhostCursor.

The planner may classify a goal, but it never supplies executable code or
coordinates.  Execution is always a schema-validated recipe from the local
trusted registry.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from ghostcursor.inference.ollama import (
    DEFAULT_MODEL,
    GenerateResponse,
    generate_structured,
)
from ghostcursor.reasoning.schema import Recipe


class PlanStatus(Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED_GOAL = "UNSUPPORTED_GOAL"
    KNOWN_INTENT_RECIPE_UNAVAILABLE = "KNOWN_INTENT_RECIPE_UNAVAILABLE"
    INVALID_MODEL_OUTPUT = "INVALID_MODEL_OUTPUT"
    MODEL_UNAVAILABLE_FALLBACK = "MODEL_UNAVAILABLE_FALLBACK"
    MODEL_ABSTAINED_FALLBACK = "MODEL_ABSTAINED_FALLBACK"


MAX_GOAL_CHARS = 1024
MAX_EXPLANATION_CHARS = 512
PLANNER_NUM_PREDICT = 128


@dataclass(frozen=True)
class IntentSpec:
    intent_id: str
    phrases: tuple[str, ...]
    recipe_path: Path | None
    canonical_target: str | None = None


@dataclass(frozen=True)
class PlanResult:
    status: PlanStatus
    intent_id: str | None
    confidence: float
    explanation: str
    plan: Recipe | None = None


@dataclass(frozen=True)
class IntentDecision:
    intent_id: str | None
    confidence: float
    explanation: str


@dataclass(frozen=True)
class IntentInference:
    decision: IntentDecision
    generation: GenerateResponse


class ModelInputRejected(ValueError):
    """The advisory request was rejected before contacting the model."""


_ROOT = Path(__file__).resolve().parent
_RECIPE_DIR = _ROOT / "recipes"


def registry() -> dict[str, IntentSpec]:
    return {
        "EXPORT_DATA": IntentSpec(
            "EXPORT_DATA",
            ("export this table as csv", "export as csv", "export data", "export the current file"),
            _RECIPE_DIR / "synthetic_export.json",
            "Synthetic Export",
        ),
        "CREATE_DOCUMENT": IntentSpec("CREATE_DOCUMENT", ("create a document", "new document"), None),
        "OPEN_SETTINGS": IntentSpec("OPEN_SETTINGS", ("open settings", "show settings"), None),
        "OPEN_FOLDER": IntentSpec(
            "OPEN_FOLDER",
            (
                "open a folder in vs code",
                "open a folder in vscode",
                "open a folder in visual studio code",
            ),
            _ROOT.parent / "packs" / "recipes" / "vscode" / "open_folder.json",
        ),
        "OPEN_TERMINAL": IntentSpec(
            "OPEN_TERMINAL",
            (
                "open the integrated terminal in vs code",
                "open the integrated terminal in vscode",
                "open a terminal in vs code",
                "open a terminal in vscode",
            ),
            _ROOT.parent / "packs" / "recipes" / "vscode" / "open_terminal.json",
        ),
    }


def _fallback(goal: str) -> tuple[str | None, float, str]:
    normalized = " ".join(goal.lower().split())
    specs = registry()
    for phrase in specs["EXPORT_DATA"].phrases:
        if normalized == phrase:
            return "EXPORT_DATA", 0.95, f"matched exact phrase: {phrase}"
    if any(word in normalized for word in ("csv", "spreadsheet", "table")) and any(
        word in normalized for word in ("export", "save", "download")
    ):
        return "EXPORT_DATA", 0.85, "matched a known export synonym"
    for phrase in specs["OPEN_FOLDER"].phrases:
        if normalized == phrase:
            return "OPEN_FOLDER", 0.95, f"matched exact phrase: {phrase}"
    if (
        "open" in normalized
        and any(alias in normalized for alias in ("vs code", "vscode", "visual studio code"))
        and ("folder" in normalized or "\\" in normalized or "/" in normalized)
    ):
        return "OPEN_FOLDER", 0.85, "matched the VS Code open-folder intent"
    for phrase in specs["OPEN_TERMINAL"].phrases:
        if normalized == phrase:
            return "OPEN_TERMINAL", 0.95, f"matched exact phrase: {phrase}"
    if (
        any(word in normalized for word in ("open", "show"))
        and "terminal" in normalized
        and any(alias in normalized for alias in ("vs code", "vscode", "visual studio code"))
    ):
        return "OPEN_TERMINAL", 0.85, "matched the VS Code integrated-terminal intent"
    return None, 0.0, "no trusted intent matched"


def deterministic_intent(goal: str) -> tuple[str | None, float, str]:
    """Expose the trusted rule classifier to production-parity evaluation.

    The evaluation gate calls this same function rather than maintaining a
    second, potentially drifting implementation of deterministic grounding.
    """
    return _fallback(goal)


def planner_response_schema(intent_ids: tuple[str, ...]) -> dict:
    if not intent_ids:
        raise ValueError("planner registry must not be empty")
    return {
        "type": "object",
        "properties": {
            "intent_id": {
                "type": ["string", "null"],
                "enum": [None, *intent_ids],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "explanation": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_EXPLANATION_CHARS,
            },
        },
        "required": ["intent_id", "confidence", "explanation"],
        "additionalProperties": False,
    }


def parse_intent_decision(raw: object, intent_ids: tuple[str, ...]) -> IntentDecision:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict) or set(raw) != {"intent_id", "confidence", "explanation"}:
        raise ValueError("model response did not have the exact planner fields")
    intent = raw["intent_id"]
    confidence = raw["confidence"]
    explanation = raw["explanation"]
    if intent is not None and (not isinstance(intent, str) or intent not in intent_ids):
        raise ValueError("invalid model intent")
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0 <= float(confidence) <= 1
    ):
        raise ValueError("invalid model confidence")
    if (
        not isinstance(explanation, str)
        or not explanation.strip()
        or len(explanation) > MAX_EXPLANATION_CHARS
    ):
        raise ValueError("invalid model explanation")
    return IntentDecision(intent, float(confidence), explanation.strip())


def infer_intent(goal: str, endpoint: str, model: str, timeout: float) -> IntentInference:
    if len(goal) > MAX_GOAL_CHARS:
        raise ModelInputRejected(f"goal exceeds {MAX_GOAL_CHARS} characters")
    intent_ids = tuple(sorted(registry()))
    prompt = (
        "Classify the goal using one registered intent. Use JSON null for intent_id "
        "when none fits. Return only intent_id, confidence, and explanation. "
        f"Registered intents: {', '.join(intent_ids)}. "
        f"Goal: {goal}"
    )
    generation = generate_structured(
        endpoint=endpoint,
        model=model,
        prompt=prompt,
        schema=planner_response_schema(intent_ids),
        timeout=timeout,
        num_predict=PLANNER_NUM_PREDICT,
    )
    return IntentInference(parse_intent_decision(generation.payload, intent_ids), generation)


def _model_intent(goal: str, endpoint: str, model: str, timeout: float) -> IntentDecision:
    """Compatibility seam used by focused policy tests."""
    return infer_intent(goal, endpoint, model, timeout).decision


def _trusted_recipe(spec: IntentSpec) -> Recipe | None:
    if spec.recipe_path is None:
        return None
    trusted_root = _RECIPE_DIR.resolve()
    pack_root = (_ROOT.parent / "packs" / "recipes").resolve()
    if spec.recipe_path.is_symlink():
        raise ValueError("recipe path must not be a symlink")
    path = spec.recipe_path.resolve(strict=True)
    if path.parent != trusted_root and not str(path).startswith(str(pack_root) + os.sep):
        raise ValueError("recipe path is outside the trusted recipe directory")
    recipe = Recipe.load(path)
    if path.parent == trusted_root and (recipe.intent != "export the current file" or recipe.app_id != "synthetic"):
        raise ValueError("recipe registry metadata does not match the trusted recipe")
    return recipe


def recipe_path_for(intent_id: str) -> Path:
    """Return a validated recipe path for a planned intent."""
    spec = registry()[intent_id]
    if spec.recipe_path is None:
        raise ValueError(f"no recipe is registered for {intent_id}")
    _trusted_recipe(spec)
    return spec.recipe_path.resolve()


def resolve_model_decision(goal: str, decision: IntentDecision) -> PlanResult:
    """Pure authority policy: model advice plus deterministic trusted grounding."""
    fallback_id, fallback_confidence, fallback_explanation = _fallback(goal)
    if decision.intent_id is None:
        if fallback_id is None:
            return PlanResult(
                PlanStatus.UNSUPPORTED_GOAL,
                None,
                0.0,
                f"model abstained: {decision.explanation}",
            )
        recipe = _trusted_recipe(registry()[fallback_id])
        return PlanResult(
            PlanStatus.MODEL_ABSTAINED_FALLBACK,
            fallback_id,
            fallback_confidence,
            f"model abstained; {fallback_explanation}",
            recipe,
        )

    spec = registry()[decision.intent_id]
    # A registered ID is only an allowlist boundary. An available recipe gains
    # authority only when the deterministic classifier independently agrees.
    if spec.recipe_path is not None and fallback_id != decision.intent_id:
        if fallback_id is not None:
            recipe = _trusted_recipe(registry()[fallback_id])
            return PlanResult(
                PlanStatus.INVALID_MODEL_OUTPUT,
                fallback_id,
                fallback_confidence,
                (
                    f"model selected ungrounded intent {decision.intent_id}; "
                    f"{fallback_explanation}"
                ),
                recipe,
            )
        return PlanResult(
            PlanStatus.UNSUPPORTED_GOAL,
            None,
            0.0,
            (
                f"model selected ungrounded intent {decision.intent_id}; "
                "no trusted intent matched"
            ),
        )
    recipe = _trusted_recipe(spec)
    if recipe is None:
        return PlanResult(
            PlanStatus.KNOWN_INTENT_RECIPE_UNAVAILABLE,
            decision.intent_id,
            decision.confidence,
            decision.explanation,
        )
    return PlanResult(
        PlanStatus.SUPPORTED,
        decision.intent_id,
        decision.confidence,
        decision.explanation,
        recipe,
    )


def plan_goal(goal: str, *, endpoint: str = "http://127.0.0.1:11434", model: str = DEFAULT_MODEL, timeout: float = 15.0, use_model: bool = True) -> PlanResult:
    """Classify one goal and load only a trusted local recipe."""
    if not goal or not goal.strip():
        return PlanResult(PlanStatus.UNSUPPORTED_GOAL, None, 0.0, "goal is empty")
    fallback_id, fallback_confidence, fallback_explanation = _fallback(goal)
    if use_model:
        try:
            return resolve_model_decision(goal, _model_intent(goal, endpoint, model, timeout))
        except (OSError, TimeoutError, ConnectionError) as exc:
            if fallback_id:
                recipe = _trusted_recipe(registry()[fallback_id])
                return PlanResult(
                    PlanStatus.MODEL_UNAVAILABLE_FALLBACK,
                    fallback_id,
                    fallback_confidence,
                    f"{fallback_explanation} (Ollama request failed: {type(exc).__name__})",
                    recipe,
                )
            return PlanResult(
                PlanStatus.UNSUPPORTED_GOAL,
                None,
                0.0,
                f"model unavailable ({type(exc).__name__}); no trusted intent matched",
            )
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            if fallback_id:
                recipe = _trusted_recipe(registry()[fallback_id])
                return PlanResult(
                    PlanStatus.INVALID_MODEL_OUTPUT,
                    fallback_id,
                    fallback_confidence,
                    f"{fallback_explanation} ({type(exc).__name__})",
                    recipe,
                )
            return PlanResult(
                PlanStatus.UNSUPPORTED_GOAL,
                None,
                0.0,
                "model output was invalid and no trusted intent matched",
            )
    if fallback_id:
        recipe = _trusted_recipe(registry()[fallback_id])
        status = PlanStatus.MODEL_UNAVAILABLE_FALLBACK if use_model else PlanStatus.SUPPORTED
        return PlanResult(status, fallback_id, fallback_confidence, fallback_explanation, recipe)
    return PlanResult(PlanStatus.UNSUPPORTED_GOAL, None, 0.0, "no trusted intent matched")


# ---------------------------------------------------------------------------
# Schema v2: classification with no recipe loading
# ---------------------------------------------------------------------------
#
# `resolve_model_decision()` above is still production authority and still
# loads a recipe inline. That coupling is what this replaces: it made naming an
# intent and gaining the right to execute one the same act, so every test of
# the authority policy had to have a loadable recipe on disk, and the policy
# could not be reasoned about without one.
#
# Here classification is pure. It names an intent and says nothing about what
# may run. Materialization -- an active adoption, a live window, an exactly
# equal application identity -- happens in `ghostcursor.packs.workflow`, which
# is the only thing that can grant execution. Production keeps the v1 path
# until the atomic cutover.


@dataclass(frozen=True)
class Classification:
    """The result of naming an intent. Carries no recipe and no authority."""

    status: PlanStatus
    intent_id: str | None
    confidence: float
    explanation: str


def classify_decision(
    goal: str,
    decision: IntentDecision,
    *,
    deterministic: Callable[[str], tuple[str | None, float, str]],
    available: frozenset[str],
) -> Classification:
    """Apply the authority policy without touching a recipe.

    `available` names the intents that currently have an active adoption. It is
    consulted only to tell an ungrounded *available* intent from an ungrounded
    unavailable one, which is the distinction D058 turns on -- a registered ID
    is an allowlist boundary the model may name, never semantic evidence that
    it named the right one.

    The model can never widen this. Where its choice and the deterministic
    classifier's grounded intent disagree, the deterministic one wins if it
    exists and nothing runs if it does not.
    """
    fallback_id, fallback_confidence, fallback_explanation = deterministic(goal)

    if decision.intent_id is None:
        if fallback_id is None:
            return Classification(
                PlanStatus.UNSUPPORTED_GOAL,
                None,
                0.0,
                f"model abstained: {decision.explanation}",
            )
        return Classification(
            PlanStatus.MODEL_ABSTAINED_FALLBACK,
            fallback_id,
            fallback_confidence,
            f"model abstained; {fallback_explanation}",
        )

    if decision.intent_id in available and fallback_id != decision.intent_id:
        if fallback_id is None:
            return Classification(
                PlanStatus.UNSUPPORTED_GOAL,
                None,
                0.0,
                (
                    f"model selected ungrounded intent {decision.intent_id}; "
                    "no trusted intent matched"
                ),
            )
        return Classification(
            PlanStatus.INVALID_MODEL_OUTPUT,
            fallback_id,
            fallback_confidence,
            (
                f"model selected ungrounded intent {decision.intent_id}; "
                f"{fallback_explanation}"
            ),
        )

    if decision.intent_id not in available:
        return Classification(
            PlanStatus.KNOWN_INTENT_RECIPE_UNAVAILABLE,
            decision.intent_id,
            decision.confidence,
            decision.explanation,
        )

    return Classification(
        PlanStatus.SUPPORTED,
        decision.intent_id,
        decision.confidence,
        decision.explanation,
    )
