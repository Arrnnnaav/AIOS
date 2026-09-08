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
from ghostcursor.packs.authority import AuthorizedActionIntent, AuthorizedIntent


class PlanStatus(Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED_GOAL = "UNSUPPORTED_GOAL"
    KNOWN_INTENT_RECIPE_UNAVAILABLE = "KNOWN_INTENT_RECIPE_UNAVAILABLE"
    KNOWN_INTENT_ACTION_PLAN_UNAVAILABLE = "KNOWN_INTENT_ACTION_PLAN_UNAVAILABLE"
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
    target_state: str | None = None
    target_candidates: tuple[object, ...] = ()


@dataclass(frozen=True)
class IntentDecision:
    intent_id: str | None
    confidence: float
    explanation: str


class CandidateSource(str, Enum):
    MODEL = "model"
    DETERMINISTIC = "deterministic"
    MODEL_UNAVAILABLE = "model_unavailable"
    INVALID_MODEL = "invalid_model"


@dataclass(frozen=True)
class IntentCandidate:
    source: CandidateSource
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
    from ghostcursor.packs.compile import compile_planner
    from ghostcursor.plugins.platform import load_runtime_catalog

    return {
        spec.intent_id: spec
        for spec in compile_planner(load_runtime_catalog())
    }


def deterministic_intent(goal: str) -> tuple[str | None, float, str]:
    """Expose the trusted rule classifier to production-parity evaluation.

    The evaluation gate calls this same function rather than maintaining a
    second, potentially drifting implementation of deterministic grounding.
    """
    from ghostcursor.packs.compile import compile_matcher
    from ghostcursor.plugins.platform import load_runtime_catalog

    catalog = load_runtime_catalog()
    outcome = compile_matcher(catalog).classify(goal)
    return outcome.intent_id, outcome.confidence, outcome.reason


def _production_intent_ids() -> tuple[str, ...]:
    """Return model-visible IDs from the verified v2 catalog only."""
    from ghostcursor.packs.compile import compile_planner
    from ghostcursor.plugins.platform import load_runtime_catalog

    return tuple(sorted(spec.intent_id for spec in compile_planner(load_runtime_catalog())))


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
# run. Teach materialization still requires an active adoption and live target;
# Act proposal authority instead binds one signed action plan and then crosses
# its own graph approval, target, per-node, and verification gates (D120).


@dataclass(frozen=True)
class Classification:
    """The result of naming an intent. Carries no recipe and no authority."""

    status: PlanStatus
    intent_id: str | None
    confidence: float
    explanation: str


@dataclass(frozen=True)
class AuthorizationResult:
    """The result of the one policy gate; only ``authorized`` may execute."""

    status: PlanStatus
    intent_id: str | None
    confidence: float
    explanation: str
    authorized: AuthorizedIntent | AuthorizedActionIntent | None = None


def _policy_classification(
    goal: str,
    decision: IntentDecision,
    *,
    deterministic: Callable[[str], tuple[str | None, float, str]],
    registered: frozenset[str],
    available: frozenset[str],
    unavailable_status: PlanStatus = PlanStatus.KNOWN_INTENT_RECIPE_UNAVAILABLE,
) -> Classification:
    """Classify an untrusted name without granting execution authority."""

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

    # Unknown is not unavailable. The latter means a verified catalog knows
    # the ID but has no active recipe; a fictional name has no such standing.
    if decision.intent_id not in registered:
        if fallback_id is None:
            return Classification(
                PlanStatus.INVALID_MODEL_OUTPUT,
                None,
                0.0,
                f"model selected unknown intent {decision.intent_id}",
            )
        return Classification(
            PlanStatus.INVALID_MODEL_OUTPUT,
            fallback_id,
            fallback_confidence,
            f"model selected unknown intent {decision.intent_id}; {fallback_explanation}",
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
            unavailable_status,
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


def classify_decision(
    goal: str,
    decision: IntentDecision,
    *,
    deterministic: Callable[[str], tuple[str | None, float, str]],
    available: frozenset[str],
) -> Classification:
    """Apply the authority policy without touching a recipe.

    `available` names the intents that have authority in the caller's selected
    domain: adopted recipes for Teach, or unique signed plans for Act. It is
    consulted only to tell an ungrounded *available* intent from an ungrounded
    unavailable one, which is the distinction D058 turns on -- a registered ID
    is an allowlist boundary the model may name, never semantic evidence that
    it named the right one.

    The model can never widen this. Where its choice and the deterministic
    classifier's grounded intent disagree, the deterministic one wins if it
    exists and nothing runs if it does not.
    """
    # Compatibility-only API for focused pure-policy tests. Production calls
    # ``authorize_intent`` with the real registered set and exact catalog.
    return _policy_classification(
        goal,
        decision,
        deterministic=deterministic,
        registered=available | ({decision.intent_id} if decision.intent_id else set()),
        available=available,
    )


def authorize_intent(
    catalog,
    goal: str,
    candidate: IntentCandidate,
    *,
    action_context=None,
    action_store=None,
) -> AuthorizationResult:
    """The only function that may mint execution authority from an intent name.

    The default authority is an adopted Teach recipe.  Supplying an exact
    ``PluginStore`` together with the exact ``CompositionContext`` it issued
    from signed on-disk state asks for a signed Act plan instead.  Shape alone
    is deliberately insufficient.  The two cases produce distinct token
    types: neither an Act mode nor a registered intent name can turn an
    unadopted recipe into Teach authority, and an adopted recipe cannot stand
    in for a signed action plan.
    """

    from ghostcursor.packs.compile import compile_matcher, compile_planner

    specs = compile_planner(catalog)
    registered = frozenset(spec.intent_id for spec in specs)
    action_bindings = {}
    action_requested = action_context is not None or action_store is not None
    if not action_requested:
        available = frozenset(
            spec.intent_id for spec in specs if spec.recipe_path is not None
        )
    else:
        from ghostcursor.plugins.store import (
            AdapterDescriptor,
            CompositionContext,
            PluginStore,
        )

        # Identity is intentional. A separately loaded or caller-reassembled
        # context could describe a different active-index epoch even when its
        # fields happen to look equal.
        if (
            type(action_store) is not PluginStore
            or type(action_context) is not CompositionContext
            or action_context.catalog is not catalog
            or not action_store.owns_composition_context(action_context)
        ):
            return AuthorizationResult(
                PlanStatus.KNOWN_INTENT_ACTION_PLAN_UNAVAILABLE,
                candidate.intent_id,
                candidate.confidence,
                "Act authorization requires the composition context that owns the catalog",
            )
        candidates = {}
        for pack in catalog.packs.values():
            plugin_id = pack.plugin_id or pack.pack_id
            descriptor = action_context.adapters.get(plugin_id)
            if not isinstance(descriptor, AdapterDescriptor):
                continue
            if (
                descriptor.plugin_id != plugin_id
                or descriptor.plugin_version != (pack.plugin_version or "legacy")
                or descriptor.manifest_sha256
                != (pack.plugin_manifest_sha256 or pack.pack.sha256)
            ):
                continue
            for plan in descriptor.plans.values():
                if (
                    plan.intent_id not in pack.intents
                    or plan.plugin_id != descriptor.plugin_id
                    or plan.plugin_version != descriptor.plugin_version
                    or plan.adapter_sha256 != descriptor.adapter_sha256
                ):
                    continue
                candidates.setdefault(plan.intent_id, []).append(
                    (pack, descriptor, plan)
                )
        action_bindings = {
            intent_id: values[0]
            for intent_id, values in candidates.items()
            if len(values) == 1
        }
        available = frozenset(action_bindings)
    matcher = compile_matcher(catalog)

    def deterministic(text: str) -> tuple[str | None, float, str]:
        outcome = matcher.classify(text)
        return outcome.intent_id, outcome.confidence, outcome.reason

    classification = _policy_classification(
        goal,
        IntentDecision(candidate.intent_id, candidate.confidence, candidate.explanation),
        deterministic=deterministic,
        registered=registered,
        available=available,
        unavailable_status=(
            PlanStatus.KNOWN_INTENT_RECIPE_UNAVAILABLE
            if not action_requested
            else PlanStatus.KNOWN_INTENT_ACTION_PLAN_UNAVAILABLE
        ),
    )
    status = classification.status
    if candidate.source is CandidateSource.MODEL_UNAVAILABLE and status is PlanStatus.SUPPORTED:
        status = PlanStatus.MODEL_UNAVAILABLE_FALLBACK
    elif candidate.source is CandidateSource.INVALID_MODEL and status in {
        PlanStatus.SUPPORTED,
        PlanStatus.INVALID_MODEL_OUTPUT,
    }:
        status = PlanStatus.INVALID_MODEL_OUTPUT

    executable = status in {
        PlanStatus.SUPPORTED,
        PlanStatus.MODEL_UNAVAILABLE_FALLBACK,
        PlanStatus.INVALID_MODEL_OUTPUT,
    }
    intent_id = classification.intent_id
    if not executable or intent_id is None:
        return AuthorizationResult(
            status, intent_id, classification.confidence, classification.explanation
        )

    if catalog.index_sha256 is None:
        return AuthorizationResult(
            PlanStatus.KNOWN_INTENT_RECIPE_UNAVAILABLE,
            intent_id,
            classification.confidence,
            "catalog carries no authority digest",
        )
    if action_context is not None:
        binding = action_bindings.get(intent_id)
        if binding is None:
            return AuthorizationResult(
                PlanStatus.KNOWN_INTENT_ACTION_PLAN_UNAVAILABLE,
                intent_id,
                classification.confidence,
                f"intent {intent_id} has no unique signed action plan",
            )
        pack, descriptor, plan = binding
        token = AuthorizedActionIntent(
            plugin_id=descriptor.plugin_id,
            plugin_version=descriptor.plugin_version,
            plugin_manifest_sha256=descriptor.manifest_sha256,
            pack_id=pack.pack_id,
            intent_id=intent_id,
            catalog_sha256=catalog.index_sha256,
            catalog_generation=catalog.generation,
            activation_generation=pack.activation_generation,
            activation_sha256=pack.activation_sha256,
            pack_sha256=pack.pack.sha256,
            intent_sha256=pack.intents[intent_id].intent.sha256,
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            adapter_sha256=descriptor.adapter_sha256,
        )
        return AuthorizationResult(
            status,
            intent_id,
            classification.confidence,
            classification.explanation,
            token,
        )

    for pack in catalog.packs.values():
        intent = pack.intents.get(intent_id)
        if intent is None:
            continue
        adoption = intent.active_adoption
        if adoption is None:
            return AuthorizationResult(
                PlanStatus.KNOWN_INTENT_RECIPE_UNAVAILABLE,
                intent_id,
                classification.confidence,
                f"intent {intent_id} has no active adoption",
            )
        token = AuthorizedIntent(
            plugin_id=pack.plugin_id or pack.pack_id,
            plugin_version=pack.plugin_version or "legacy",
            plugin_manifest_sha256=pack.plugin_manifest_sha256 or pack.pack.sha256,
            pack_id=pack.pack_id,
            intent_id=intent_id,
            catalog_sha256=catalog.index_sha256,
            catalog_generation=catalog.generation,
            activation_generation=pack.activation_generation,
            activation_sha256=pack.activation_sha256,
            pack_sha256=pack.pack.sha256,
            intent_sha256=intent.intent.sha256,
            adoption_id=adoption.adoption_id,
            recipe_sha256=adoption.recipe.sha256,
            evidence_sha256=adoption.evidence.sha256,
        )
        return AuthorizationResult(
            status,
            intent_id,
            classification.confidence,
            classification.explanation,
            token,
        )
    return AuthorizationResult(
        PlanStatus.UNSUPPORTED_GOAL,
        None,
        0.0,
        f"no verified pack provides intent {intent_id!r}",
    )


def resolve_model_decision(goal: str, decision: IntentDecision) -> Classification:
    """Apply the v2 model policy without loading or returning a recipe."""
    from ghostcursor.packs.compile import compile_matcher
    from ghostcursor.plugins.platform import load_runtime_catalog

    catalog = load_runtime_catalog()
    # Build once here only to retain this evaluation seam's assertion that the
    # catalog is compilable; authorization owns the actual policy decision.
    compile_matcher(catalog)
    result = authorize_intent(
        catalog,
        goal,
        IntentCandidate(
            CandidateSource.MODEL,
            decision.intent_id,
            decision.confidence,
            decision.explanation,
        ),
    )
    return Classification(
        result.status, result.intent_id, result.confidence, result.explanation
    )


def plan_compiled_goal(
    goal: str,
    *,
    target_title_re: str | None = None,
    target_hwnd: int | None = None,
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
    from ghostcursor.packs.compile import compile_matcher, compile_planner
    from ghostcursor.packs.workflow import (
        TargetChoiceRequired,
        TargetNotRunning,
        WorkflowUnavailable,
        bind_workflow,
    )
    from ghostcursor.plugins.platform import load_runtime_catalog

    catalog = load_runtime_catalog()
    compile_planner(catalog)
    matcher = compile_matcher(catalog)

    fallback = matcher.classify(goal)
    if not use_model:
        candidate = IntentCandidate(
            CandidateSource.DETERMINISTIC,
            fallback.intent_id,
            fallback.confidence,
            fallback.reason,
        )
    else:
        try:
            decision = infer_intent(
                goal,
                endpoint=endpoint,
                model=model,
                timeout=timeout,
            ).decision
            candidate = IntentCandidate(
                CandidateSource.MODEL,
                decision.intent_id,
                decision.confidence,
                decision.explanation,
            )
        except (OSError, TimeoutError, ConnectionError) as exc:
            candidate = IntentCandidate(
                CandidateSource.MODEL_UNAVAILABLE,
                fallback.intent_id,
                fallback.confidence,
                f"{fallback.reason} (Ollama request failed: {type(exc).__name__})",
            )
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            candidate = IntentCandidate(
                CandidateSource.INVALID_MODEL,
                fallback.intent_id,
                fallback.confidence,
                f"{fallback.reason} ({type(exc).__name__})",
            )

    authorization = authorize_intent(catalog, goal, candidate)
    if authorization.authorized is None:
        return PlanResult(
            authorization.status,
            authorization.intent_id,
            authorization.confidence,
            authorization.explanation,
        )

    try:
        workflow = bind_workflow(
            authorization.authorized,
            goal,
            target_title_re=target_title_re,
            target_hwnd=target_hwnd,
        )
    except TargetChoiceRequired as exc:
        return PlanResult(
            PlanStatus.KNOWN_INTENT_RECIPE_UNAVAILABLE,
            authorization.intent_id,
            authorization.confidence,
            str(exc),
            target_state="target_choice_required",
            target_candidates=exc.candidates,
        )
    except TargetNotRunning as exc:
        return PlanResult(
            PlanStatus.KNOWN_INTENT_RECIPE_UNAVAILABLE,
            authorization.intent_id,
            authorization.confidence,
            str(exc),
            target_state="target_not_running",
        )
    except WorkflowUnavailable as exc:
        return PlanResult(
            PlanStatus.KNOWN_INTENT_RECIPE_UNAVAILABLE,
            authorization.intent_id,
            authorization.confidence,
            str(exc),
        )
    return PlanResult(
        authorization.status,
        authorization.intent_id,
        authorization.confidence,
        authorization.explanation,
        workflow,
    )
