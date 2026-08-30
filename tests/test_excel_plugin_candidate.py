"""Excel is a two-workflow, data-only, inactive plugin candidate."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ghostcursor.devtools.candidate_acceptance import load_candidate
from ghostcursor.packs.activation import IntentAvailability, load_catalog
from ghostcursor.packs.compile import compile_matcher


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "plugins" / "sources" / "excel"
CANDIDATE_ROOT = SOURCE_ROOT / "payload" / "ghostcursor" / "packs" / "excel"
D080_BASELINE = "e7aab9c51af6cdb6d296df3080340f8f50f5df4f"
CANDIDATE_COMMIT = "827071c3e92979b53556b1796629be36c80a9cda"
D032_REVIEW_COMMIT = "381d97f5f376ee586260eb4430595fcff1e2668e"


@pytest.fixture(scope="module")
def digests() -> dict[str, str]:
    return json.loads(
        (SOURCE_ROOT / "candidate-digests.json").read_text(encoding="utf-8")
    )["artifacts"]


def _graph(stem: str, digests: dict[str, str]):
    return load_candidate(
        CANDIDATE_ROOT,
        pack_path=CANDIDATE_ROOT / "pack" / "excel.json",
        pack_sha256=digests["pack/excel.json"],
        intent_path=CANDIDATE_ROOT / "intents" / f"{stem}.json",
        intent_sha256=digests[f"intents/{stem}.json"],
        recipe_path=CANDIDATE_ROOT / "recipes" / f"{stem}.json",
        recipe_sha256=digests[f"recipes/{stem}.json"],
        project_root=REPO_ROOT,
    )


@pytest.fixture(scope="module")
def catalog(tmp_path_factory):
    project = tmp_path_factory.mktemp("excel-candidate-catalog")
    packs = project / "ghostcursor" / "packs"
    packs.mkdir(parents=True)
    shutil.copy2(SOURCE_ROOT / "index.json", packs / "index.json")
    shutil.copytree(CANDIDATE_ROOT, packs / "excel")
    shutil.copytree(SOURCE_ROOT / "payload" / "docs", project / "docs")
    loaded = load_catalog(project)
    assert loaded.root_valid
    assert loaded.diagnostics == ()
    return loaded


def test_every_candidate_digest_binds_the_exact_raw_bytes(digests) -> None:
    for relative, expected in digests.items():
        actual = hashlib.sha256((CANDIDATE_ROOT / relative).read_bytes()).hexdigest()
        assert actual == expected, relative


@pytest.mark.parametrize(
    ("stem", "intent_id", "control_types"),
    [
        (
            "select_cell_b2",
            "SELECT_CELL_B2",
            {"DataItem"},
        ),
        (
            "add_worksheet",
            "ADD_WORKSHEET",
            {"Button", "TabItem"},
        ),
    ],
)
def test_each_excel_candidate_loads_and_compiles(
    stem, intent_id, control_types, digests
) -> None:
    graph = _graph(stem, digests)
    assert graph.intent.value["intent_id"] == intent_id
    assert graph.recipe.value["intent_id"] == intent_id
    assert {selector.strategy for selector in graph.compiled.plan.selectors.values()} == {
        "window_descendants"
    }
    assert {
        selector.control_type for selector in graph.compiled.plan.selectors.values()
    } == control_types


def test_reviewed_graph_is_nameable_and_has_exact_execution_authority(catalog) -> None:
    matcher = compile_matcher(catalog)
    for goal, intent_id in (
        ("select cell b2 in excel", "SELECT_CELL_B2"),
        ("add a new sheet in excel", "ADD_WORKSHEET"),
    ):
        decision = matcher.classify(goal)
        assert (decision.intent_id, decision.kind) == (intent_id, "matched")

    pack = catalog.packs["excel"]
    assert set(pack.intents) == {"ADD_WORKSHEET", "SELECT_CELL_B2"}
    assert all(
        intent.availability is IntentAvailability.ACTIVE
        for intent in pack.intents.values()
    )
    assert all(intent.active_adoption is not None for intent in pack.intents.values())
    assert {
        intent.active_adoption.review_commit for intent in pack.intents.values()
    } == {D032_REVIEW_COMMIT}
    assert {
        intent.active_adoption.reviewer_id for intent in pack.intents.values()
    } == {"codex-d032-heisenberg"}
    assert {
        intent.active_adoption.accepted_application_identity.value
        for intent in pack.intents.values()
    } == {"16.0.20326.20112"}


def test_reviewed_evidence_commit_precedes_every_activation() -> None:
    reviewed = subprocess.run(
        [
            "git",
            "show",
            f"{D032_REVIEW_COMMIT}:plugins/sources/excel/payload/ghostcursor/packs/excel/activation.json",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    activation = json.loads(reviewed)
    assert all(
        entry["active_adoption_id"] is None and entry["adoptions"] == {}
        for entry in activation["intents"].values()
    )


def test_excel_candidate_contains_no_executable_plugin_code() -> None:
    assert not list(SOURCE_ROOT.rglob("*.py"))
    specification = json.loads(
        (SOURCE_ROOT / "plugin-source.json").read_text(encoding="utf-8")
    )
    assert specification["applications"] == [
        {"kind": "executable", "value": "excel.exe"}
    ]
    assert specification["trees"] == [
        {
            "destination": "ghostcursor/packs/excel",
            "source": "plugins/sources/excel/payload/ghostcursor/packs/excel",
        },
        {
            "destination": "docs/evidence",
            "source": "plugins/sources/excel/payload/docs/evidence",
        },
    ]


def test_excel_authoring_after_the_generic_grammar_adds_no_production_python() -> None:
    changed = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            D080_BASELINE,
            CANDIDATE_COMMIT,
            "--",
            ":(glob)ghostcursor/**/*.py",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert changed == []
