"""The three migrated candidates, checked against the v1 recipes they replace.

Migration changes REPRESENTATION. Everything else -- which controls a workflow
selects, what its title check accepts, how its steps identify themselves for
learned observations, what provenance it carries, what its wrong-action surface
can see, whether OCR may run, and what each verification means -- has to come
out the same. So the v1 recipes are read here and compared field by field,
rather than a reviewed snapshot being restated by hand: a hand-copied
expectation lets the two drift while both look green.

The candidates are quarantined. They live outside `ghostcursor/packs/`, nothing
in production reads their directory, and the tests at the end assert that
rather than trusting the layout.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Mapping

import pytest

from ghostcursor.devtools.candidate_acceptance import load_candidate
from ghostcursor.packs.compile import compile_recipe
from ghostcursor.reasoning.identity import step_key
from ghostcursor.reasoning.schema import Recipe

REPO_ROOT = Path(__file__).resolve().parent.parent
CANDIDATE_ROOT = (
    REPO_ROOT / "docs" / "superpowers" / "candidates" / "declarative-workflow-compiler"
)
V1_RECIPES = REPO_ROOT / "ghostcursor" / "packs" / "recipes"
V1_MANIFESTS = REPO_ROOT / "ghostcursor" / "packs" / "manifests"
BUILDER = REPO_ROOT / "tools" / "build_migration_candidates.py"

#: pack id -> (intent id, candidate artifact stem, v1 recipe path)
MIGRATIONS = {
    "EXPORT_DATA": ("synthetic", "open_export", "synthetic/synthetic_export.json"),
    "OPEN_FOLDER": ("vscode", "open_folder", "vscode/open_folder.json"),
    "OPEN_TERMINAL": ("vscode", "open_terminal", "vscode/open_terminal.json"),
}

CR = bytes([13])
UTF8_BOM = bytes([0xEF, 0xBB, 0xBF])


@pytest.fixture(scope="module")
def digests() -> dict:
    return json.loads((CANDIDATE_ROOT / "digests.json").read_text(encoding="utf-8"))[
        "artifacts"
    ]


def _artifact(kind: str, pack_id: str, stem: str, digests: dict) -> Path:
    prefix = f"{pack_id}/{kind}/{stem}."
    matches = [path for path in digests if path.startswith(prefix)]
    assert len(matches) == 1, f"{prefix} names {len(matches)} artifacts"
    return CANDIDATE_ROOT / matches[0]


def _graph(intent_id: str, digests: dict):
    pack_id, stem, _v1 = MIGRATIONS[intent_id]
    pack = _artifact("pack", pack_id, pack_id, digests)
    intent = _artifact("intents", pack_id, stem, digests)
    recipe = _artifact("recipes", pack_id, stem, digests)
    relative = lambda path: path.relative_to(CANDIDATE_ROOT).as_posix()
    return load_candidate(
        CANDIDATE_ROOT,
        pack_path=pack,
        pack_sha256=digests[relative(pack)],
        intent_path=intent,
        intent_sha256=digests[relative(intent)],
        recipe_path=recipe,
        recipe_sha256=digests[relative(recipe)],
        project_root=REPO_ROOT,
    )


def _plain(value):
    """Undo the trust boundary's deep freeze for comparison.

    Loaded artifacts come back as mappingproxies and tuples, which never
    compare equal to the plain dicts and lists a v1 recipe parses into. The
    difference is representation -- exactly the thing this file exists to look
    past -- so it is undone here rather than asserted around.
    """
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _v1(intent_id: str) -> dict:
    _pack, _stem, path = MIGRATIONS[intent_id]
    return json.loads((V1_RECIPES / path).read_text(encoding="utf-8"))


ALL_INTENTS = sorted(MIGRATIONS)


# ---------------------------------------------------------------------------
# Bytes and digests
# ---------------------------------------------------------------------------


def test_the_committed_candidates_are_exactly_what_the_builder_produces() -> None:
    """Regenerating must change nothing.

    The artifacts are output, not a second maintained source, so the only
    thing worth asserting is that the generator and the committed bytes agree.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(BUILDER), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_every_artifact_is_utf8_lf_without_a_bom(digests: dict) -> None:
    for relative in digests:
        raw = (CANDIDATE_ROOT / relative).read_bytes()
        assert CR not in raw, relative
        assert not raw.startswith(UTF8_BOM), relative
        raw.decode("utf-8")


def test_the_recorded_digest_is_of_the_exact_committed_bytes(digests: dict) -> None:
    for relative, recorded in digests.items():
        raw = (CANDIDATE_ROOT / relative).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == recorded, relative


def test_the_filename_fragment_is_readability_never_authority(digests: dict) -> None:
    """The fragment agrees with the digest, and nothing parses it to find out.

    A loader that derived the digest from the name would accept any bytes
    someone was willing to rename, so the full digest is recorded separately
    and passed in explicitly.
    """
    for relative, recorded in digests.items():
        fragment = Path(relative).name.split(".")[-2]
        assert recorded.startswith(fragment), relative
        assert len(fragment) < len(recorded)

    source = BUILDER.read_text(encoding="utf-8")
    assert "readability" in source
    loader = (REPO_ROOT / "ghostcursor" / "packs" / "trusted.py").read_text(
        encoding="utf-8"
    )
    assert "path.stem" not in loader, "the loader parses a filename"


@pytest.mark.parametrize("intent_id", ALL_INTENTS)
def test_each_candidate_loads_through_the_trusted_boundary(intent_id, digests) -> None:
    """Strict schema, exact digests, containment, cross-file agreement."""
    graph = _graph(intent_id, digests)
    assert graph.intent.value["intent_id"] == intent_id
    assert graph.recipe.value["intent_id"] == intent_id
    assert graph.compiled.intent_id == intent_id


# ---------------------------------------------------------------------------
# Representation changed; behaviour did not
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("intent_id", ALL_INTENTS)
def test_the_step_key_namespace_is_the_v1_intent_string(intent_id, digests) -> None:
    """The one field that must not be "modernised".

    `step_key()` hashes this with the claimed descriptor, so substituting the
    new intent ID -- the obvious thing to put here -- silently orphans every
    observation the workflow has already learned (D016).
    """
    graph = _graph(intent_id, digests)
    assert graph.recipe.value["step_key_namespace"] == _v1(intent_id)["intent"]


@pytest.mark.parametrize("intent_id", ALL_INTENTS)
def test_every_step_keeps_its_identity(intent_id, digests) -> None:
    """Computed through the real `step_key()`, both sides.

    Asserting the namespace matches is not the same as asserting the keys do:
    the claimed name, OCR text and visual description all feed the hash, so a
    descriptor edited in passing would change identity while the namespace
    still looked right.
    """
    graph = _graph(intent_id, digests)
    v1 = Recipe.load(V1_RECIPES / MIGRATIONS[intent_id][2])
    v2_steps = graph.recipe.value["steps"]
    assert len(v2_steps) == len(v1.steps)

    namespace = graph.recipe.value["step_key_namespace"]
    for index, (v1_step, v2_step) in enumerate(zip(v1.steps, v2_steps)):
        claimed = v2_step["target_descriptor"]["claimed"]
        adapted = Recipe.from_dict(
            {
                "app_id": v1.app_id,
                "intent": namespace,
                "steps": [
                    {
                        "user_action": v2_step["user_action"],
                        "target_descriptor": {"claimed": claimed, "confirmed": []},
                        "instruction_text": v2_step["instruction_text"],
                        "verification_rule": {
                            "kind": "user_confirms",
                            "args": {},
                            "timeout_s": 1.0,
                        },
                        "risk": v2_step["risk"],
                        "preconditions": [],
                        "provenance": v2_step["provenance"],
                    }
                ],
            }
        ).steps[0]
        assert step_key(namespace, adapted) == step_key(v1.intent, v1_step), index


@pytest.mark.parametrize("intent_id", ALL_INTENTS)
def test_claimed_descriptors_and_provenance_survive_verbatim(
    intent_id, digests
) -> None:
    graph = _graph(intent_id, digests)
    v1 = _v1(intent_id)
    for index, (v1_step, v2_step) in enumerate(
        zip(v1["steps"], graph.recipe.value["steps"])
    ):
        v1_claimed = v1_step["target_descriptor"]["claimed"]
        v2_claimed = dict(v2_step["target_descriptor"]["claimed"])
        # v2 states every field explicitly; v1 omitted the ones that were None.
        for field in ("name", "ocr_text", "visual_description"):
            assert v2_claimed[field] == v1_claimed.get(field), (index, field)
        assert _plain(v2_claimed["name_synonyms"]) == list(
            v1_claimed.get("name_synonyms", [])
        ), index
        assert _plain(v2_step["provenance"]) == v1_step["provenance"], index
        assert v2_step["instruction_text"] == v1_step["instruction_text"], index
        assert v2_step["user_action"] == v1_step["user_action"], index
        assert v2_step["risk"] == v1_step["risk"], index


@pytest.mark.parametrize("intent_id", ALL_INTENTS)
def test_verification_kind_and_timeout_are_unchanged(intent_id, digests) -> None:
    graph = _graph(intent_id, digests)
    v1 = _v1(intent_id)
    for index, (v1_step, v2_step) in enumerate(
        zip(v1["steps"], graph.recipe.value["steps"])
    ):
        v1_rule = v1_step["verification_rule"]
        v2_rule = v2_step["verification_rule"]
        assert v2_rule["kind"] == v1_rule["kind"], index
        assert v2_rule["timeout_s"] == v1_rule["timeout_s"], index
        for option in (
            "fail_after_timeout",
            "timeout_from_hint",
            "accept_if_already_present",
        ):
            assert v2_rule["args"].get(option) == v1_rule["args"].get(option), (
                index,
                option,
            )


@pytest.mark.parametrize("intent_id", ALL_INTENTS)
def test_the_v1_descriptor_target_became_a_selector_naming_the_same_control(
    intent_id, digests
) -> None:
    """A descriptor-matched verification becomes a selector for the same name.

    The move from "find something matching this descriptor" to "read this
    declared selector" is the representation change. Which control it means
    is not allowed to change with it.
    """
    graph = _graph(intent_id, digests)
    plan = graph.compiled.plan
    v1 = _v1(intent_id)
    for index, (v1_step, v2_step) in enumerate(
        zip(v1["steps"], graph.recipe.value["steps"])
    ):
        wanted = v1_step["verification_rule"]["args"].get("target_descriptor")
        if wanted is None:
            continue
        selector_id = v2_step["verification_rule"]["selector"]
        assert selector_id is not None, index
        assert wanted["name"] in plan.selectors[selector_id].names, index


@pytest.mark.parametrize("intent_id", ALL_INTENTS)
def test_the_pack_keeps_its_v1_window_identity(intent_id, digests) -> None:
    pack_id = MIGRATIONS[intent_id][0]
    graph = _graph(intent_id, digests)
    manifest = json.loads(
        (V1_MANIFESTS / f"{pack_id}.json").read_text(encoding="utf-8")
    )
    assert _plain(graph.pack.value["executable_names"]) == manifest["executable_names"]
    assert _plain(graph.pack.value["title_patterns"]) == manifest["title_patterns"]
    assert graph.pack.value["display_name"] == manifest["display_name"]


# ---------------------------------------------------------------------------
# Per-workflow requirements
# ---------------------------------------------------------------------------


def test_synthetic_export_declares_its_wrong_action_surface(digests) -> None:
    """The certified test clicks `Wrong control` instead of `Export`.

    A recipe that never named that control would leave the run unable to say
    what the user actually touched, which is the whole of the wrong-action
    feedback D037 added.
    """
    graph = _graph("EXPORT_DATA", digests)
    plan = graph.compiled.plan
    assert set(plan.selectors) == {"export_button", "export_status", "wrong_control"}
    assert graph.compiled.context_selectors == ("wrong_control",)
    assert plan.selectors["wrong_control"].names == ("Wrong control",)
    assert plan.selectors["export_button"].cardinality == "exactly_one"
    assert plan.selectors["export_status"].cardinality == "at_least_one"


def test_synthetic_export_disables_ocr(digests) -> None:
    """UIA reads this Win32 demo cleanly and the certified behaviour never used
    a pixel tier; enabling one would allow a grounding path v1 never had."""
    graph = _graph("EXPORT_DATA", digests)
    assert graph.pack.value["tier2_capture"] == "disabled"


def test_synthetic_export_binds_identity_to_the_demo_bytes(digests) -> None:
    """python.exe hosts it; the interpreter's version is not its identity
    (D073)."""
    graph = _graph("EXPORT_DATA", digests)
    identity = graph.pack.value["version_identity"]
    assert identity["kind"] == "content_sha256"
    assert identity["path"] == "ghostcursor/demo/synthetic_export_app.py"
    assert (REPO_ROOT / identity["path"]).is_file()


def test_open_folder_uses_the_reviewed_bounded_walk(digests) -> None:
    """Bounded descendants, normalised matching, both ellipsis spellings.

    A provider-side exact query returns a dead pointer for this target while
    the Button walk reads it cleanly, so the two strategies are not
    interchangeable here (D069).
    """
    graph = _graph("OPEN_FOLDER", digests)
    selector = graph.compiled.plan.selectors["open_folder"]
    assert selector.strategy == "bounded_descendants"
    assert selector.control_type == "Button"
    assert selector.normalise == "strip_leading_private_use"
    assert selector.cardinality == "exactly_one"
    assert set(selector.names) == {"Open Folder...", "Open Folder…"}


def test_open_folder_writes_no_codicon_glyph_into_the_recipe(digests) -> None:
    """A private-use codepoint is version-sensitive (D069).

    The glyph is normalised away at match time and must never be recorded as
    part of a trusted name.
    """
    graph = _graph("OPEN_FOLDER", digests)
    raw = graph.recipe.raw_bytes.decode("utf-8")
    assert not any(0xE000 <= ord(character) <= 0xF8FF for character in raw)


def test_open_folder_title_verification_reproduces_the_v1_contract(digests) -> None:
    """Parity is the constraint, and it is checked against the real verifier."""
    from ghostcursor.packs.compile import compile_goal_reference, derive_goal_reference
    from ghostcursor.reasoning.schema import VerificationKind, VerificationRule
    from ghostcursor.reasoning.verification import Snapshot, verify
    from ghostcursor.reasoning.vscode import verify_open_folder

    graph = _graph("OPEN_FOLDER", digests)
    args = graph.compiled.steps[0].verification.args
    spec = compile_goal_reference(
        args["goal_reference"], _plain(graph.pack.value["aliases"])
    )
    rule = VerificationRule(VerificationKind.WINDOW_TITLE_MATCHES, args=_plain(args))

    cases = [
        (
            "Visual Studio Code",
            "demo - Visual Studio Code",
            r"Open C:\Projects\Demo in VS Code",
        ),
        ("Visual Studio Code", "demo - Visual Studio Code", "Open a folder in VS Code"),
        (
            "Visual Studio Code",
            "other - Visual Studio Code",
            r"Open C:\Projects\Demo in VS Code",
        ),
        (
            "demo - Visual Studio Code",
            "demo - Visual Studio Code",
            "Open a folder in VS Code",
        ),
        ("Visual Studio Code", "Untitled - Notepad", "Open a folder in VS Code"),
        ("Visual Studio Code", "demo - Code", r"Open C:\Projects\Demo in VS Code"),
        (
            "Welcome - Visual Studio Code",
            "Visual Studio Code",
            "Open a folder in VS Code",
        ),
        ("Visual Studio Code", "workspace - Visual Studio Code", "open ."),
    ]
    for before, after, goal in cases:
        v2 = verify(
            rule,
            Snapshot(title=before, elements=()),
            Snapshot(title=after, elements=()),
            goal_reference=derive_goal_reference(spec, goal),
        )
        v1 = verify_open_folder(
            Snapshot(title=before, elements=()),
            Snapshot(title=after, elements=()),
            goal,
        )
        assert v2 is v1, (before, after, goal)


def test_open_folder_does_not_reuse_the_packs_discovery_patterns(digests) -> None:
    """A discovery pattern is satisfied by every failed run too."""
    graph = _graph("OPEN_FOLDER", digests)
    suffixes = graph.compiled.steps[0].verification.args["completion_title_suffixes"]
    assert tuple(suffixes) == ("visual studio code", " - code")
    assert set(suffixes).isdisjoint(_plain(graph.pack.value["title_patterns"]))


def test_open_terminal_names_exactly_the_certified_controls(digests) -> None:
    """No synonym, no normalisation.

    `Toggle Panel` is a v1 descriptor synonym used for the hint text and never
    for matching; promoting it to a selector name would broaden certified
    behaviour, which the migration is not allowed to do.
    """
    graph = _graph("OPEN_TERMINAL", digests)
    selectors = graph.compiled.plan.selectors
    assert selectors["toggle_panel"].names == ("Toggle Panel (Ctrl+J)",)
    assert selectors["terminal_section"].names == ("Terminal Section",)
    for selector in selectors.values():
        assert selector.normalise == "none", selector.selector_id
        assert selector.strategy == "bounded_descendants"

    v1 = _v1("OPEN_TERMINAL")
    synonyms = v1["steps"][0]["target_descriptor"]["claimed"]["name_synonyms"]
    assert "Toggle Panel" in synonyms
    declared = {name for selector in selectors.values() for name in selector.names}
    assert "Toggle Panel" not in declared


def test_open_terminal_keeps_both_bounded_verification_options(digests) -> None:
    """Each option is load-bearing for a different failure.

    `accept_if_already_present` stops an already-satisfied goal receiving a
    shortcut that closes it; `timeout_from_hint` bounds a no-op shortcut that
    provides no observable action event (D057).
    """
    graph = _graph("OPEN_TERMINAL", digests)
    args = graph.compiled.steps[0].verification.args
    assert args["accept_if_already_present"] is True
    assert args["timeout_from_hint"] is True
    assert args["fail_after_timeout"] is True


def test_no_candidate_promotes_a_positional_automation_id(digests) -> None:
    """`list_id_<n>_<n>` encodes a list index, not a control (D069).

    The compiler refuses one, so a candidate carrying one would not load at
    all -- this asserts none does, at the boundary that would catch it.
    """
    for intent_id in ALL_INTENTS:
        graph = _graph(intent_id, digests)
        raw = graph.recipe.raw_bytes.decode("utf-8")
        assert "list_id_" not in raw, intent_id
        compiled = compile_recipe(graph.recipe.value)
        assert compiled.intent_id == intent_id


# ---------------------------------------------------------------------------
# Observation plans
# ---------------------------------------------------------------------------


EXPECTED_PLANS = {
    "EXPORT_DATA": {
        "traversals": {
            "Button": ["export_button", "wrong_control"],
            "Text": ["export_status"],
        },
        "queries": {},
    },
    "OPEN_FOLDER": {"traversals": {"Button": ["open_folder"]}, "queries": {}},
    "OPEN_TERMINAL": {
        "traversals": {"Button": ["terminal_section", "toggle_panel"]},
        "queries": {},
    },
}


@pytest.mark.parametrize("intent_id", ALL_INTENTS)
def test_the_observation_plan_matches_its_reviewed_shape(intent_id, digests) -> None:
    """One bounded traversal per control type, shared by every selector on it."""
    graph = _graph(intent_id, digests)
    plan = graph.compiled.plan
    expected = EXPECTED_PLANS[intent_id]

    traversals = {
        traversal.control_type: sorted(traversal.selector_ids)
        for traversal in plan.traversals
    }
    assert traversals == {
        control_type: sorted(ids)
        for control_type, ids in expected["traversals"].items()
    }
    assert plan.queries == ()
    covered = {sid for traversal in plan.traversals for sid in traversal.selector_ids}
    assert covered == set(plan.selectors)


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------


def test_the_candidates_live_outside_the_trusted_pack_root() -> None:
    trusted = (REPO_ROOT / "ghostcursor" / "packs").resolve()
    resolved = CANDIDATE_ROOT.resolve()
    assert trusted not in resolved.parents
    assert resolved != trusted


def test_production_has_no_index_that_could_reach_them() -> None:
    """Committing a candidate must not make it discoverable.

    Production still loads v1 manifests; `packs/index.json` does not exist, so
    the activation graph names nothing. Task 9 is what changes that, and only
    for artifacts that have been accepted and installed.
    """
    assert not (REPO_ROOT / "ghostcursor" / "packs" / "index.json").exists()

    from ghostcursor.packs.activation import load_catalog

    catalog = load_catalog(REPO_ROOT)
    assert catalog.packs == {}


def test_the_production_registry_never_scans_the_candidate_directory() -> None:
    from ghostcursor.packs.registry import PackRegistry

    registry = PackRegistry()
    roots = {pack.recipe_directory.resolve() for pack in registry.installed_packs()}
    candidate = CANDIDATE_ROOT.resolve()
    for root in roots:
        assert candidate != root and candidate not in root.parents


def test_no_production_module_references_the_candidate_directory() -> None:
    """A path constant would be a way in that no scan of the registry sees."""
    offenders = []
    for path in (REPO_ROOT / "ghostcursor").rglob("*.py"):
        if "devtools" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "candidates/declarative-workflow-compiler" in text or (
            "superpowers" in text and "candidates" in text
        ):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_the_planner_registry_still_names_only_the_v1_intents() -> None:
    """The candidates grant no planner authority.

    Production authority is still the hardcoded registry until the Task 9
    cutover; a candidate that had quietly joined it would be executable
    without ever having been accepted.
    """
    from ghostcursor.reasoning.planner import registry

    specs = registry()
    for spec in specs.values():
        if spec.recipe_path is None:
            continue
        resolved = spec.recipe_path.resolve()
        assert CANDIDATE_ROOT.resolve() not in resolved.parents


def test_the_builder_is_not_importable_from_production() -> None:
    for path in (REPO_ROOT / "ghostcursor").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            assert not any("build_migration_candidates" in name for name in names), path
