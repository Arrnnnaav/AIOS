"""PowerPoint begins as a measured, data-only, inactive plugin candidate."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from ghostcursor.devtools.candidate_acceptance import load_candidate
from ghostcursor.packs.activation import IntentAvailability, load_catalog
from ghostcursor.packs.compile import compile_matcher, compile_planner


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT / "plugins" / "sources" / "powerpoint"
CANDIDATE_ROOT = SOURCE_ROOT / "payload" / "ghostcursor" / "packs" / "powerpoint"


def _digests() -> dict[str, str]:
    return json.loads(
        (SOURCE_ROOT / "candidate-digests.json").read_text(encoding="utf-8")
    )["artifacts"]


def test_candidate_digest_inventory_binds_every_declared_artifact():
    for relative, expected in _digests().items():
        assert hashlib.sha256((CANDIDATE_ROOT / relative).read_bytes()).hexdigest() == expected


def test_add_slide_candidate_loads_and_compiles_without_application_python():
    digests = _digests()
    graph = load_candidate(
        CANDIDATE_ROOT,
        pack_path=CANDIDATE_ROOT / "pack" / "powerpoint.json",
        pack_sha256=digests["pack/powerpoint.json"],
        intent_path=CANDIDATE_ROOT / "intents" / "add_slide.json",
        intent_sha256=digests["intents/add_slide.json"],
        recipe_path=CANDIDATE_ROOT / "recipes" / "add_slide.json",
        recipe_sha256=digests["recipes/add_slide.json"],
        project_root=REPO_ROOT,
    )
    assert graph.intent.value["intent_id"] == "ADD_SLIDE"
    assert graph.recipe.value["steps"][0]["preconditions"] == ("slide1_before",)
    assert {
        selector.strategy for selector in graph.compiled.plan.selectors.values()
    } == {"provider_exact"}
    assert set(graph.compiled.plan.selectors) == {
        "new_slide", "slide1_before", "slide2_after"
    }
    assert not list(SOURCE_ROOT.rglob("*.py"))


def test_candidate_is_nameable_but_carries_no_execution_authority(tmp_path):
    project = tmp_path / "candidate"
    packs = project / "ghostcursor" / "packs"
    packs.mkdir(parents=True)
    shutil.copy2(SOURCE_ROOT / "index.json", packs / "index.json")
    shutil.copytree(CANDIDATE_ROOT, packs / "powerpoint")
    shutil.copytree(SOURCE_ROOT / "payload" / "docs", project / "docs")

    catalog = load_catalog(project)
    intent = catalog.packs["powerpoint"].intents["ADD_SLIDE"]
    decision = compile_matcher(catalog).classify("add a slide in powerpoint")
    planner = {spec.intent_id: spec for spec in compile_planner(catalog)}

    assert catalog.root_valid and catalog.diagnostics == ()
    assert decision.intent_id == "ADD_SLIDE"
    assert intent.availability is IntentAvailability.KNOWN_INTENT_RECIPE_UNAVAILABLE
    assert intent.active_adoption is None
    assert planner["ADD_SLIDE"].recipe_path is None


def test_candidate_source_declares_only_the_powerpoint_executable():
    specification = json.loads(
        (SOURCE_ROOT / "plugin-source.json").read_text(encoding="utf-8")
    )
    assert specification["applications"] == [
        {"kind": "executable", "value": "powerpnt.exe"}
    ]
    assert "capabilities.json" not in {
        item["destination"] for item in specification["files"]
    }
