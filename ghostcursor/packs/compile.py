"""Compile a verified pack catalog into planner registrations and a matcher.

Every function here is pure: it reads a `VerifiedCatalog` and returns frozen
values.  Nothing in this module touches the filesystem, the screen, a model, or
the reasoning loop, so a compiled matcher can be exercised in the hermetic lane
with no desktop at all.

The matcher implements D072's grammar exactly and nothing beyond it:

* Two tiers.  `exact` is 0.95 and `heuristic` is 0.85.  Confidence is a
  property of the tier, never a number an artifact may declare.
* Fixed depth.  A heuristic rule is `all_of: [clause]`, a clause is
  `any_of: [term]`, and a term is one of `token`, `alias`, `path`.  There is no
  recursion, no negation, and no plugin form.
* Tier by tier.  Every exact rule across every intent is evaluated before any
  heuristic rule.
* Fail closed on ambiguity.  Several rules matching the *same* intent
  deduplicate to that intent; two *different* intents matching inside one tier
  resolve to no intent at all.

`_fallback()` in `ghostcursor.reasoning.planner` remains the production matcher
until the atomic cutover.  This module is compared against it by
`tests/test_compiled_matcher.py`; production does not choose between them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from ghostcursor.packs.activation import (
    Diagnostic,
    DiagnosticCode,
    IntentAvailability,
    VerifiedCatalog,
    VerifiedPack,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ghostcursor.reasoning.planner import IntentSpec

EXACT_CONFIDENCE = 0.95
HEURISTIC_CONFIDENCE = 0.85

#: The only confidences a compiled matcher can produce.  An artifact cannot
#: widen this set, because artifacts never carry a confidence at all.
MATCH_CONFIDENCES = (0.0, HEURISTIC_CONFIDENCE, EXACT_CONFIDENCE)


# --------------------------------------------------------------------------
# The path predicate
#
# One definition, shared by the matcher and by goal-derived title verification.
# Two definitions would let a goal ground through a path that the verifier then
# refuses to recognise.  Recognised forms only: a bare relative forward slash is
# prose (`and/or`, `csv/tsv`), not a path, and a loose backslash standing alone
# between words is prose too.
# --------------------------------------------------------------------------

_DRIVE_ROOTED = re.compile(r"\A[a-z]:[\\/][^\\/]")
_UNC = re.compile(r"\A\\\\[^\\/]+\\[^\\/]")
_DOT_RELATIVE = re.compile(r"\A\.{1,2}[\\/][^\\/]")
_RELATIVE_BACKSLASH = re.compile(r"\A[^\\/]+\\[^\\/]")

_PATH_FORMS = (_DRIVE_ROOTED, _UNC, _DOT_RELATIVE, _RELATIVE_BACKSLASH)


def is_path_reference(token: str) -> bool:
    """Whether one whitespace-delimited token is a recognised path reference.

    The separator has to join non-separator text on both sides, which is what
    separates a relative backslash path from the bare backslash in `foo \\ bar`.
    """
    candidate = token.casefold()
    return any(form.match(candidate) is not None for form in _PATH_FORMS)


def normalise_goal(goal: str) -> str:
    """Case-folded, whitespace-collapsed goal text.

    Every literal in an artifact is required to already be in this form, so
    matching never has to normalise one side at match time.
    """
    return " ".join(goal.casefold().split())


def path_tokens(goal: str) -> tuple[str, ...]:
    """The tokens of `goal` that are recognised path references."""
    return tuple(
        token for token in normalise_goal(goal).split() if is_path_reference(token)
    )


# --------------------------------------------------------------------------
# Compiled matcher terms
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LiteralTerm:
    """A `token` or a resolved `alias`: any listed literal, as a substring.

    An alias is resolved to its members at compile time, so the matcher never
    performs a lookup that could fail while classifying a goal.
    """

    literals: tuple[str, ...]

    def matches(self, normalized: str, tokens: tuple[str, ...]) -> bool:
        return any(literal in normalized for literal in self.literals)


@dataclass(frozen=True)
class PathTerm:
    """The `path` primitive: some token of the goal is a path reference."""

    def matches(self, normalized: str, tokens: tuple[str, ...]) -> bool:
        return any(is_path_reference(token) for token in tokens)


Term = LiteralTerm | PathTerm
Clause = tuple[Term, ...]
HeuristicRule = tuple[Clause, ...]


@dataclass(frozen=True)
class CompiledIntent:
    intent_id: str
    pack_id: str
    canonical_target: str | None
    availability: IntentAvailability
    exact_phrases: tuple[str, ...]
    heuristic_rules: tuple[HeuristicRule, ...]

    def matches_exact(self, normalized: str) -> bool:
        return normalized in self.exact_phrases

    def matches_heuristic(self, normalized: str, tokens: tuple[str, ...]) -> bool:
        """Whether *any* of this intent's heuristic rules is satisfied.

        This is where D072's rule deduplication lives: the answer is one
        boolean per intent, so an intent declaring both a broad and a narrow
        rule contributes one match and can never look ambiguous with itself.
        """
        return any(
            all(
                any(term.matches(normalized, tokens) for term in clause)
                for clause in rule
            )
            for rule in self.heuristic_rules
        )


@dataclass(frozen=True)
class MatchOutcome:
    """What the compiled matcher concluded about one goal.

    `kind` is `matched`, `no_match`, or `ambiguous`.  Ambiguity is reported
    distinctly from absence because they are different facts, even though
    neither grounds a workflow.
    """

    intent_id: str | None
    confidence: float
    kind: str
    reason: str

    @property
    def grounded(self) -> bool:
        return self.intent_id is not None


class UnknownAliasError(ValueError):
    """A rule referenced an alias its pack does not declare."""


@dataclass(frozen=True)
class CompiledMatcher:
    intents: tuple[CompiledIntent, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    def classify(self, goal: str) -> MatchOutcome:
        normalized = normalise_goal(goal)
        tokens = tuple(normalized.split())

        exact = _matching_ids(
            intent for intent in self.intents if intent.matches_exact(normalized)
        )
        outcome = _resolve(exact, EXACT_CONFIDENCE, "exact")
        if outcome is not None:
            return outcome

        heuristic = _matching_ids(
            intent
            for intent in self.intents
            if intent.matches_heuristic(normalized, tokens)
        )
        outcome = _resolve(heuristic, HEURISTIC_CONFIDENCE, "heuristic")
        if outcome is not None:
            return outcome

        return MatchOutcome(None, 0.0, "no_match", "no trusted intent matched")


def _matching_ids(matched: Iterable[CompiledIntent]) -> tuple[str, ...]:
    """The ids of the matching intents, in catalog order.

    Deliberately not a deduplicating step.  Rule-level deduplication already
    happened inside each intent, and intent ids are unique across a verified
    catalog, so a repeated id here would mean the catalog was built wrong.
    Collapsing it silently would hide that; letting it reach the ambiguity
    check fails closed instead.
    """
    return tuple(intent.intent_id for intent in matched)


def _resolve(
    intent_ids: tuple[str, ...], confidence: float, tier: str
) -> MatchOutcome | None:
    """Turn one tier's matches into an outcome, or `None` to fall through."""
    if not intent_ids:
        return None
    if len(intent_ids) > 1:
        names = ", ".join(sorted(intent_ids))
        return MatchOutcome(
            None,
            0.0,
            "ambiguous",
            f"{tier} tier matched more than one intent ({names})",
        )
    return MatchOutcome(
        intent_ids[0],
        confidence,
        "matched",
        f"matched {intent_ids[0]} on the {tier} tier",
    )


# --------------------------------------------------------------------------
# Compilation
# --------------------------------------------------------------------------


def _compile_terms(terms: Any, aliases: Mapping[str, Any]) -> Clause:
    compiled: list[Term] = []
    for term in terms:
        primitive, value = next(iter(term.items()))
        if primitive == "token":
            compiled.append(LiteralTerm((value,)))
        elif primitive == "alias":
            if value not in aliases:
                # A missing alias is a hard failure.  Skipping the term would
                # silently widen the rule: an `any_of` clause with one term
                # removed is a different rule, and a clause that lost every
                # term would become vacuously true.
                raise UnknownAliasError(f"rule references undeclared alias {value!r}")
            compiled.append(LiteralTerm(tuple(aliases[value])))
        else:  # `path`; the schema admits no other primitive
            compiled.append(PathTerm())
    return tuple(compiled)


def _compile_rules(
    intent_value: Any, aliases: Mapping[str, Any]
) -> tuple[tuple[str, ...], tuple[HeuristicRule, ...]]:
    phrases: list[str] = []
    heuristic: list[HeuristicRule] = []
    for rule in intent_value["rules"]:
        if rule["tier"] == "exact":
            phrases.extend(rule["phrases"])
            continue
        heuristic.append(
            tuple(
                _compile_terms(clause["any_of"], aliases) for clause in rule["all_of"]
            )
        )
    return tuple(phrases), tuple(heuristic)


def compile_matcher(catalog: VerifiedCatalog) -> CompiledMatcher:
    """Compile every verified intent in `catalog` into a deterministic matcher.

    An intent whose rules cannot be compiled contributes no rules and earns a
    diagnostic.  It can then never match, which is the fail-closed direction:
    the alternative is a partially compiled rule that matches more goals than
    the artifact declared.
    """
    if not catalog.root_valid:
        return CompiledMatcher((), ())

    intents: list[CompiledIntent] = []
    diagnostics: list[Diagnostic] = []
    for pack in catalog.packs.values():
        aliases = pack.pack_value["aliases"]
        for intent_id, verified in pack.intents.items():
            try:
                phrases, heuristic = _compile_rules(verified.intent_value, aliases)
            except UnknownAliasError as exc:
                diagnostics.append(
                    Diagnostic(
                        DiagnosticCode.INTENT_INVALID,
                        str(exc),
                        pack_id=pack.pack_id,
                        intent_id=intent_id,
                    )
                )
                phrases, heuristic = (), ()
            intents.append(
                CompiledIntent(
                    intent_id=intent_id,
                    pack_id=pack.pack_id,
                    canonical_target=verified.intent_value["canonical_target"],
                    availability=verified.availability,
                    exact_phrases=phrases,
                    heuristic_rules=heuristic,
                )
            )
    return CompiledMatcher(tuple(intents), tuple(diagnostics))


def _recipe_path(pack: VerifiedPack, intent_id: str) -> Path | None:
    verified = pack.intents[intent_id]
    if verified.availability is not IntentAvailability.ACTIVE:
        return None
    adoption = verified.active_adoption
    if adoption is None:  # pragma: no cover - availability implies an adoption
        return None
    return pack.directory / adoption.recipe.path


def compile_planner(catalog: VerifiedCatalog) -> tuple["IntentSpec", ...]:
    """Compile the planner's intent registrations from a verified catalog.

    Registration and recipe authority are separate.  Every verified intent is
    registered so the planner can name it, but only an intent with an active
    adoption carries a recipe path: an intent whose recipe is unavailable is
    still a known intent, which is what makes
    `KNOWN_INTENT_RECIPE_UNAVAILABLE` distinguishable from an unsupported goal.
    """
    # Imported here, not at module scope: `planner` imports the Ollama
    # transport, and at cutover `planner` imports this module.  A module-level
    # import would make that a cycle and would pull the inference stack into
    # every consumer of the pack layer.
    from ghostcursor.reasoning.planner import IntentSpec

    if not catalog.root_valid:
        return ()

    matcher = compile_matcher(catalog)
    by_id = {intent.intent_id: intent for intent in matcher.intents}

    specs: list[IntentSpec] = []
    for pack in catalog.packs.values():
        for intent_id in pack.intents:
            compiled = by_id[intent_id]
            specs.append(
                IntentSpec(
                    intent_id=intent_id,
                    phrases=compiled.exact_phrases,
                    recipe_path=_recipe_path(pack, intent_id),
                    canonical_target=compiled.canonical_target,
                )
            )
    return tuple(specs)
