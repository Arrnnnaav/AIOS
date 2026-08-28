"""Differential and contract tests for the compiled D072 matcher.

Three separate things are proved here, and they are deliberately not merged:

1. The **path predicate** agrees with the contract-defining table in
   `docs/evidence/d072-compatibility-corpus.md`.  The table is parsed, not
   retyped, so the document and the code cannot drift apart.
2. The **compiled matcher** reproduces the frozen v1 reference on every corpus row that
   D072 does not allowlist, and reproduces D072's stated new outcome on every
   row it does.
3. The **evidence document** is a faithful projection of the canonical corpus
   fixture, checked by running the renderer in `--check` mode.

The v1 column is checked against the frozen pre-cutover semantics below. The
production matcher is deliberately not used to manufacture that baseline.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from ghostcursor.packs import compile as packs_compile
from ghostcursor.packs.activation import DiagnosticCode, IntentAvailability
from ghostcursor.packs.compile import (
    EXACT_CONFIDENCE,
    HEURISTIC_CONFIDENCE,
    MATCH_CONFIDENCES,
    CompiledIntent,
    CompiledMatcher,
    LiteralTerm,
    PathTerm,
    UnknownAliasError,
    compile_matcher,
    compile_planner,
    is_path_reference,
    normalise_goal,
    path_tokens,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = REPO_ROOT / "tests" / "data" / "d072_compatibility_v1.json"
EVIDENCE_PATH = REPO_ROOT / "docs" / "evidence" / "d072-compatibility-corpus.md"
RENDERER = REPO_ROOT / "tools" / "render_d072_compatibility.py"

# The reviewed shape of the corpus.  A change to any of these numbers is a
# change to what was reviewed, and has to be re-reviewed rather than re-run.
EXPECTED_ROWS = 86
EXPECTED_DIVERGENCES = 14
EXPECTED_CLASS_SIZES = {"forward-slash": 5, "backslash-prose": 3, "ambiguity": 6}


@pytest.fixture(scope="module")
def corpus() -> dict:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# The reference pack: the three intents D072 is specified against
# --------------------------------------------------------------------------

VSCODE_ALIASES = {"vscode_names": ["vs code", "vscode", "visual studio code"]}


def _intent(intent_id: str, rules: list[dict], target: str | None = None) -> dict:
    return {
        "schema_version": 2,
        "intent_id": intent_id,
        "canonical_target": target,
        "rules": rules,
    }


EXPORT_DATA = _intent(
    "EXPORT_DATA",
    [
        {
            "tier": "exact",
            "phrases": [
                "export this table as csv",
                "export as csv",
                "export data",
                "export the current file",
            ],
        },
        {
            "tier": "heuristic",
            "all_of": [
                {
                    "any_of": [
                        {"token": "csv"},
                        {"token": "spreadsheet"},
                        {"token": "table"},
                    ]
                },
                {
                    "any_of": [
                        {"token": "export"},
                        {"token": "save"},
                        {"token": "download"},
                    ]
                },
            ],
        },
    ],
)

OPEN_FOLDER = _intent(
    "OPEN_FOLDER",
    [
        {
            "tier": "exact",
            "phrases": [
                "open a folder in vs code",
                "open a folder in vscode",
                "open a folder in visual studio code",
            ],
        },
        {
            "tier": "heuristic",
            "all_of": [
                {"any_of": [{"token": "open"}]},
                {"any_of": [{"alias": "vscode_names"}]},
                {"any_of": [{"token": "folder"}, {"path": True}]},
            ],
        },
    ],
    target="Open Folder",
)

OPEN_TERMINAL = _intent(
    "OPEN_TERMINAL",
    [
        {
            "tier": "exact",
            "phrases": [
                "open the integrated terminal in vs code",
                "open the integrated terminal in vscode",
                "open a terminal in vs code",
                "open a terminal in vscode",
            ],
        },
        {
            "tier": "heuristic",
            "all_of": [
                {"any_of": [{"token": "open"}, {"token": "show"}]},
                {"any_of": [{"token": "terminal"}]},
                {"any_of": [{"alias": "vscode_names"}]},
            ],
        },
    ],
    target="Toggle Panel (Ctrl+J)",
)


def _compiled(intent_value: dict, aliases: dict | None = None) -> CompiledIntent:
    phrases, heuristic = packs_compile._compile_rules(
        intent_value, VSCODE_ALIASES if aliases is None else aliases
    )
    return CompiledIntent(
        intent_id=intent_value["intent_id"],
        pack_id="vscode",
        canonical_target=intent_value["canonical_target"],
        availability=IntentAvailability.ACTIVE,
        exact_phrases=phrases,
        heuristic_rules=heuristic,
    )


def _v1_reference(goal: str) -> tuple[str | None, float, str]:
    """Independent transcription of the pre-cutover planner semantics.

    This is a frozen test oracle, not a production helper. Keeping it here is
    intentional: comparing the v2 matcher with ``deterministic_intent`` after
    cutover would compare the implementation with itself and make D072's
    differential gate vacuous.
    """
    normalized = " ".join(goal.lower().split())
    exact = {
        phrase: "EXPORT_DATA"
        for phrase in EXPORT_DATA["rules"][0]["phrases"]
    }
    exact.update({phrase: "OPEN_FOLDER" for phrase in OPEN_FOLDER["rules"][0]["phrases"]})
    exact.update({phrase: "OPEN_TERMINAL" for phrase in OPEN_TERMINAL["rules"][0]["phrases"]})
    if normalized in exact:
        return exact[normalized], 0.95, "matched exact phrase"
    if any(word in normalized for word in ("csv", "spreadsheet", "table")) and any(
        word in normalized for word in ("export", "save", "download")
    ):
        return "EXPORT_DATA", 0.85, "matched a known export synonym"
    if (
        "open" in normalized
        and any(alias in normalized for alias in VSCODE_ALIASES["vscode_names"])
        and ("folder" in normalized or "\\" in normalized or "/" in normalized)
    ):
        return "OPEN_FOLDER", 0.85, "matched the VS Code open-folder intent"
    if (
        any(word in normalized for word in ("open", "show"))
        and "terminal" in normalized
        and any(alias in normalized for alias in VSCODE_ALIASES["vscode_names"])
    ):
        return "OPEN_TERMINAL", 0.85, "matched the VS Code integrated-terminal intent"
    return None, 0.0, "no trusted intent matched"
@pytest.fixture(scope="module")
def matcher() -> CompiledMatcher:
    """The v2 matcher fixture, alongside the frozen v1 reference.

    Order is recorded rather than relied upon: a correct D072 matcher is
    order-independent, and `test_matcher_is_order_independent` proves this one
    is.  Keeping the same order here means a differential failure is a real
    disagreement, not an artefact of how the fixture happened to be built.
    """
    return CompiledMatcher(
        tuple(_compiled(value) for value in (EXPORT_DATA, OPEN_FOLDER, OPEN_TERMINAL))
    )


# --------------------------------------------------------------------------
# 1. The path predicate
# --------------------------------------------------------------------------


def _contract_table() -> list[tuple[str, bool]]:
    """Parse the path-predicate table out of the evidence document.

    Reading the table instead of restating it is the point: a hand-copied
    fixture would let the specification and the implementation disagree while
    both looked green.
    """
    text = EVIDENCE_PATH.read_text(encoding="utf-8")
    section = text.split("## Path predicate", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        match = re.match(r"^\| `(.+)` \| (yes|no) \| ", line)
        if match:
            rows.append((match.group(1), match.group(2) == "yes"))
    return rows


def test_path_predicate_matches_the_documented_contract() -> None:
    rows = _contract_table()
    assert len(rows) == 14, "the contract-defining table lost or gained a row"
    mismatches = [
        (text, expected)
        for text, expected in rows
        if bool(path_tokens(text)) != expected
    ]
    assert mismatches == []


def test_a_lone_backslash_between_words_is_not_a_path() -> None:
    # The case that makes the definition testable at all: the separator has to
    # join text on both sides, not merely appear somewhere in the goal.
    assert is_path_reference("foo\\bar")
    assert not is_path_reference("\\")
    assert path_tokens("open foo \\ bar in vs code") == ()


def test_a_trailing_separator_is_not_a_path_reference() -> None:
    assert not is_path_reference("foo\\")
    assert not is_path_reference("c:\\")


def test_normalisation_collapses_case_and_whitespace() -> None:
    assert (
        normalise_goal("  Open   A Folder\tin VS Code ") == "open a folder in vs code"
    )


# --------------------------------------------------------------------------
# 2. The compiled matcher
# --------------------------------------------------------------------------


def test_exact_tier_outranks_a_heuristic_match_on_another_intent(
    matcher: CompiledMatcher,
) -> None:
    # `open a folder in vs code` is EXPORT_DATA-free, so build a goal that is an
    # exact phrase for one intent while heuristically matching another.
    colliding = CompiledMatcher(
        (
            _compiled(OPEN_FOLDER),
            _compiled(
                _intent(
                    "OPEN_SETTINGS",
                    [{"tier": "exact", "phrases": ["open a folder in vs code"]}],
                )
            ),
        )
    )
    # Both intents claim the phrase, so the exact tier is ambiguous and the
    # heuristic tier is never consulted -- tier order is what makes this fail
    # closed instead of silently returning OPEN_FOLDER at 0.85.
    outcome = colliding.classify("open a folder in vs code")
    assert (outcome.kind, outcome.intent_id, outcome.confidence) == (
        "ambiguous",
        None,
        0.0,
    )


def test_an_exact_phrase_wins_over_the_same_intents_heuristic_rule(
    matcher: CompiledMatcher,
) -> None:
    outcome = matcher.classify("Open a folder in VS Code")
    assert outcome.intent_id == "OPEN_FOLDER"
    assert outcome.confidence == EXACT_CONFIDENCE


def test_two_rules_on_one_intent_are_one_match_not_an_ambiguity() -> None:
    """A goal satisfying *both* of an intent's rules still grounds that intent.

    Rule deduplication is structural: `matches_heuristic` answers once per
    intent, so the ambiguity check never sees the same intent twice.  The goal
    below satisfies each rule on its own, which is what makes the assertion
    about deduplication rather than about one rule happening to fire.
    """
    doubled_value = _intent(
        "OPEN_FOLDER",
        [
            {"tier": "heuristic", "all_of": [{"any_of": [{"token": "open"}]}]},
            {"tier": "heuristic", "all_of": [{"any_of": [{"token": "folder"}]}]},
        ],
    )
    compiled = _compiled(doubled_value)
    assert len(compiled.heuristic_rules) == 2
    assert compiled.matches_heuristic("open", ("open",))
    assert compiled.matches_heuristic("folder", ("folder",))

    doubled = CompiledMatcher((compiled,))
    outcome = doubled.classify("open folder")
    assert (outcome.intent_id, outcome.confidence, outcome.kind) == (
        "OPEN_FOLDER",
        HEURISTIC_CONFIDENCE,
        "matched",
    )


def test_a_repeated_intent_id_reaches_the_ambiguity_check() -> None:
    """A catalog cannot produce this, and the matcher must not paper over it.

    Intent ids are unique across a verified catalog, so two compiled intents
    sharing an id means something upstream built the matcher wrong.  Silently
    deduplicating would hide that and ground a workflow anyway; failing closed
    surfaces it.
    """
    repeated = CompiledMatcher((_compiled(OPEN_FOLDER), _compiled(OPEN_FOLDER)))
    outcome = repeated.classify("open a folder in vs code")
    assert outcome.kind == "ambiguous"
    assert outcome.intent_id is None


def test_two_intents_in_one_tier_fail_closed(matcher: CompiledMatcher) -> None:
    outcome = matcher.classify("open folder in vs code and export table")
    assert outcome.kind == "ambiguous"
    assert outcome.intent_id is None
    assert outcome.confidence == 0.0
    assert "EXPORT_DATA" in outcome.reason and "OPEN_FOLDER" in outcome.reason


def test_matcher_is_order_independent(matcher: CompiledMatcher) -> None:
    """Reversing catalog order changes no outcome.

    An order-sensitive matcher would resolve a cross-intent collision by source
    order, which is precisely the v1 behaviour D072 replaces.
    """
    reversed_matcher = CompiledMatcher(tuple(reversed(matcher.intents)))
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    for row in corpus["rows"]:
        first = matcher.classify(row["goal"])
        second = reversed_matcher.classify(row["goal"])
        assert (first.intent_id, first.confidence, first.kind) == (
            second.intent_id,
            second.confidence,
            second.kind,
        ), row["goal"]


def test_an_undeclared_alias_is_a_hard_failure_not_a_skipped_term() -> None:
    with pytest.raises(UnknownAliasError):
        packs_compile._compile_rules(OPEN_FOLDER, {})


def test_a_clause_whose_alias_is_missing_never_becomes_vacuously_true() -> None:
    # Guards the failure direction: if the term were dropped, the clause would
    # be empty and `all(...)` over no terms is True, which would widen the rule
    # to every goal containing `open`.
    catalog = _catalog_with(OPEN_FOLDER, aliases={})
    compiled = compile_matcher(catalog)
    assert compiled.diagnostics
    assert compiled.intents == ()
    assert compiled.classify("open anything at all").intent_id is None


def test_an_intent_that_fails_to_compile_leaves_the_registry_too() -> None:
    """Exclusion covers matching *and* the model-visible registry.

    An intent that only lost its rules would still be a registered id carrying
    a recipe path.  A registered id is an allowlist boundary the model can
    name (D058), and a recipe path is execution authority -- so a cross-file
    invalid artifact would keep a seat at execution while looking harmless.
    """
    catalog = _catalog_with(OPEN_FOLDER, aliases={})

    matcher = compile_matcher(catalog)
    assert [d.code for d in matcher.diagnostics] == [DiagnosticCode.INTENT_INVALID]
    assert matcher.diagnostics[0].intent_id == "OPEN_FOLDER"

    specs = compile_planner(catalog)
    assert specs == (), "an invalid intent must not reach the planner registry"


def test_a_valid_intent_survives_a_sibling_that_fails_to_compile() -> None:
    """Exclusion is intent-scoped, not pack-scoped.

    OPEN_TERMINAL also references the alias, so the fixture gives only
    EXPORT_DATA rules that can compile without one -- and it must still
    register and still match.
    """
    catalog = _catalog_with(EXPORT_DATA, OPEN_FOLDER, aliases={})
    specs = compile_planner(catalog)
    assert [spec.intent_id for spec in specs] == ["EXPORT_DATA"]

    matcher = compile_matcher(catalog)
    assert matcher.classify("export as csv").intent_id == "EXPORT_DATA"
    assert matcher.classify("open a folder in vs code").intent_id is None


def test_confidence_comes_from_the_tier_and_only_from_the_tier(
    matcher: CompiledMatcher, corpus: dict
) -> None:
    seen = {matcher.classify(row["goal"]).confidence for row in corpus["rows"]}
    assert seen <= set(MATCH_CONFIDENCES)
    assert EXACT_CONFIDENCE == 0.95 and HEURISTIC_CONFIDENCE == 0.85


# --------------------------------------------------------------------------
# The differential gate
# --------------------------------------------------------------------------


def test_every_corpus_row_matches_its_recorded_v2_outcome(
    matcher: CompiledMatcher, corpus: dict
) -> None:
    failures = []
    for row in corpus["rows"]:
        outcome = matcher.classify(row["goal"])
        actual = (outcome.intent_id, outcome.confidence, outcome.kind)
        expected = (row["expected_v2"], row["v2_confidence"], row["v2_kind"])
        if actual != expected:
            failures.append((row["goal"], expected, actual))
    assert failures == []


def test_every_corpus_row_matches_its_recorded_v1_outcome(corpus: dict) -> None:
    """The recorded v1 column is checked against the frozen v1 oracle.

    Without this, a divergence row could be "explained" by a v1 column that was
    never true, and the gate below would be comparing the new matcher against
    fiction.
    """
    failures = []
    for row in corpus["rows"]:
        intent_id, confidence, _reason = _v1_reference(row["goal"])
        # The pre-cutover planner had no ambiguity concept -- it resolved collisions by
        # source order -- so its kind is fully determined by whether it
        # grounded.  Deriving it here rather than trusting the column is what
        # makes the column checked instead of merely rendered.
        kind = "matched" if intent_id is not None else "no_match"
        actual = (intent_id, confidence, kind)
        expected = (row["expected_v1"], row["v1_confidence"], row["v1_kind"])
        if actual != expected:
            failures.append((row["goal"], expected, actual))
    assert failures == []


def test_no_corpus_row_claims_v1_was_ambiguous(corpus: dict) -> None:
    """`ambiguous` is a v2-only outcome.

    v1 returns whichever rule its source order reaches first, so a v1 column
    reading `ambiguous` would describe behaviour that cannot occur -- and would
    quietly reclassify a real divergence as agreement.
    """
    assert {row["v1_kind"] for row in corpus["rows"]} == {"matched", "no_match"}


def test_no_unlisted_divergence_from_the_production_matcher(
    matcher: CompiledMatcher, corpus: dict
) -> None:
    """The gate: agreement everywhere except the declared allowlist."""
    unlisted = []
    stale = []
    for row in corpus["rows"]:
        v1_intent, v1_confidence, _reason = _v1_reference(row["goal"])
        outcome = matcher.classify(row["goal"])
        diverges = (v1_intent, v1_confidence) != (outcome.intent_id, outcome.confidence)
        if diverges and not row["diverges"]:
            unlisted.append(row["goal"])
        if row["diverges"] and not diverges:
            stale.append(row["goal"])
    assert unlisted == [], "divergences not covered by a D072 allowlist entry"
    assert stale == [], "allowlisted rows that no longer diverge"


def test_every_divergence_lands_in_a_declared_class(corpus: dict) -> None:
    declared = set(corpus["divergence_classes"])
    unclassified = [
        row["goal"]
        for row in corpus["rows"]
        if row["diverges"] and row["divergence_class"] not in declared
    ]
    assert unclassified == []


def test_the_frozen_dataset_rows_are_all_present_and_agree(
    matcher: CompiledMatcher, corpus: dict
) -> None:
    frozen = [
        row for row in corpus["rows"] if row["origin"].startswith("frozen dataset:")
    ]
    assert len(frozen) == 30
    for row in frozen:
        assert not row["diverges"], row["goal"]
        outcome = matcher.classify(row["goal"])
        assert (outcome.intent_id, outcome.confidence) == (
            row["expected_v1"],
            row["v1_confidence"],
        ), row["goal"]


# --------------------------------------------------------------------------
# 3. The canonical fixture and its rendered evidence
# --------------------------------------------------------------------------


def test_the_canonical_corpus_has_the_reviewed_shape(corpus: dict) -> None:
    rows = corpus["rows"]
    assert len(rows) == EXPECTED_ROWS
    assert len({row["goal"] for row in rows}) == EXPECTED_ROWS
    assert sum(1 for row in rows if row["diverges"]) == EXPECTED_DIVERGENCES
    sizes = Counter(row["divergence_class"] for row in rows if row["diverges"])
    assert dict(sizes) == EXPECTED_CLASS_SIZES
    assert set(corpus["divergence_classes"]) == set(EXPECTED_CLASS_SIZES)
    for row in rows:
        assert row["v2_confidence"] in MATCH_CONFIDENCES
        assert row["diverges"] == (row["divergence_class"] is not None)


def test_every_divergence_class_records_its_d072_reason(corpus: dict) -> None:
    for name, definition in corpus["divergence_classes"].items():
        assert definition["d072_reason"].strip(), name
        assert definition["representatives_summary"].strip(), name


def _check_renderer(document: Path | None = None) -> subprocess.CompletedProcess:
    command = [sys.executable, str(RENDERER), "--check"]
    if document is not None:
        command += ["--document", str(document)]
    return subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True)


CR = bytes([13])
LF = bytes([10])
UTF8_BOM = bytes([0xEF, 0xBB, 0xBF])


def test_the_evidence_document_is_a_faithful_render_of_the_corpus() -> None:
    """Run the renderer's `--check` mode rather than comparing two copies.

    The document's generated regions are output, not a second maintained
    source, so the only thing worth asserting is that regenerating produces no
    difference.
    """
    assert _check_renderer().returncode == 0, _check_renderer().stderr


def test_the_evidence_document_is_utf8_lf_without_a_bom() -> None:
    raw = EVIDENCE_PATH.read_bytes()
    assert CR not in raw
    assert not raw.startswith(UTF8_BOM)
    raw.decode("utf-8")


def _corrupt(original: bytes, kind: str) -> bytes:
    if kind == "crlf":
        return original.replace(LF, CR + LF)
    if kind == "bom":
        return UTF8_BOM + original
    if kind == "bare-cr-terminator":
        return original.replace(LF, CR, 1)
    # A stray CR inside a prose line, outside every generated region: the case
    # a CRLF-only normalisation preserves, so rendering reproduces it and the
    # comparison sees no difference.
    anchor = b"Every input D072"
    index = original.index(anchor)
    return (
        original[:index]
        + b"Every"
        + CR
        + b" input D072"
        + original[index + len(anchor) :]
    )


@pytest.mark.parametrize(
    "kind", ["crlf", "bom", "bare-cr-terminator", "bare-cr-in-prose"]
)
def test_check_mode_rejects_every_non_canonical_encoding(
    tmp_path: Path, kind: str
) -> None:
    """`--check` must fail on any byte difference, encoding included.

    Each corruption here reads back as the same *text* under some plausible
    reading -- CRLF and a lone CR are folded by text mode, and a BOM decodes to
    a character that survives rendering untouched -- so a check that compares
    anything but canonical bytes accepts at least one of them.

    The corrupted copy lives in `tmp_path`.  Rewriting the tracked document in
    place would leave it corrupted if the test process were killed, and would
    be observed by anything else reading the repository meanwhile.
    """
    original = EVIDENCE_PATH.read_bytes()
    copy = tmp_path / EVIDENCE_PATH.name

    copy.write_bytes(original)
    assert _check_renderer(copy).returncode == 0, "a verbatim copy must pass"

    corrupted = _corrupt(original, kind)
    assert corrupted != original, kind
    copy.write_bytes(corrupted)
    assert _check_renderer(copy).returncode == 1, f"--check accepted {kind}"


def test_rendering_a_non_canonical_copy_restores_canonical_bytes(
    tmp_path: Path,
) -> None:
    """Normal mode repairs what `--check` rejects, and never in the repository."""
    original = EVIDENCE_PATH.read_bytes()
    copy = tmp_path / EVIDENCE_PATH.name
    copy.write_bytes(UTF8_BOM + original.replace(LF, CR + LF))

    result = subprocess.run(
        [sys.executable, str(RENDERER), "--document", str(copy)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert copy.read_bytes() == original
    assert EVIDENCE_PATH.read_bytes() == original


# --------------------------------------------------------------------------
# Bounded generation
# --------------------------------------------------------------------------


def _representative(term: dict, aliases: dict) -> str:
    if "token" in term:
        return term["token"]
    if "alias" in term:
        return aliases[term["alias"]][0]
    return "c:\\projects\\demo"


def _clause_products(intent_value: dict, aliases: dict) -> list[list[str]]:
    """One representative per clause, crossed over all clauses.

    Bounded by the product of clause sizes -- no randomness and no seed, so the
    generated set is identical on every run and on every machine.
    """
    from itertools import product

    heuristic = [rule for rule in intent_value["rules"] if rule["tier"] == "heuristic"]
    generated: list[list[str]] = []
    for rule in heuristic:
        choices = [
            [_representative(term, aliases) for term in clause["any_of"]]
            for clause in rule["all_of"]
        ]
        generated.extend(list(combination) for combination in product(*choices))
    return generated


@pytest.mark.parametrize(
    "intent_value",
    [EXPORT_DATA, OPEN_FOLDER, OPEN_TERMINAL],
    ids=lambda v: v["intent_id"],
)
def test_generated_clause_products_reach_their_own_intent(intent_value: dict) -> None:
    """Every clause product grounds the intent that declared it.

    This is a completeness check on the rule, not on the corpus: if a clause
    lists a term that no goal can satisfy, the product built from it fails here
    rather than silently narrowing the rule.
    """
    single = CompiledMatcher((_compiled(intent_value),))
    for combination in _clause_products(intent_value, VSCODE_ALIASES):
        goal = " ".join(combination)
        outcome = single.classify(goal)
        assert outcome.intent_id == intent_value["intent_id"], goal
        assert outcome.confidence == HEURISTIC_CONFIDENCE, goal


@pytest.mark.parametrize(
    "intent_value",
    [EXPORT_DATA, OPEN_FOLDER, OPEN_TERMINAL],
    ids=lambda v: v["intent_id"],
)
def test_every_declared_exact_phrase_grounds_verbatim(intent_value: dict) -> None:
    single = CompiledMatcher((_compiled(intent_value),))
    phrases = [
        phrase
        for rule in intent_value["rules"]
        if rule["tier"] == "exact"
        for phrase in rule["phrases"]
    ]
    assert phrases
    for phrase in phrases:
        outcome = single.classify(phrase)
        assert (outcome.intent_id, outcome.confidence) == (
            intent_value["intent_id"],
            EXACT_CONFIDENCE,
        ), phrase


def test_generation_is_deterministic() -> None:
    first = _clause_products(EXPORT_DATA, VSCODE_ALIASES)
    second = _clause_products(EXPORT_DATA, VSCODE_ALIASES)
    assert first == second
    assert len(first) == 9  # 3 x 3, the declared clause product


# --------------------------------------------------------------------------
# compile_planner over a verified catalog
# --------------------------------------------------------------------------


class _StubIntent:
    def __init__(
        self, value: dict, availability: IntentAvailability, recipe: str | None
    ):
        self.intent_value = value
        self.availability = availability
        self.active_adoption = _StubAdoption(recipe) if recipe else None


class _StubAdoption:
    def __init__(self, recipe: str):
        self.recipe = type("Ref", (), {"path": recipe})()


class _StubPack:
    def __init__(self, pack_id: str, directory: Path, aliases: dict, intents: dict):
        self.pack_id = pack_id
        self.directory = directory
        self.pack_value = {"aliases": aliases}
        self.intents = intents


class _StubCatalog:
    def __init__(self, packs: dict, root_valid: bool = True):
        self.root_valid = root_valid
        self.packs = packs
        self.diagnostics = ()


def _catalog_with(*intent_values: dict, aliases: dict | None = None) -> _StubCatalog:
    intents = {
        value["intent_id"]: _StubIntent(
            value,
            IntentAvailability.ACTIVE,
            f"recipes/{value['intent_id'].lower()}.json",
        )
        for value in intent_values
    }
    pack = _StubPack(
        "vscode",
        Path("packs/vscode"),
        VSCODE_ALIASES if aliases is None else aliases,
        intents,
    )
    return _StubCatalog({"vscode": pack})


def test_compile_planner_carries_phrases_and_recipe_authority() -> None:
    specs = compile_planner(_catalog_with(OPEN_FOLDER, OPEN_TERMINAL))
    by_id = {spec.intent_id: spec for spec in specs}
    assert by_id["OPEN_FOLDER"].phrases == (
        "open a folder in vs code",
        "open a folder in vscode",
        "open a folder in visual studio code",
    )
    assert by_id["OPEN_FOLDER"].canonical_target == "Open Folder"
    assert by_id["OPEN_FOLDER"].recipe_path == Path(
        "packs/vscode/recipes/open_folder.json"
    )


def test_planner_only_intents_register_without_rules_or_recipe_authority() -> None:
    """A common-pack intent is nameable but not executable and not matchable.

    `CREATE_DOCUMENT` and `OPEN_SETTINGS` stay model-visible registered ids.
    Giving them deterministic rules would change deterministic-null results,
    and giving them a recipe path would make them executable -- neither is what
    `recipe: null` means.
    """
    create = _intent("CREATE_DOCUMENT", [])
    settings = _intent("OPEN_SETTINGS", [])
    intents = {
        "CREATE_DOCUMENT": _StubIntent(
            create, IntentAvailability.KNOWN_INTENT_RECIPE_UNAVAILABLE, None
        ),
        "OPEN_SETTINGS": _StubIntent(
            settings, IntentAvailability.KNOWN_INTENT_RECIPE_UNAVAILABLE, None
        ),
    }
    catalog = _StubCatalog(
        {"common": _StubPack("common", Path("packs/common"), {}, intents)}
    )

    specs = compile_planner(catalog)
    assert {spec.intent_id for spec in specs} == {"CREATE_DOCUMENT", "OPEN_SETTINGS"}
    for spec in specs:
        assert spec.phrases == ()
        assert spec.recipe_path is None

    compiled = compile_matcher(catalog)
    assert compiled.classify("create a document").intent_id is None
    assert compiled.classify("open settings").intent_id is None


def test_an_invalid_root_compiles_to_nothing() -> None:
    catalog = _StubCatalog({}, root_valid=False)
    assert compile_planner(catalog) == ()
    assert compile_matcher(catalog).intents == ()


def test_compiled_terms_carry_no_executable_behaviour() -> None:
    """Terms are data, not callables an artifact could supply.

    D072 admits three primitives and no plugin form; this pins that a compiled
    term is one of exactly two frozen shapes.
    """
    _phrases, heuristic = packs_compile._compile_rules(OPEN_FOLDER, VSCODE_ALIASES)
    terms = [term for rule in heuristic for clause in rule for term in clause]
    assert terms
    assert all(isinstance(term, (LiteralTerm, PathTerm)) for term in terms)
