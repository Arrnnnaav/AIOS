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
#: Deck planning (D186). Bounds keep one model answer small and a deck sane.
MAX_SLIDES = 30
MAX_BULLETS = 8
MAX_SLIDE_TITLE = 120
MAX_BULLET_CHARS = 200
#: Deep research (D186): decompose a question into a few sub-questions.
MAX_SUBQUESTIONS = 6
MAX_SUBQUESTION_CHARS = 200
#: One-step task router (D186): which capability a stated task needs.
TASK_INTENTS = (
    "research",
    "deck",
    "research_deck",
    "deck_build",
    "plan",
    "remember",
    "skill",
    "chat",
)
MAX_TASK_ARG_CHARS = 400


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
ACTIONS = ("click", "type", "paste", "paste_text", "copy", "keys", "none")
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
        if (
            not {"instruction", "expected_change"}
            <= set(step)
            <= {
                "instruction",
                "expected_change",
                "action",
                "text",
            }
        ):
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


# --- deck planning (D186): outline-first, a closed layout per slide ----------
# The method every AI deck tool converges on (Gamma, Beautiful.ai): produce a
# slide-by-slide OUTLINE, assign each slide a LAYOUT by its content type. This
# is Orbyn's planner form of that -- a reviewable spec the Act-on-PowerPoint
# path can later build, never execution authority on its own.


class SlideLayout(str, Enum):
    """The content-typed layouts a slide can take (the taxonomy Gamma/
    Beautiful.ai expose as Smart Slides / card types)."""

    TITLE = "title"  # title / cover slide
    SECTION = "section"  # section divider
    BULLETS = "bullets"  # a heading with bullet points
    TWO_COLUMN = "two_column"  # two side-by-side lists
    COMPARISON = "comparison"  # A-vs-B
    TIMELINE = "timeline"  # ordered milestones
    TABLE = "table"  # rows/columns of data
    QUOTE = "quote"  # a pulled quotation
    IMAGE = "image"  # image-led slide with a caption


@dataclass(frozen=True)
class Slide:
    title: str
    bullets: tuple[str, ...]
    layout: SlideLayout


@dataclass(frozen=True)
class DeckSpec:
    title: str
    slides: tuple[Slide, ...]


DECK_SPEC_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "slides"],
    "properties": {
        "title": {"type": "string", "maxLength": MAX_SLIDE_TITLE},
        "slides": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_SLIDES,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "bullets", "layout"],
                "properties": {
                    "title": {"type": "string", "maxLength": MAX_SLIDE_TITLE},
                    "bullets": {
                        "type": "array",
                        "maxItems": MAX_BULLETS,
                        "items": {"type": "string", "maxLength": MAX_BULLET_CHARS},
                    },
                    "layout": {"enum": [layout.value for layout in SlideLayout]},
                },
            },
        },
    },
}


def parse_deck_spec(text: str) -> DeckSpec:
    """Strict, closed parse of a deck plan -- same rules as parse_teach_plan:
    exact fields, bounded sizes, a layout from the closed enum, else INVALID."""

    value = strict_json(text)
    _exact(value, {"title", "slides"}, "deck")
    title = value["title"]
    if not isinstance(title, str) or not title.strip() or len(title) > MAX_SLIDE_TITLE:
        raise _invalid("deck title is invalid")
    slides = value["slides"]
    if not isinstance(slides, list) or not 1 <= len(slides) <= MAX_SLIDES:
        raise _invalid(f"deck must have 1..{MAX_SLIDES} slides")
    parsed = []
    for index, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            raise _invalid(f"slide {index} is not an object")
        _exact(slide, {"title", "bullets", "layout"}, f"slide {index}")
        stitle = slide["title"]
        if (
            not isinstance(stitle, str)
            or not stitle.strip()
            or len(stitle) > MAX_SLIDE_TITLE
        ):
            raise _invalid(f"slide {index} title is invalid")
        bullets = slide["bullets"]
        if not isinstance(bullets, list) or len(bullets) > MAX_BULLETS:
            raise _invalid(f"slide {index} bullets are invalid")
        clean_bullets = []
        for bullet in bullets:
            if (
                not isinstance(bullet, str)
                or not bullet.strip()
                or len(bullet) > MAX_BULLET_CHARS
            ):
                raise _invalid(f"slide {index} has an invalid bullet")
            clean_bullets.append(" ".join(bullet.split()))
        try:
            layout = SlideLayout(slide["layout"])
        except ValueError as exc:
            raise _invalid(f"slide {index} layout is not allowed") from exc
        parsed.append(Slide(" ".join(stitle.split()), tuple(clean_bullets), layout))
    return DeckSpec(" ".join(title.split()), tuple(parsed))


# --- deep research (D186): decompose, then research each sub-question --------
# The loop every "deep research" product runs (OpenAI/Perplexity/Gemini) is:
# decompose the question into a plan, research each part, synthesise with
# citations. This is the plan step as a closed schema; Orbyn's existing
# research() does the cited per-part search, and the owner's Company Brain is
# the durable "one shared context" (rocket.new's Solve pillar applied here).

RESEARCH_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["subquestions"],
    "properties": {
        "subquestions": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_SUBQUESTIONS,
            "items": {"type": "string", "maxLength": MAX_SUBQUESTION_CHARS},
        }
    },
}


MAX_EXTRACTED, MAX_EXTRACTED_CHARS = 12, 300
EXTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["facts"],
    "properties": {
        "facts": {
            "type": "array",
            "maxItems": MAX_EXTRACTED,
            "items": {"type": "string", "maxLength": MAX_EXTRACTED_CHARS},
        }
    },
}


def parse_extracted_facts(text: str) -> tuple[str, ...]:
    """Strict, closed parse of facts pulled from a document: 0..12 short
    statements. Each becomes a CANDIDATE the person reviews; nothing here is
    trusted or used before that."""

    value = strict_json(text)
    _exact(value, {"facts"}, "extracted facts")
    facts = value["facts"]
    if not isinstance(facts, list) or len(facts) > MAX_EXTRACTED:
        raise _invalid(f"at most {MAX_EXTRACTED} facts")
    out = []
    for fact in facts:
        if not isinstance(fact, str) or len(fact) > MAX_EXTRACTED_CHARS:
            raise _invalid("a fact is not a short statement")
        words = " ".join(fact.split())
        if len(words.split()) >= 3:  # a word or two is not a fact
            out.append(words)
    return tuple(out)


def parse_research_plan(text: str) -> tuple[str, ...]:
    """Strict, closed parse of a decomposition -- 1..MAX_SUBQUESTIONS non-empty
    sub-questions, else INVALID_OUTPUT (same discipline as parse_teach_plan)."""

    value = strict_json(text)
    _exact(value, {"subquestions"}, "research plan")
    subs = value["subquestions"]
    if not isinstance(subs, list) or not 1 <= len(subs) <= MAX_SUBQUESTIONS:
        raise _invalid(f"a plan has 1..{MAX_SUBQUESTIONS} sub-questions")
    out = []
    for index, sub in enumerate(subs, start=1):
        if (
            not isinstance(sub, str)
            or not sub.strip()
            or len(sub) > MAX_SUBQUESTION_CHARS
        ):
            raise _invalid(f"sub-question {index} is invalid")
        out.append(" ".join(sub.split()))
    return tuple(out)


# --- one-step task router (D186): classify a task into a capability ----------
# "Anyone types their task; Orbyn runs the right capability." A closed-schema
# classification picks one intent and the core argument; the session dispatches
# to the existing (reviewed) capability. An action task ("do X in an app")
# becomes a PLAN the user approves -- the router never auto-acts (rule 2).

INTENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "argument"],
    "properties": {
        "intent": {"enum": list(TASK_INTENTS)},
        "argument": {"type": "string", "maxLength": MAX_TASK_ARG_CHARS},
    },
}


def parse_intent(text: str) -> tuple[str, str]:
    """Strict parse of the router's answer -> (intent, argument). intent must be
    one of TASK_INTENTS; argument is the task's core (topic/question/need/fact),
    trimmed. INVALID_OUTPUT otherwise."""

    value = strict_json(text)
    _exact(value, {"intent", "argument"}, "intent")
    intent = value["intent"]
    if intent not in TASK_INTENTS:
        raise _invalid("intent is not an allowed capability")
    argument = value["argument"]
    if not isinstance(argument, str) or len(argument) > MAX_TASK_ARG_CHARS:
        raise _invalid("intent argument is invalid")
    return intent, " ".join(argument.split())


# --- crew orchestration (D186): decompose a goal into ordered capability steps
# The manager pattern (CrewAI/OpenAI-Swarm), governed the Orbyn way: a closed
# list of intent-tagged subtasks run in order through the existing reviewed
# capabilities. Results chain through the Company Brain (research files facts,
# later steps recall them). An "act"/"plan" step still only PROPOSES (rule 2).
MAX_CREW_STEPS = 6

CREW_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["steps"],
    "properties": {
        "steps": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_CREW_STEPS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["intent", "argument"],
                "properties": {
                    "intent": {"enum": list(TASK_INTENTS)},
                    "argument": {"type": "string", "maxLength": MAX_TASK_ARG_CHARS},
                },
            },
        }
    },
}


def parse_crew_plan(text: str) -> tuple[tuple[str, str], ...]:
    """Strict, closed parse of a crew plan -> ordered ((intent, argument), ...),
    1..MAX_CREW_STEPS steps, each intent in TASK_INTENTS. INVALID_OUTPUT else."""

    value = strict_json(text)
    _exact(value, {"steps"}, "crew plan")
    steps = value["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_CREW_STEPS:
        raise _invalid(f"a crew plan has 1..{MAX_CREW_STEPS} steps")
    out = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or set(step) != {"intent", "argument"}:
            raise _invalid(f"crew step {index} has wrong fields")
        intent, argument = step["intent"], step["argument"]
        if intent not in TASK_INTENTS:
            raise _invalid(f"crew step {index} intent is not a capability")
        if not isinstance(argument, str) or len(argument) > MAX_TASK_ARG_CHARS:
            raise _invalid(f"crew step {index} argument is invalid")
        out.append((intent, " ".join(argument.split())))
    return tuple(out)


# --- note enhancement (D186): rough notes -> a structured summary -------------
# Granola's core value (clean up the user's OWN notes) without recording audio
# or joining a call: one closed-schema completion turns messy notes into a
# title, a short summary, key points, and action items. All local.
MAX_NOTE_POINTS = 15
MAX_NOTE_LINE = 300

NOTES_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "summary", "key_points", "action_items"],
    "properties": {
        "title": {"type": "string", "maxLength": 120},
        "summary": {"type": "string", "maxLength": 1000},
        "key_points": {
            "type": "array",
            "maxItems": MAX_NOTE_POINTS,
            "items": {"type": "string", "maxLength": MAX_NOTE_LINE},
        },
        "action_items": {
            "type": "array",
            "maxItems": MAX_NOTE_POINTS,
            "items": {"type": "string", "maxLength": MAX_NOTE_LINE},
        },
    },
}


@dataclass(frozen=True)
class NotesSummary:
    title: str
    summary: str
    key_points: tuple[str, ...]
    action_items: tuple[str, ...]


def _note_list(value, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_NOTE_POINTS:
        raise _invalid(f"notes {field} is invalid")
    out = []
    for item in value:
        if not isinstance(item, str) or len(item) > MAX_NOTE_LINE:
            raise _invalid(f"notes {field} has an invalid item")
        cleaned = " ".join(item.split())
        if cleaned:
            out.append(cleaned)
    return tuple(out)


def parse_notes(text: str) -> NotesSummary:
    """Strict closed parse of enhanced notes (same discipline as the others)."""

    value = strict_json(text)
    _exact(value, {"title", "summary", "key_points", "action_items"}, "notes")
    for field in ("title", "summary"):
        if not isinstance(value[field], str) or len(value[field]) > (
            120 if field == "title" else 1000
        ):
            raise _invalid(f"notes {field} is invalid")
    return NotesSummary(
        title=" ".join(value["title"].split()),
        summary=" ".join(value["summary"].split()),
        key_points=_note_list(value["key_points"], "key_points"),
        action_items=_note_list(value["action_items"], "action_items"),
    )


# --- plan critique (D186): advisory review of a plan before Act ---------------
# The Critic/Evaluation capability: a model reads a step plan the user is about
# to run and lists concerns (missing steps, risky/destructive steps, ambiguous
# targets, wrong order). Advisory only -- it never blocks; Act's own gates
# (approval, deny-list, observed-control, ESC) remain the enforcement.
MAX_CONCERNS = 10
CRITIQUE_VERDICTS = ("ready", "caution")

CRITIQUE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "concerns"],
    "properties": {
        "verdict": {"enum": list(CRITIQUE_VERDICTS)},
        "concerns": {
            "type": "array",
            "maxItems": MAX_CONCERNS,
            "items": {"type": "string", "maxLength": 200},
        },
    },
}


@dataclass(frozen=True)
class Critique:
    verdict: str
    concerns: tuple[str, ...]


def parse_critique(text: str) -> Critique:
    """Strict closed parse of a plan critique; INVALID_OUTPUT otherwise."""

    value = strict_json(text)
    _exact(value, {"verdict", "concerns"}, "critique")
    if value["verdict"] not in CRITIQUE_VERDICTS:
        raise _invalid("critique verdict is not allowed")
    raw = value["concerns"]
    if not isinstance(raw, list) or len(raw) > MAX_CONCERNS:
        raise _invalid("critique concerns are invalid")
    concerns = []
    for item in raw:
        if not isinstance(item, str) or len(item) > 200:
            raise _invalid("a critique concern is invalid")
        cleaned = " ".join(item.split())
        if cleaned:
            concerns.append(cleaned)
    return Critique(value["verdict"], tuple(concerns))
