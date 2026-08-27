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
from types import MappingProxyType
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

    An intent whose rules cannot be compiled is **excluded entirely** and earns
    a diagnostic.  Contributing an empty rule set instead would leave it
    unmatchable but still registered, and a registered id is model-visible and
    carries recipe authority -- so a cross-file-invalid artifact would keep a
    seat at execution.  The spec scopes an invalid intent artifact to
    "excluded from matching + registry diagnostic", and this is the single
    place that exclusion is decided: `compile_planner()` registers exactly what
    survives here.
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
                continue
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

    Registration and recipe authority are separate.  Every intent that compiles
    is registered so the planner can name it, but only an intent with an active
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
            compiled = by_id.get(intent_id)
            if compiled is None:
                # Excluded by `compile_matcher()` with a diagnostic.  Skipping
                # it here is what keeps an invalid artifact out of the
                # model-visible registry and away from recipe authority.
                continue
            specs.append(
                IntentSpec(
                    intent_id=intent_id,
                    phrases=compiled.exact_phrases,
                    recipe_path=_recipe_path(pack, intent_id),
                    canonical_target=compiled.canonical_target,
                )
            )
    return tuple(specs)


# --------------------------------------------------------------------------
# Observation plans
#
# A recipe declares every control its action, its verification, and its
# wrong-action context need.  Compiling that declaration into a plan is what
# lets one bounded worker tick observe the whole union with no
# workflow-specific Python: the plan says which traversals to run and which
# selectors read from each, and the worker just executes it.
# --------------------------------------------------------------------------

PROVIDER_EXACT = "provider_exact"
BOUNDED_DESCENDANTS = "bounded_descendants"

EXACTLY_ONE = "exactly_one"
AT_LEAST_ONE = "at_least_one"

STRIP_LEADING_PRIVATE_USE = "strip_leading_private_use"


class RecipeCompileError(ValueError):
    """A verified recipe could not be compiled into an observation plan."""


@dataclass(frozen=True)
class CompiledSelector:
    selector_id: str
    strategy: str
    control_type: str
    names: tuple[str, ...]
    normalise: str
    cardinality: str
    result_limit: int

    @property
    def query_key(self) -> tuple[str, ...]:
        """What makes two provider queries identical.

        Grouping is by the *full* query.  A provider call performs no
        traversal, so two selectors that differ in any queried field are two
        different calls -- unlike a bounded walk, where the traversal is the
        expensive part and is shared by control type.
        """
        return (self.strategy, self.control_type, self.normalise) + self.names


@dataclass(frozen=True)
class BoundedTraversal:
    """One walk of a control type, shared by every selector over it."""

    control_type: str
    selector_ids: tuple[str, ...]


@dataclass(frozen=True)
class ProviderQuery:
    """One provider call, shared by selectors whose full query is identical."""

    control_type: str
    name: str
    selector_ids: tuple[str, ...]


@dataclass(frozen=True)
class ObservationPlan:
    selectors: Mapping[str, CompiledSelector]
    traversals: tuple[BoundedTraversal, ...]
    queries: tuple[ProviderQuery, ...]

    @property
    def selector_ids(self) -> tuple[str, ...]:
        return tuple(self.selectors)


@dataclass(frozen=True)
class CompiledVerification:
    kind: str
    selector_id: str | None
    args: Mapping[str, Any]
    timeout_s: float


@dataclass(frozen=True)
class CompiledStep:
    user_action: str
    target_selector: str | None
    instruction_text: str
    verification: CompiledVerification
    risk: str


@dataclass(frozen=True)
class CompiledRecipe:
    intent_id: str
    step_key_namespace: str
    steps: tuple[CompiledStep, ...]
    context_selectors: tuple[str, ...]
    plan: ObservationPlan


def _compile_selector(selector_id: str, value: Mapping[str, Any]) -> CompiledSelector:
    return CompiledSelector(
        selector_id=selector_id,
        strategy=value["strategy"],
        control_type=value["control_type"],
        names=tuple(value["names"]),
        normalise=value["normalise"],
        cardinality=value["cardinality"],
        result_limit=value["result_limit"],
    )


def _reject_positional_ids(recipe_value: Mapping[str, Any]) -> None:
    """No compiled recipe may name a positional AutomationId.

    `list_id_<number>_<number>` encodes a list index, not a control, and is the
    only non-empty id VS Code exposes.  `promote()` and `ObservationStore`
    reject it independently at runtime; rejecting it here as well means a
    recipe carrying one never reaches either -- three boundaries, none relying
    on another having caught it.
    """
    from ghostcursor.reasoning.schema import is_positional_automation_id

    for index, step in enumerate(recipe_value["steps"]):
        wanted = step["verification_rule"]["args"].get("automation_id")
        if is_positional_automation_id(wanted):
            raise RecipeCompileError(
                f"step {index} verifies against positional AutomationId {wanted!r}"
            )


def compile_observation_plan(recipe_value: Mapping[str, Any]) -> ObservationPlan:
    """Group a recipe's selectors into the traversals and queries one tick runs.

    Grouping is strategy-specific because the two strategies cost different
    things.  A bounded walk pays for the traversal, so one walk per unique
    control type is shared by every selector of that type.  A provider call
    performs no traversal at all, so control-type grouping would be meaningless
    for it and queries collapse only when the entire query is identical.

    Cardinality is *not* applied here.  It is evaluated per selector against
    that selector's own results at observation time, because a shared traversal
    produces candidates for several selectors and only each selector knows how
    many of them it is allowed to claim.
    """
    selectors = {
        selector_id: _compile_selector(selector_id, value)
        for selector_id, value in recipe_value["selectors"].items()
    }

    traversals: dict[str, list[str]] = {}
    queries: dict[tuple[str, ...], list[str]] = {}
    for selector in selectors.values():
        if selector.strategy == BOUNDED_DESCENDANTS:
            traversals.setdefault(selector.control_type, []).append(selector.selector_id)
        elif selector.strategy == PROVIDER_EXACT:
            queries.setdefault(selector.query_key, []).append(selector.selector_id)
        else:  # pragma: no cover - the schema admits no third strategy
            raise RecipeCompileError(f"unknown strategy {selector.strategy!r}")

    return ObservationPlan(
        selectors=MappingProxyType(selectors),
        traversals=tuple(
            BoundedTraversal(control_type, tuple(ids))
            for control_type, ids in traversals.items()
        ),
        queries=tuple(
            # A provider selector carries exactly one name, enforced by the
            # schema, so the query has a single name to send.
            ProviderQuery(selectors[ids[0]].control_type, selectors[ids[0]].names[0], tuple(ids))
            for ids in queries.values()
        ),
    )


def compile_recipe(recipe_value: Mapping[str, Any]) -> CompiledRecipe:
    """Compile one verified recipe artifact into its executable form."""
    _reject_positional_ids(recipe_value)

    steps = []
    for step in recipe_value["steps"]:
        rule = step["verification_rule"]
        steps.append(
            CompiledStep(
                user_action=step["user_action"],
                target_selector=step["target_selector"],
                instruction_text=step["instruction_text"],
                verification=CompiledVerification(
                    kind=rule["kind"],
                    selector_id=rule.get("selector"),
                    args=MappingProxyType(dict(rule["args"])),
                    timeout_s=float(rule["timeout_s"]),
                ),
                risk=step["risk"],
            )
        )

    return CompiledRecipe(
        intent_id=recipe_value["intent_id"],
        step_key_namespace=recipe_value["step_key_namespace"],
        steps=tuple(steps),
        context_selectors=tuple(recipe_value["context_selectors"]),
        plan=compile_observation_plan(recipe_value),
    )


# ---------------------------------------------------------------------------
# Goal-derived title verification (Design section 7)
# ---------------------------------------------------------------------------


def normalise_title_text(value: str) -> str:
    """Casefold and collapse whitespace, keeping punctuation.

    The one normalisation both the title check and the derived reference use.
    Two definitions would let a reference be derived under one rule and matched
    under another.
    """
    return " ".join(value.casefold().strip().split())


@dataclass(frozen=True)
class GoalReferenceSpec:
    """The compiled form of a recipe's `goal_reference` declaration.

    Every field is a literal the recipe declared; none is a pattern the recipe
    wrote. The compiler escapes each literal before matching, so a recipe can
    say which words to strip but can never supply a regular expression -- the
    extension point the design refuses to open.
    """

    strip_leading_token: str
    alias_members: tuple[str, ...]
    nonspecific_templates: tuple[str, ...]
    trailing_preposition: str
    basename_separators: tuple[str, ...]
    minimum_length: int


def _alias_alternation(members: Iterable[str]) -> str:
    """A regex alternation over escaped alias members, whitespace-flexible.

    `vs code` must also match `vs  code`, because goals are typed by people.
    Escaping first and only then relaxing the spaces is what keeps this a
    literal comparison: nothing the recipe wrote survives as syntax.
    """
    parts = []
    for member in members:
        words = member.split()
        if not words:
            continue
        parts.append(r"\s+".join(re.escape(word) for word in words))
    # No ordering rule here on purpose. Every pattern this alternation appears
    # in is anchored, so a shorter member that matches first still forces the
    # regex to backtrack into the longer one when the anchor fails. An
    # ordering that changes no outcome would read as a safety measure while
    # enforcing nothing (D031).
    return "|".join(parts)


def compile_goal_reference(
    value: Mapping[str, Any], aliases: Mapping[str, Any]
) -> GoalReferenceSpec:
    """Bind a verified `goal_reference` to its pack alias group."""
    alias = value["alias"]
    members = aliases.get(alias)
    if members is None:
        raise UnknownAliasError(f"goal_reference names unknown alias {alias!r}")
    return GoalReferenceSpec(
        strip_leading_token=value["strip_leading_token"],
        alias_members=tuple(members),
        nonspecific_templates=tuple(value["nonspecific_templates"]),
        trailing_preposition=value["strip_trailing_alias_clause"]["preposition"],
        basename_separators=tuple(value["basename_separators"]),
        minimum_length=int(value["minimum_length"]),
    )


def derive_goal_reference(spec: GoalReferenceSpec, goal: str) -> str:
    """Reduce a goal to the reference a completed title must contain.

    The six steps of Design section 7, in order. Each transformation applies to
    the *original* remainder rather than to a normalised copy, so separator
    splitting still sees the goal's real punctuation; only the final value is
    normalised.
    """
    alternation = _alias_alternation(spec.alias_members)
    text = goal.strip()

    # 1-2. a leading `open`, on a word boundary so `opener` survives.
    text = re.sub(
        rf"^{re.escape(spec.strip_leading_token)}\b", "", text, flags=re.IGNORECASE
    ).strip()

    # 3. a WHOLE-remainder match of a nonspecific template. Whole-remainder is
    #    the point: `a folder in vs code` names nothing, but `notes a folder in
    #    vs code` names `notes` and must keep it.
    if alternation:
        for template in spec.nonspecific_templates:
            words = template.split()
            pattern = r"\s+".join(
                f"(?:{alternation})" if word == "{alias}" else re.escape(word)
                for word in words
            )
            text = re.sub(rf"^{pattern}\s*$", "", text, flags=re.IGNORECASE).strip()

        # 4. a TRAILING alias clause: `... in vs code`.
        text = re.sub(
            rf"\s+{re.escape(spec.trailing_preposition)}\s+(?:{alternation})\s*$",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

    # 5. bare separator containment, deliberately NOT D072's path predicate.
    #    The two answer different questions -- D072 asks whether a goal is
    #    about a path, this asks whether a reference has a final segment -- and
    #    using the stricter one here would silently change what gets verified
    #    for a goal that grounds through its `folder` token instead.
    if any(separator in text for separator in spec.basename_separators):
        pattern = "[" + "".join(re.escape(s) for s in spec.basename_separators) + "]+"
        segments = [segment for segment in re.split(pattern, text) if segment]
        text = segments[-1] if segments else ""

    # 6.
    return normalise_title_text(text)


def reference_is_specific(spec: GoalReferenceSpec, reference: str) -> bool:
    """Whether condition 3 applies at all.

    A shorter reference is not a weaker match, it is no evidence: `.` appears
    in ordinary window titles and would satisfy the containment check without
    the title having anything to do with the goal.
    """
    return len(reference) >= spec.minimum_length
