"""Task 11: Open Extensions is a quarantined, data-only workflow."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ghostcursor.devtools.candidate_acceptance import load_candidate
from ghostcursor.packs.activation import IntentAvailability, load_catalog
from ghostcursor.packs.compile import compile_matcher, compile_planner
from ghostcursor.perception.service import run_observation_plan
from ghostcursor.perception.uia import SelectorAmbiguityFault, provider_exact


REPO_ROOT = Path(__file__).resolve().parent.parent
CANDIDATE_ROOT = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "candidates"
    / "declarative-workflow-compiler"
)
BASELINE_COMMIT = "41682ee5b41a8742b0b0ec8d60ffeca4014d0b44"
ACTIVATION_COMMIT = "2736d1b841696c07f20eb935cfb022d37bfae156"
BASELINE_TREE = "fd6824109c6bf8b509bc3da4fd6b49a696e136a5"
CUTOVER_COMMIT = "108b6fb3f0fee5c4fd564d093f4229accfa74ba2"
ACTION_NAME = "Extensions (Ctrl+Shift+X)"
VERIFY_NAME = "Installed Section"


@pytest.fixture(scope="module")
def digests() -> dict[str, str]:
    value = json.loads(
        (CANDIDATE_ROOT / "digests.json").read_text(encoding="utf-8")
    )
    return value["artifacts"]


def _artifact(kind: str, stem: str, digests: dict[str, str]) -> Path:
    prefix = f"vscode/{kind}/{stem}."
    matches = [path for path in digests if path.startswith(prefix)]
    assert len(matches) == 1, f"{prefix} names {len(matches)} artifacts"
    return CANDIDATE_ROOT / matches[0]


@pytest.fixture(scope="module")
def graph(digests):
    paths = {
        "pack": _artifact("pack", "vscode", digests),
        "intent": _artifact("intents", "open_extensions", digests),
        "recipe": _artifact("recipes", "open_extensions", digests),
    }

    def relative(path: Path) -> str:
        return path.relative_to(CANDIDATE_ROOT).as_posix()

    return load_candidate(
        CANDIDATE_ROOT,
        pack_path=paths["pack"],
        pack_sha256=digests[relative(paths["pack"])],
        intent_path=paths["intent"],
        intent_sha256=digests[relative(paths["intent"])],
        recipe_path=paths["recipe"],
        recipe_sha256=digests[relative(paths["recipe"])],
        project_root=REPO_ROOT,
    )


@pytest.fixture(scope="module")
def catalog(tmp_path_factory):
    root = tmp_path_factory.mktemp("open-extensions-catalog")
    packs = root / "ghostcursor" / "packs"
    packs.parent.mkdir(parents=True)
    shutil.copytree(CANDIDATE_ROOT, packs)
    demo = root / "ghostcursor" / "demo"
    demo.mkdir()
    shutil.copy2(
        REPO_ROOT / "ghostcursor" / "demo" / "synthetic_export_app.py",
        demo / "synthetic_export_app.py",
    )
    return load_catalog(root)


class _Rect:
    left, top, right, bottom = 1093, 923, 1133, 969


class _Info:
    def __init__(self, name: str, control_type: str, runtime_id: tuple[int, ...]):
        self.name = name
        self.control_type = control_type
        self.automation_id = ""
        self.rectangle = _Rect()
        self.runtime_id = runtime_id


def test_the_proof_baseline_is_the_independently_recertified_tree() -> None:
    recorded = json.loads(
        (CANDIDATE_ROOT / "proof-baseline.json").read_text(encoding="utf-8")
    )
    assert recorded == {
        "schema_version": 1,
        "proof": "open_extensions_data_only",
        "compiler_baseline_commit": BASELINE_COMMIT,
        "compiler_baseline_tree": BASELINE_TREE,
        "task9_cutover_commit": CUTOVER_COMMIT,
    }
    actual_tree = subprocess.run(
        ["git", "rev-parse", f"{BASELINE_COMMIT}^{{tree}}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert actual_tree == BASELINE_TREE


def test_the_proof_diff_contains_no_production_python_change() -> None:
    """D078 fixes both proof endpoints; later shared fixes cannot move them."""
    tracked = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            BASELINE_COMMIT,
            ACTIVATION_COMMIT,
            "--",
            ":(glob)ghostcursor/**/*.py",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "ghostcursor"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert tracked == []
    assert [path for path in untracked if path.endswith(".py")] == []


def test_open_extensions_uses_only_the_frozen_d072_grammar(graph) -> None:
    assert graph.intent.value["intent_id"] == "OPEN_EXTENSIONS"
    assert graph.intent.value["rules"] == (
        {
            "tier": "exact",
            "phrases": (
                "open extensions in vs code",
                "open extensions in vscode",
                "open the extensions view in vs code",
                "open the extensions view in vscode",
            ),
        },
        {
            "tier": "heuristic",
            "all_of": (
                {"any_of": ({"token": "open"}, {"token": "show"})},
                {"any_of": ({"token": "extensions"},)},
                {"any_of": ({"alias": "vscode_names"},)},
            ),
        },
    )


def test_exact_and_heuristic_rules_compile_without_a_new_primitive(catalog) -> None:
    matcher = compile_matcher(catalog)
    exact = matcher.classify("open extensions in vscode")
    heuristic = matcher.classify("show extensions in visual studio code")
    assert (exact.intent_id, exact.confidence, exact.kind) == (
        "OPEN_EXTENSIONS",
        0.95,
        "matched",
    )
    assert (heuristic.intent_id, heuristic.confidence, heuristic.kind) == (
        "OPEN_EXTENSIONS",
        0.85,
        "matched",
    )


def test_the_recipe_is_exactly_the_reviewed_selector_contract(graph) -> None:
    recipe = graph.recipe.value
    assert recipe["intent_id"] == "OPEN_EXTENSIONS"
    assert recipe["context_selectors"] == ()
    assert recipe["selectors"] == {
        "extensions_tab": {
            "strategy": "provider_exact",
            "control_type": "TabItem",
            "names": (ACTION_NAME,),
            "normalise": "none",
            "cardinality": "exactly_one",
            "result_limit": 8,
        },
        "installed_section": {
            "strategy": "provider_exact",
            "control_type": "Button",
            "names": (VERIFY_NAME,),
            "normalise": "none",
            "cardinality": "at_least_one",
            "result_limit": 8,
        },
    }
    step = recipe["steps"][0]
    assert step["target_selector"] == "extensions_tab"
    assert step["verification_rule"] == {
        "kind": "element_appears",
        "selector": "installed_section",
        "args": {},
        "timeout_s": 20.0,
    }


def test_bare_name_is_ambiguous_but_the_reviewed_tabitem_is_exact() -> None:
    tab = _Info(ACTION_NAME, "TabItem", (42, 460470, 4, 4, 1, 890))
    group = _Info(ACTION_NAME, "Group", (42, 460470, 4, 4, 1, 891))
    with pytest.raises(SelectorAmbiguityFault, match="matched 2 controls"):
        provider_exact(lambda: [tab, group], lambda raw: raw)

    selected = provider_exact(lambda: [tab], lambda raw: raw)
    assert len(selected) == 1
    assert selected[0].control_type == "TabItem"


def test_the_compiled_plan_queries_the_reviewed_types_and_cardinalities(graph) -> None:
    plan = graph.compiled.plan
    calls: list[tuple[str, str]] = []
    tab = _Info(ACTION_NAME, "TabItem", (42, 460470, 4, 4, 1, 890))

    def query_for(control_type: str, name: str):
        calls.append((control_type, name))
        found = [tab] if (control_type, name) == ("TabItem", ACTION_NAME) else []
        return lambda: found

    observed = run_observation_plan(
        plan,
        query_for=query_for,
        make_info=lambda raw: raw,
    )
    assert calls == [("TabItem", ACTION_NAME), ("Button", VERIFY_NAME)]
    assert len(observed.selectors["extensions_tab"]) == 1
    assert observed.selectors["installed_section"] == ()


def test_the_candidate_is_registered_but_has_no_execution_authority(catalog) -> None:
    intent = catalog.packs["vscode"].intents["OPEN_EXTENSIONS"]
    assert intent.availability is IntentAvailability.KNOWN_INTENT_RECIPE_UNAVAILABLE
    assert intent.active_adoption is None
    assert intent.adoptions == {}
    specs = {spec.intent_id: spec for spec in compile_planner(catalog)}
    assert specs["OPEN_EXTENSIONS"].recipe_path is None


def test_open_extensions_digests_bind_the_exact_candidate_bytes(digests) -> None:
    relatives = [
        path
        for path in digests
        if "/open_extensions." in path or path.startswith("vscode/pack/")
    ]
    assert len(relatives) == 3
    for relative in relatives:
        raw = (CANDIDATE_ROOT / relative).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digests[relative]
