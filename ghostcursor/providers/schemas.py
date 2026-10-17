"""Closed response schemas and a strict parser.

A model answer is accepted only if it is exactly the expected shape: duplicate
keys, extra fields, wrong types, out-of-range values and unknown ids are all
refused. A refused answer is "unavailable" -- there is no fallback to the
model's free text or reasoning.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum

from ghostcursor.providers.errors import FailureKind, ProviderError

ABSTAIN = "ABSTAIN"
MAX_PLAN_STEPS = 20
MAX_INSTRUCTION_CHARS = 200


class ExpectedChange(str, Enum):
    """What a guidance step must cause, in terms the harness can observe."""

    CHOSEN_DISAPPEARS = "chosen_disappears"
    CHOSEN_STATE_CHANGES = "chosen_state_changes"
    FOCUS_MOVES_TO_CHOSEN = "focus_moves_to_chosen"
    NEW_WINDOW_OF_TARGET = "new_window_of_target"
    TITLE_CHANGES = "title_changes"


def _invalid(detail: str) -> ProviderError:
    return ProviderError(FailureKind.INVALID_OUTPUT, detail)


def strict_json(text: str) -> dict:
    """Parse exactly one JSON object; refuse duplicate keys and NaN/Infinity."""

    def pairs(items):
        seen = {}
        for key, value in items:
            if key in seen:
                raise _invalid(f"duplicate key {key!r}")
            seen[key] = value
        return seen

    def no_constant(token):
        raise _invalid(f"non-finite number {token}")

    if not isinstance(text, str) or not text.strip():
        raise _invalid("empty answer")
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped[stripped.find("{") :] if "{" in stripped else stripped
    try:
        value = json.loads(
            stripped, object_pairs_hook=pairs, parse_constant=no_constant
        )
    except ProviderError:
        raise
    except (ValueError, TypeError) as exc:
        raise _invalid("not a single JSON object") from exc
    if not isinstance(value, dict):
        raise _invalid("not a JSON object")
    return value


def _exact(value: dict, keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise _invalid(f"{label} fields are {sorted(value)}, expected {sorted(keys)}")


@dataclass(frozen=True)
class Choice:
    """One System-One choice among offered ids, or abstention."""

    choice: str  # an offered id, or ABSTAIN
    probabilities: dict  # id -> probability, offered ids only

    @property
    def abstained(self) -> bool:
        return self.choice == ABSTAIN

    def top_two(self) -> tuple[float, float]:
        ranked = sorted(self.probabilities.values(), reverse=True) + [0.0, 0.0]
        return ranked[0], ranked[1]


def parse_choice(answer: object, offered: tuple[str, ...]) -> Choice:
    """Validate a Jev ``choice`` answer against the ids actually offered."""

    if not isinstance(answer, dict):
        raise _invalid("choice answer is not an object")
    choice = answer.get("choice")
    allowed = set(offered) | {ABSTAIN}
    if not isinstance(choice, str) or choice not in allowed:
        raise _invalid("choice is not an offered id")
    raw = answer.get("probabilities", {})
    if not isinstance(raw, dict):
        raise _invalid("probabilities is not an object")
    probabilities = {}
    for key, value in raw.items():
        if key not in allowed:
            raise _invalid("probability for an id that was not offered")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise _invalid("probability out of range")
        probabilities[key] = float(value)
    return Choice(choice, probabilities)


#: What Act performs on the step's observed control (D182). Teach ignores it.
ACTIONS = ("click", "type", "paste", "copy", "keys", "none")
MAX_ACTION_TEXT = 2000


@dataclass(frozen=True)
class PlanStep:
    instruction: str
    expected_change: ExpectedChange
    action: str = "click"
    #: what to type for "type"; a key chord such as "ctrl+s" for "keys"
    text: str = ""


@dataclass(frozen=True)
class TeachPlan:
    steps: tuple[PlanStep, ...]


TEACH_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["steps"],
    "properties": {
        "steps": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_PLAN_STEPS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["instruction", "expected_change", "action", "text"],
                "properties": {
                    "instruction": {
                        "type": "string",
                        "maxLength": MAX_INSTRUCTION_CHARS,
                    },
                    "expected_change": {"enum": [c.value for c in ExpectedChange]},
                    "action": {"enum": list(ACTIONS)},
                    "text": {"type": "string", "maxLength": MAX_ACTION_TEXT},
                },
            },
        }
    },
}


def parse_teach_plan(text: str) -> TeachPlan:
    value = strict_json(text)
    _exact(value, {"steps"}, "plan")
    steps = value["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_PLAN_STEPS:
        raise _invalid("plan must have 1..20 steps")
    parsed = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise _invalid(f"step {index} is not an object")
        if not {"instruction", "expected_change"} <= set(step) <= {
            "instruction",
            "expected_change",
            "action",
            "text",
        }:
            raise _invalid(f"step {index} fields are {sorted(step)}")
        action, text = step.get("action", "click"), step.get("text", "")
        if action not in ACTIONS:
            raise _invalid(f"step {index} action is not allowed")
        if not isinstance(text, str) or len(text) > MAX_ACTION_TEXT:
            raise _invalid(f"step {index} text is invalid")
        instruction = step["instruction"]
        if (
            not isinstance(instruction, str)
            or not instruction.strip()
            or len(instruction) > MAX_INSTRUCTION_CHARS
        ):
            raise _invalid(f"step {index} instruction is invalid")
        try:
            change = ExpectedChange(step["expected_change"])
        except ValueError as exc:
            raise _invalid(f"step {index} expected_change is not allowed") from exc
        parsed.append(PlanStep(" ".join(instruction.split()), change, action, text))
    return TeachPlan(tuple(parsed))
