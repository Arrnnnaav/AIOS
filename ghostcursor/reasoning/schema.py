"""The step contract — the interface between recipe producers and the loop.

Frozen deliberately: the knowledge base (later) and the reasoning loop (now)
are built against this and nothing else, so they can evolve independently.

See docs/superpowers/specs/2026-08-14-reasoning-and-knowledge-design.md §4.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

# Keys that must never appear in a serialised step. Recipes describe intent;
# coordinates are resolved live on every render, because a persisted pixel is
# wrong the moment the window moves.
_FORBIDDEN_KEYS = {"bbox", "x", "y", "coordinates", "rect", "point"}


class UserAction(str, Enum):
    """What to ask the *human* to do. Never what this program does — the
    system draws hints and never acts (D006)."""

    CLICK = "click"
    PRESS_KEYS = "press_keys"
    TYPE = "type"
    DRAG = "drag"
    SELECT = "select"
    SCROLL = "scroll"
    OBSERVE = "observe"
    WAIT = "wait"


class Risk(str, Enum):
    NORMAL = "normal"
    ELEVATED = "elevated"  # destructive or hard to undo


class VerificationKind(str, Enum):
    ELEMENT_APPEARS = "element_appears"
    ELEMENT_DISAPPEARS = "element_disappears"
    WINDOW_TITLE_MATCHES = "window_title_matches"
    FOCUS_MOVES_TO = "focus_moves_to"
    PROPERTY_CHANGES = "property_changes"
    ANY_MEANINGFUL_CHANGE = "any_meaningful_change"
    USER_CONFIRMS = "user_confirms"


#: Actions that point at a UI element and therefore need something to ground.
_TARGETED_ACTIONS = {
    UserAction.CLICK,
    UserAction.TYPE,
    UserAction.DRAG,
    UserAction.SELECT,
    UserAction.SCROLL,
}

_REQUIRED_ARGS = {
    VerificationKind.ELEMENT_APPEARS: ("target_descriptor",),
    VerificationKind.ELEMENT_DISAPPEARS: ("target_descriptor",),
    VerificationKind.WINDOW_TITLE_MATCHES: ("pattern",),
    # Differs from its descriptor-based siblings: focus crosses the worker
    # thread boundary as a bare AutomationId string (Snapshot.focused_
    # automation_id), never a name, so there is nothing for a descriptor's
    # name half to match. Requiring target_descriptor here would advertise
    # matching this rule cannot perform.
    VerificationKind.FOCUS_MOVES_TO: ("automation_id",),
    VerificationKind.PROPERTY_CHANGES: ("target_descriptor", "property"),
    VerificationKind.ANY_MEANINGFUL_CHANGE: ("scope",),
    VerificationKind.USER_CONFIRMS: (),
}


@dataclass
class ClaimedDescriptor:
    """What documentation can tell us. A guess: may be wrong, may be for a
    different UI language."""

    name: str | None = None
    name_synonyms: list[str] = field(default_factory=list)
    ocr_text: str | None = None
    visual_description: str | None = None

    def is_empty(self) -> bool:
        return not (self.name or self.name_synonyms or self.ocr_text)


# A list index is not a control identity. VS Code exposes these as the only
# non-empty AutomationIds it has, and the command palette's list is
# recency-ordered, so `list_id_5_0` means "most recently used command" and
# changes constantly. Persisting one and hydrating it on a later run points at
# whatever now occupies that index. Measured in D069.
_POSITIONAL_AUTOMATION_ID = re.compile(r"^list_id_\d+_\d+$")


def is_positional_automation_id(automation_id: str | None) -> bool:
    """True for ids that encode a list position rather than a control."""
    return bool(_POSITIONAL_AUTOMATION_ID.match(automation_id or ""))


@dataclass
class ConfirmedObservation:
    """What we learned by grounding successfully. Written at runtime, never by
    distillation — no tutorial ever names an AutomationId."""

    app_version: str
    locales_observed: list[str] = field(default_factory=list)
    automation_id: str | None = None
    control_type: str | None = None
    #: Tie-breaker between otherwise-equal matches only. Never identity —
    #: a tree path breaks whenever layout changes.
    accessibility_path_hint: list[str] = field(default_factory=list)
    last_seen_at: str | None = None


@dataclass
class TargetDescriptor:
    claimed: ClaimedDescriptor = field(default_factory=ClaimedDescriptor)
    confirmed: list[ConfirmedObservation] = field(default_factory=list)


@dataclass
class VerificationRule:
    kind: VerificationKind
    args: dict = field(default_factory=dict)
    timeout_s: float = 30.0


@dataclass
class Step:
    user_action: UserAction
    target_descriptor: TargetDescriptor
    instruction_text: str
    verification_rule: VerificationRule
    risk: Risk = Risk.NORMAL
    preconditions: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Recipe:
    app_id: str
    intent: str
    steps: list[Step]

    def to_dict(self) -> dict:
        return {
            "app_id": self.app_id,
            "intent": self.intent,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Recipe":
        steps = []
        for i, raw in enumerate(data["steps"]):
            # Check for coordinates anywhere in the step, recursively
            leaked = _has_forbidden_keys(raw)
            if leaked:
                raise ValueError(
                    "step stores coordinates; recipes store "
                    "intent only, coordinates are resolved live"
                )
            step = _step_from_dict(raw)
            # Validate the step before accepting it
            errors = validate_step(step)
            if errors:
                raise ValueError(f"step {i} is invalid: {'; '.join(errors)}")
            steps.append(step)
        return cls(app_id=data["app_id"], intent=data["intent"], steps=steps)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> "Recipe":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _has_forbidden_keys(obj: object) -> str | None:
    """Recursively search obj for any forbidden coordinate keys.

    Returns the first forbidden key found, or None if clean.
    """
    if isinstance(obj, dict):
        leaked = _FORBIDDEN_KEYS & set(obj)
        if leaked:
            return sorted(leaked)[0]
        for value in obj.values():
            result = _has_forbidden_keys(value)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _has_forbidden_keys(item)
            if result:
                return result
    return None


def _step_from_dict(raw: dict) -> Step:
    td = raw["target_descriptor"]
    return Step(
        user_action=UserAction(raw["user_action"]),
        target_descriptor=TargetDescriptor(
            claimed=ClaimedDescriptor(**td.get("claimed", {})),
            confirmed=[ConfirmedObservation(**c) for c in td.get("confirmed", [])],
        ),
        instruction_text=raw["instruction_text"],
        verification_rule=VerificationRule(
            kind=VerificationKind(raw["verification_rule"]["kind"]),
            args=raw["verification_rule"].get("args", {}),
            timeout_s=raw["verification_rule"].get("timeout_s", 30.0),
        ),
        risk=Risk(raw.get("risk", "normal")),
        preconditions=raw.get("preconditions", []),
        provenance=raw.get("provenance", {}),
    )


#: Required args that verify() never reads as an identifier, so emptiness
#: cannot make the rule degenerate. Only ANY_MEANINGFUL_CHANGE's `scope`
#: qualifies today: verify() ignores it entirely and compares whole-snapshot
#: element identity, so `{}` means "the whole window" and is a legitimate
#: recipe. Every other required arg names something the rule must match, and
#: an empty one silently breaks it in one direction or the other.
#:
#: That `scope` is REQUIRED but never read is its own smell -- see
#: docs/superpowers/FOLLOWUPS.md. It is left alone here because narrowing this
#: check is not the place to change what a verification rule accepts.
_MAY_BE_EMPTY = {
    (VerificationKind.ANY_MEANINGFUL_CHANGE, "scope"),
}


def _is_empty(value) -> bool:
    """Whether a supplied verification arg carries no information.

    Whitespace counts as empty: a pattern or an AutomationId of "   " is a
    typo, not an intention, and it fails in exactly the same silent way.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (dict, list, tuple, set)):
        return not value
    return False


def validate_step(step: Step) -> list[str]:
    """Return human-readable problems with a step. Empty means valid."""
    errors: list[str] = []
    rule = step.verification_rule

    # Spec §7: any_meaningful_change fires on unrelated activity, so it must
    # never be what declares a destructive step complete.
    if (
        step.risk is Risk.ELEVATED
        and rule.kind is VerificationKind.ANY_MEANINGFUL_CHANGE
    ):
        errors.append(
            "elevated-risk step cannot be verified by any_meaningful_change; "
            "use an element-level rule or user_confirms"
        )

    for required in _REQUIRED_ARGS[rule.kind]:
        if required not in rule.args:
            errors.append(
                f"verification rule {rule.kind.value} requires arg {required!r}"
            )
        elif (rule.kind, required) not in _MAY_BE_EMPTY and _is_empty(
            rule.args[required]
        ):
            # Present but empty is worse than missing, because it validates.
            # Every rule kind degenerates on an empty required arg, in one of
            # two directions, and BOTH are silent:
            #
            #   never satisfied -- element_appears / element_disappears with an
            #   empty descriptor match nothing, and focus_moves_to with an empty
            #   automation_id can never match, so the tour dwells on that step
            #   forever without saying why. That is verbatim the failure the
            #   NotImplementedError on focus_moves_to used to guard against, and
            #   this project's rule for it is to fail LOUDLY.
            #
            #   always satisfied -- window_title_matches with an empty pattern is
            #   `re.search("", title)`, which matches everything, so the step
            #   completes without the user having done anything. In a system
            #   whose whole premise is verifying the world actually changed,
            #   auto-satisfying on no evidence is the worse of the two.
            #
            # Validation is the only place either can be caught: verify()
            # returning False for an unnameable target is correct on its own
            # terms and must not change.
            errors.append(
                f"verification rule {rule.kind.value} has an empty "
                f"{required!r}; an empty value can never identify anything, so "
                "the step would either never complete or complete on no evidence"
            )

    for option in (
        "fail_after_timeout",
        "timeout_from_hint",
        "accept_if_already_present",
    ):
        if option in rule.args and not isinstance(rule.args[option], bool):
            errors.append(f"verification option {option!r} must be a boolean")

    if (
        rule.args.get("accept_if_already_present") is True
        and rule.kind is not VerificationKind.ELEMENT_APPEARS
    ):
        errors.append(
            "accept_if_already_present is supported only for element_appears"
        )

    if (
        rule.args.get("timeout_from_hint") is True
        and rule.args.get("fail_after_timeout") is not True
    ):
        errors.append(
            "timeout_from_hint requires fail_after_timeout so the deadline has an effect"
        )

    if (
        step.user_action in _TARGETED_ACTIONS
        and step.target_descriptor.claimed.is_empty()
    ):
        if not step.target_descriptor.confirmed:
            errors.append(
                f"{step.user_action.value} step has nothing to identify its target with"
            )

    if not step.instruction_text.strip():
        errors.append("step has no instruction_text to show the user")

    return errors
