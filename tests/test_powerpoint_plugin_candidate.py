"""PowerPoint guided and autonomous candidates stay inactive until acceptance."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

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


@pytest.mark.parametrize(
    ("stem", "intent_id", "selector_ids", "step_count"),
    (
        (
            "add_slide",
            "ADD_SLIDE",
            {"new_slide", "slide1_before", "slide2_after"},
            1,
        ),
        (
            "insert_bar_chart",
            "INSERT_BAR_CHART",
            {
                "bar_category",
                "bar_selected",
                "chart_button",
                "chart_design",
                "confirm_chart",
                "insert_tab",
                "slide2_before",
            },
            4,
        ),
        (
            "open_comment_editor",
            "OPEN_COMMENT_EDITOR",
            {"comment_button", "comment_editor", "insert_tab", "slide2_before"},
            2,
        ),
        (
            "open_normal_view",
            "OPEN_NORMAL_VIEW",
            {"normal_button", "normal_slide_pane", "slide2_before", "slide_sorter_before"},
            1,
        ),
        (
            "open_slide_sorter",
            "OPEN_SLIDE_SORTER",
            {"slide2_before", "slide_sorter_button", "slide_sorter_pane"},
            1,
        ),
    ),
)
def test_each_candidate_loads_and_compiles_without_application_python(
    stem, intent_id, selector_ids, step_count
):
    digests = _digests()
    graph = load_candidate(
        CANDIDATE_ROOT,
        pack_path=CANDIDATE_ROOT / "pack" / "powerpoint.json",
        pack_sha256=digests["pack/powerpoint.json"],
        intent_path=CANDIDATE_ROOT / "intents" / f"{stem}.json",
        intent_sha256=digests[f"intents/{stem}.json"],
        recipe_path=CANDIDATE_ROOT / "recipes" / f"{stem}.json",
        recipe_sha256=digests[f"recipes/{stem}.json"],
        project_root=REPO_ROOT,
    )
    assert graph.intent.value["intent_id"] == intent_id
    assert len(graph.recipe.value["steps"]) == step_count
    assert {
        selector.strategy for selector in graph.compiled.plan.selectors.values()
    } == {"provider_exact"}
    assert set(graph.compiled.plan.selectors) == selector_ids
    assert all(
        selector.cardinality == "exactly_one"
        for selector_id, selector in graph.compiled.plan.selectors.items()
        if selector_id in {
            step.target_selector for step in graph.compiled.steps
        }
    )
    assert {
        path.relative_to(SOURCE_ROOT).as_posix()
        for path in SOURCE_ROOT.rglob("*.py")
    } == {
        "payload/ghostcursor/adapter/powerpoint_adapter.py",
        "payload/ghostcursor/adapter/powerpoint_live_verifier.py",
        "payload/ghostcursor/adapter/powerpoint_verifier.py",
        "payload/ghostcursor/adapter/uia_adapter.py",
    }
    # The third file is not application Python and must not become any: it is
    # the canonical shared adapter, byte-for-byte (D108). Widening the set
    # above without this would let anything at all be added under that name.
    import hashlib

    shipped = (SOURCE_ROOT / "payload/ghostcursor/adapter/uia_adapter.py").read_bytes()
    canonical = (
        Path(__file__).resolve().parents[1] / "plugins/shared/uia_adapter.py"
    ).read_bytes()
    assert shipped == canonical
    from ghostcursor.plugins.bundle import CANONICAL_UIA_ADAPTER_SHA256

    assert hashlib.sha256(shipped).hexdigest() == CANONICAL_UIA_ADAPTER_SHA256


def test_candidate_is_nameable_but_carries_no_execution_authority(tmp_path):
    project = tmp_path / "candidate"
    packs = project / "ghostcursor" / "packs"
    packs.mkdir(parents=True)
    shutil.copy2(SOURCE_ROOT / "index.json", packs / "index.json")
    shutil.copytree(CANDIDATE_ROOT, packs / "powerpoint")
    shutil.copytree(SOURCE_ROOT / "payload" / "docs", project / "docs")

    catalog = load_catalog(project)
    pack = catalog.packs["powerpoint"]
    matcher = compile_matcher(catalog)
    planner = {spec.intent_id: spec for spec in compile_planner(catalog)}

    assert catalog.root_valid and catalog.diagnostics == ()
    assert matcher.classify("add a slide in powerpoint").intent_id == "ADD_SLIDE"
    assert matcher.classify("insert a bar chart in powerpoint").intent_id == "INSERT_BAR_CHART"
    assert matcher.classify("add a comment in powerpoint").intent_id == "OPEN_COMMENT_EDITOR"
    assert matcher.classify("open normal view in powerpoint").intent_id == "OPEN_NORMAL_VIEW"
    assert matcher.classify("open slide sorter in powerpoint").intent_id == "OPEN_SLIDE_SORTER"
    assert matcher.classify("build the ghostcursor investor deck in powerpoint").intent_id == "BUILD_INVESTOR_DECK"
    assert matcher.classify("build the animation catalog in powerpoint").intent_id == "BUILD_ANIMATION_CATALOG"
    assert set(pack.intents) == {
        "ADD_SLIDE",
        "BUILD_ANIMATION_CATALOG",
        "BUILD_INVESTOR_DECK",
        "INSERT_BAR_CHART",
        "OPEN_COMMENT_EDITOR",
        "OPEN_NORMAL_VIEW",
        "OPEN_SLIDE_SORTER",
    }
    assert all(
        intent.availability is IntentAvailability.KNOWN_INTENT_RECIPE_UNAVAILABLE
        and intent.active_adoption is None
        for intent in pack.intents.values()
    )
    assert all(spec.recipe_path is None for spec in planner.values())


def test_candidate_source_declares_only_the_powerpoint_executable():
    specification = json.loads(
        (SOURCE_ROOT / "plugin-source.json").read_text(encoding="utf-8")
    )
    assert specification["applications"] == [
        {"kind": "executable", "value": "powerpnt.exe"}
    ]
    destinations = {
        item["destination"] for item in specification["files"]
    }
    assert "capabilities.json" not in destinations
    assert {"ghostcursor/action-plans.json", "ghostcursor/operations.json"} <= destinations
    assert specification["adapter_api"] == {
        "entrypoint": "ghostcursor/adapter/powerpoint_adapter.py",
        "operations": "ghostcursor/operations.json",
        "plans": "ghostcursor/action-plans.json",
        "protocol_version": 1,
        # The generic UIA adapter, shipped because at least one operation
        # declares a UIA backend. Bundle verification refuses either half of
        # that pairing on its own (D108).
        "uia_entrypoint": "ghostcursor/adapter/uia_adapter.py",
        "verifier": "ghostcursor/adapter/powerpoint_verifier.py",
        # The live-state verifier, required by the same pairing rule. The
        # verifier above reads a saved file, which is the wrong evidence for
        # an effect that only exists in the running application; shipping a
        # UIA backend without this would ship an action nothing can confirm.
        "live_verifier": "ghostcursor/adapter/powerpoint_live_verifier.py",
    }
