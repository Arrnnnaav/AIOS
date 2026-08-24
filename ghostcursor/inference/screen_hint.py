"""Screen-aware, bounded next-hint inference.

The model sees only a goal and frozen UI primitives. It can select an observed
AutomationId, never a path, coordinate, recipe, or executable action.
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass

from ghostcursor.perception.uia import Element


@dataclass(frozen=True)
class HintDecision:
    automation_id: str | None
    confidence: float
    explanation: str
    source: str  # "model", "fallback", or "invalid-model"


def _fallback(elements: list[Element], allowed_names: tuple[str, ...]) -> HintDecision:
    names = {name.casefold() for name in allowed_names}
    for element in elements:
        if element.source == "uia" and element.name.casefold() in names:
            return HintDecision(element.automation_id, 0.95, "matched the trusted target name", "fallback")
    return HintDecision(None, 0.0, "no trusted observed target matched", "fallback")


def _parse(raw: object, elements: list[Element]) -> HintDecision:
    if isinstance(raw, str):
        # Qwen may include a reasoning block and then a final JSON object.
        # Do not use one greedy {.*} match: if reasoning contains an example
        # object, it joins that example to the final object and breaks JSON.
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE)
        decoder = json.JSONDecoder()
        candidates: list[dict[str, object]] = []
        for match in re.finditer(r"\{", cleaned):
            try:
                candidate, _ = decoder.raw_decode(cleaned[match.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                candidates.append(candidate)
        if not candidates:
            raise ValueError("model response was not JSON")
        raw = candidates[-1]
    if not isinstance(raw, dict):
        raise ValueError("model response was not an object")
    automation_id = raw.get("automation_id", raw.get("target_automation_id", raw.get("target_id")))
    confidence = raw.get("confidence")
    explanation = raw.get("explanation", raw.get("reason", "model selected the target"))
    if isinstance(automation_id, int):
        automation_id = str(automation_id)
    if isinstance(confidence, str):
        try:
            confidence = float(confidence)
        except ValueError:
            confidence = {
                "high": 0.95,
                "medium": 0.75,
                "low": 0.50,
            }.get(confidence.strip().casefold())
    observed_ids = {element.automation_id for element in elements if element.automation_id}
    if automation_id not in observed_ids or not isinstance(confidence, (int, float)) or not isinstance(explanation, str):
        raise ValueError("model selected an unobserved target or returned invalid fields")
    return HintDecision(automation_id, float(confidence), explanation, "model")


def decide_next_hint(
    goal: str,
    elements: list[Element],
    allowed_names: tuple[str, ...],
    *,
    endpoint: str = "http://127.0.0.1:11434",
    model: str = "qwen3:4b-instruct",
    timeout: float = 15.0,
    use_model: bool = True,
) -> HintDecision:
    fallback = _fallback(elements, allowed_names)
    if not use_model:
        return fallback
    prompt = (
        "Return JSON only: {automation_id, confidence, explanation}. "
        "Choose exactly one observed control that best advances the goal. "
        "Do not invent IDs.\n"
        f"Goal: {goal}\nObserved UI elements: "
        + json.dumps([
            {"name": e.name, "control_type": e.control_type, "automation_id": e.automation_id}
            for e in elements
        ], ensure_ascii=False)
    )
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/api/generate",
        data=json.dumps({"model": model, "prompt": prompt, "stream": False}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            outer = json.loads(response.read().decode("utf-8"))
        decision = _parse(outer.get("response", outer), elements)
        if decision.automation_id not in {
            e.automation_id for e in elements
            if e.name.casefold() in {name.casefold() for name in allowed_names}
        }:
            raise ValueError("model selected an observed but untrusted target")
        return decision
    except (OSError, TimeoutError, ConnectionError):
        return fallback
    except (ValueError, KeyError, json.JSONDecodeError):
        return HintDecision(fallback.automation_id, fallback.confidence, "model output was invalid; used trusted fallback", "invalid-model")
