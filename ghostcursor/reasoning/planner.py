"""Bounded natural-language planning for GhostCursor.

The planner may classify a goal, but it never supplies executable code or
coordinates.  Execution is always a schema-validated recipe from the local
trusted registry.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from ghostcursor.inference.ollama import (
    DEFAULT_MODEL,
    GenerateResponse,
    generate_structured,
)


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
    plan: object | None = None


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


def compiled_registry() -> dict[str, IntentSpec]:
    """Return registrations compiled from the installed v2 catalog."""
    from ghostcursor.packs.activation import load_catalog
    from ghostcursor.packs.compile import compile_planner

    project_root = _ROOT.parent.parent
    return {
        spec.intent_id: spec
        for spec in compile_planner(load_catalog(project_root))
    }


def deterministic_intent(goal: str) -> tuple[str | None, float, str]:
    """Expose the trusted rule classifier to production-parity evaluation.

    The evaluation gate calls this same function rather than maintaining a
    second, potentially drifting implementation of deterministic grounding.
    """
    from ghostcursor.packs.activation import load_catalog
    from ghostcursor.packs.compile import compile_matcher

    project_root = Path(__file__).resolve().parent.parent.parent
    catalog = load_catalog(project_root)
    outcome = compile_matcher(catalog).classify(goal)
    return outcome.intent_id, outcome.confidence, outcome.reason


def _production_intent_ids() -> tuple[str, ...]:
    """Return model-visible IDs from the verified v2 catalog only."""
    from ghostcursor.packs.activation import load_catalog
    from ghostcursor.packs.compile import compile_planner

    project_root = Path(__file__).resolve().parent.parent.parent
    return tuple(sorted(spec.intent_id for spec in compile_planner(load_catalog(project_root))))


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
    intent_ids = _production_intent_ids()
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


def plan_goal(goal: str, *, endpoint: str = "http://127.0.0.1:11434", model: str = DEFAULT_MODEL, timeout: float = 15.0, use_model: bool = True) -> PlanResult:
    """Classify and materialize a goal through the installed v2 authority."""
    return plan_compiled_goal(
        goal,
        endpoint=endpoint,
        model=model,
        timeout=timeout,
        use_model=use_model,
    )


# ---------------------------------------------------------------------------
# Schema v2: classification with no recipe loading
# ---------------------------------------------------------------------------
#
# Classification is pure. It names an intent and says nothing about what may
# run. Materialization -- an active adoption, a live window, and an exactly
# equal application identity -- happens in `ghostcursor.packs.workflow`, which
# is the only thing that can grant execution.


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


def resolve_model_decision(goal: str, decision: IntentDecision) -> Classification:
    """Apply the v2 model policy without loading or returning a recipe."""
    from ghostcursor.packs.activation import load_catalog
    from ghostcursor.packs.compile import compile_matcher, compile_planner

    project_root = Path(__file__).resolve().parent.parent.parent
    catalog = load_catalog(project_root)
    specs = compile_planner(catalog)
    available = frozenset(spec.intent_id for spec in specs if spec.recipe_path is not None)
    matcher = compile_matcher(catalog)

    def deterministic(text: str) -> tuple[str | None, float, str]:
        outcome = matcher.classify(text)
        return outcome.intent_id, outcome.confidence, outcome.reason

    return classify_decision(
        goal,
        decision,
        deterministic=deterministic,
        available=available,
    )


def plan_compiled_goal(
    goal: str,
    *,
    target_title_re: str | None = None,
    endpoint: str = "http://127.0.0.1:11434",
    model: str = DEFAULT_MODEL,
    timeout: float = 15.0,
    use_model: bool = True,
) -> PlanResult:
    """Classify and materialize one goal from the verified v2 catalog.

    This is the production authority seam used by the schema-v2 CLI path.
    Classification is performed by the compiled matcher, while execution is
    granted only after the verified catalog binds an adopted recipe to one
    live target window.  The legacy ``plan_goal`` remains available to the
    model-gate tests until the atomic cutover removes its authority path.
    """
    from ghostcursor.packs.activation import load_catalog
    from ghostcursor.packs.compile import compile_matcher, compile_planner
    from ghostcursor.packs.workflow import WorkflowUnavailable, bind_workflow

    project_root = Path(__file__).resolve().parent.parent.parent
    catalog = load_catalog(project_root)
    specs = compile_planner(catalog)
    available = frozenset(spec.intent_id for spec in specs if spec.recipe_path is not None)
    matcher = compile_matcher(catalog)

    def deterministic(text: str) -> tuple[str | None, float, str]:
        outcome = matcher.classify(text)
        return outcome.intent_id, outcome.confidence, outcome.reason

    fallback = matcher.classify(goal)
    if not use_model:
        classification = classify_decision(
            goal,
            IntentDecision(fallback.intent_id, fallback.confidence, fallback.reason),
            deterministic=deterministic,
            available=available,
        )
    else:
        try:
            decision = infer_intent(
                goal,
                endpoint=endpoint,
                model=model,
                timeout=timeout,
            ).decision
            classification = classify_decision(
                goal,
                decision,
                deterministic=deterministic,
                available=available,
            )
        except (OSError, TimeoutError, ConnectionError) as exc:
            if fallback.intent_id is None:
                return PlanResult(
                    PlanStatus.UNSUPPORTED_GOAL,
                    None,
                    0.0,
                    f"model unavailable ({type(exc).__name__}); no trusted intent matched",
                )
            classification = Classification(
                PlanStatus.MODEL_UNAVAILABLE_FALLBACK,
                fallback.intent_id,
                fallback.confidence,
                f"{fallback.reason} (Ollama request failed: {type(exc).__name__})",
            )
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            if fallback.intent_id is None:
                return PlanResult(
                    PlanStatus.UNSUPPORTED_GOAL,
                    None,
                    0.0,
                    "model output was invalid and no trusted intent matched",
                )
            classification = Classification(
                PlanStatus.INVALID_MODEL_OUTPUT,
                fallback.intent_id,
                fallback.confidence,
                f"{fallback.reason} ({type(exc).__name__})",
            )

    if classification.intent_id is None:
        return PlanResult(
            classification.status,
            None,
            classification.confidence,
            classification.explanation,
        )
    if classification.status not in {
        PlanStatus.SUPPORTED,
        PlanStatus.MODEL_UNAVAILABLE_FALLBACK,
        PlanStatus.INVALID_MODEL_OUTPUT,
    }:
        return PlanResult(
            classification.status,
            classification.intent_id,
            classification.confidence,
            classification.explanation,
        )

    try:
        workflow = bind_workflow(
            catalog,
            classification.intent_id,
            goal,
            target_title_re=target_title_re,
            project_root=project_root,
        )
    except WorkflowUnavailable as exc:
        return PlanResult(
            PlanStatus.KNOWN_INTENT_RECIPE_UNAVAILABLE,
            classification.intent_id,
            classification.confidence,
            str(exc),
        )
    return PlanResult(
        classification.status,
        classification.intent_id,
        classification.confidence,
        classification.explanation,
        workflow,
    )
