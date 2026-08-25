"""Bounded natural-language planning for GhostCursor.

The planner may classify a goal, but it never supplies executable code or
coordinates.  Execution is always a schema-validated recipe from the local
trusted registry.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ghostcursor.inference.ollama import DEFAULT_MODEL, generate_body
from ghostcursor.reasoning.schema import Recipe


class PlanStatus(Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED_GOAL = "UNSUPPORTED_GOAL"
    KNOWN_INTENT_RECIPE_UNAVAILABLE = "KNOWN_INTENT_RECIPE_UNAVAILABLE"
    INVALID_MODEL_OUTPUT = "INVALID_MODEL_OUTPUT"
    MODEL_UNAVAILABLE_FALLBACK = "MODEL_UNAVAILABLE_FALLBACK"


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


def _model_intent(goal: str, endpoint: str, model: str, timeout: float) -> tuple[str, float, str]:
    intent_ids = tuple(registry())
    prompt = (
        "Return JSON only with keys intent_id, confidence, explanation. "
        f"intent_id must be one of {', '.join(intent_ids)}. "
        f"Goal: {goal}"
    )
    schema = {
        "type": "object",
        "properties": {
            "intent_id": {"type": "string", "enum": list(intent_ids)},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "explanation": {"type": "string", "minLength": 1},
        },
        "required": ["intent_id", "confidence", "explanation"],
        "additionalProperties": False,
    }
    body = json.dumps(
        generate_body(model=model, prompt=prompt, schema=schema)
    ).encode()
    request = urllib.request.Request(endpoint.rstrip("/") + "/api/generate", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        outer = json.loads(response.read().decode("utf-8"))
    raw = outer.get("response", outer)
    if isinstance(raw, str):
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("model response was not JSON")
        raw = json.loads(match.group(0))
    if not isinstance(raw, dict):
        raise ValueError("model response was not an object")
    intent = raw.get("intent_id")
    confidence = raw.get("confidence")
    explanation = raw.get("explanation")
    if (
        intent not in registry()
        or not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0 <= float(confidence) <= 1
        or not isinstance(explanation, str)
        or not explanation.strip()
    ):
        raise ValueError("invalid model fields")
    return intent, float(confidence), explanation


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


def plan_goal(goal: str, *, endpoint: str = "http://127.0.0.1:11434", model: str = DEFAULT_MODEL, timeout: float = 15.0, use_model: bool = True) -> PlanResult:
    """Classify one goal and load only a trusted local recipe."""
    if not goal or not goal.strip():
        return PlanResult(PlanStatus.UNSUPPORTED_GOAL, None, 0.0, "goal is empty")
    fallback_id, fallback_confidence, fallback_explanation = _fallback(goal)
    if use_model:
        try:
            intent_id, confidence, explanation = _model_intent(goal, endpoint, model, timeout)
            spec = registry()[intent_id]
            # A model can choose only a registered ID, but registration alone
            # does not make the choice semantically safe. Qwen mapped "deploy
            # this project" to EXPORT_DATA during the live never-fabricate
            # probe. Any intent carrying executable authority must therefore
            # agree with the deterministic classifier's grounded candidate.
            # Unavailable intents remain honest non-launch results.
            if spec.recipe_path is not None and fallback_id != intent_id:
                if fallback_id is not None:
                    recipe = _trusted_recipe(registry()[fallback_id])
                    return PlanResult(
                        PlanStatus.INVALID_MODEL_OUTPUT,
                        fallback_id,
                        fallback_confidence,
                        (
                            f"model selected ungrounded intent {intent_id}; "
                            f"{fallback_explanation}"
                        ),
                        recipe,
                    )
                return PlanResult(
                    PlanStatus.UNSUPPORTED_GOAL,
                    None,
                    0.0,
                    f"model selected ungrounded intent {intent_id}; no trusted intent matched",
                )
            recipe = _trusted_recipe(spec)
            if recipe is None:
                return PlanResult(PlanStatus.KNOWN_INTENT_RECIPE_UNAVAILABLE, intent_id, confidence, explanation)
            return PlanResult(PlanStatus.SUPPORTED, intent_id, confidence, explanation, recipe)
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
        except (ValueError, KeyError, json.JSONDecodeError):
            if fallback_id:
                recipe = _trusted_recipe(registry()[fallback_id])
                return PlanResult(PlanStatus.INVALID_MODEL_OUTPUT, fallback_id, fallback_confidence, fallback_explanation, recipe)
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
