"""The accepted Open Extensions bytes are the production authority after Task 12."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ghostcursor.packs.activation import (
    ApplicationIdentity,
    IntentAvailability,
    load_catalog,
)
from ghostcursor.packs.compile import compile_matcher, compile_planner
from ghostcursor.packs.workflow import (
    AppSnapshot,
    TargetContext,
    materialize,
)


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "docs/superpowers/candidates/declarative-workflow-compiler"
EVIDENCE = ROOT / "docs/evidence/open-extensions-candidate-acceptance.md"
EXPECTED = {
    "pack": "185cd7431e4f7e5ecd2d9e372a15690edd496a26667bafbb59f218762bb2f992",
    "intent": "f4c5f6a24ab494660fa51cd9b1676ed437cc79c5877eb735b34607771446e025",
    "recipe": "b749cca0ff2f12929321effc46383baba7816bfd5b043e1f94e4e38e3ea1cca7",
    "evidence": "18710dc4500c8b372e2a28142b3daa5f6ca112e68f96140eb77a7ca504998a51",
}


def _catalog_entry():
    catalog = load_catalog(ROOT)
    assert catalog.root_valid, catalog.diagnostics
    assert catalog.diagnostics == ()
    pack = catalog.packs["vscode"]
    return catalog, pack, pack.intents["OPEN_EXTENSIONS"]


def test_production_catalog_activates_the_reviewed_adoption() -> None:
    catalog, pack, intent = _catalog_entry()
    assert pack.activation_generation == 2
    assert intent.availability is IntentAvailability.ACTIVE
    adoption = intent.active_adoption
    assert adoption is not None
    assert adoption.adoption_id == "accept-open-extensions-1"
    assert adoption.accepted_application_identity == ApplicationIdentity(
        kind="executable_version", value="1.135.0.0"
    )
    assert adoption.accepted_pack.sha256 == EXPECTED["pack"]
    assert adoption.accepted_intent.sha256 == EXPECTED["intent"]
    assert adoption.recipe.sha256 == EXPECTED["recipe"]
    assert adoption.evidence.sha256 == EXPECTED["evidence"]
    assert adoption.review_commit == "9af7cb9af0c3cb1c26acb898f741331547bd8a5c"


def test_installed_intent_and_recipe_are_the_accepted_candidate_bytes() -> None:
    paths = {
        "intent": "vscode/intents/open_extensions.f4c5f6a24ab49466.json",
        "recipe": "vscode/recipes/open_extensions.b749cca0ff2f1292.json",
    }
    for label, relative in paths.items():
        installed = ROOT / "ghostcursor/packs" / relative
        candidate = CANDIDATE / relative
        assert installed.read_bytes() == candidate.read_bytes()
        assert hashlib.sha256(installed.read_bytes()).hexdigest() == EXPECTED[label]
    assert hashlib.sha256(EVIDENCE.read_bytes()).hexdigest() == EXPECTED["evidence"]


def test_production_matcher_and_planner_expose_the_active_workflow() -> None:
    catalog, _pack, _intent = _catalog_entry()
    match = compile_matcher(catalog).classify("open extensions in vscode")
    assert (match.intent_id, match.confidence, match.kind) == (
        "OPEN_EXTENSIONS",
        0.95,
        "matched",
    )
    specs = {spec.intent_id: spec for spec in compile_planner(catalog)}
    assert specs["OPEN_EXTENSIONS"].recipe_path == (
        ROOT
        / "ghostcursor/packs/vscode/recipes/open_extensions.b749cca0ff2f1292.json"
    )


def test_production_materialization_binds_the_reviewed_bytes() -> None:
    catalog, pack, intent = _catalog_entry()
    app = AppSnapshot(
        executable_name="code.exe", version="1.135.0.0", process_id=4242
    )
    target = TargetContext(
        hwnd=101,
        title="Welcome - AIOS - Visual Studio Code",
        app=app,
        identity=ApplicationIdentity(kind="executable_version", value="1.135.0.0"),
    )
    workflow = materialize(catalog, pack, intent, "open extensions in vscode", target)
    assert workflow.intent_id == "OPEN_EXTENSIONS"
    assert workflow.activation_generation == 2
    assert workflow.pack_sha256 == EXPECTED["pack"]
    assert workflow.intent_sha256 == EXPECTED["intent"]
    assert workflow.recipe_sha256 == EXPECTED["recipe"]
    assert workflow.evidence_sha256 == EXPECTED["evidence"]
    assert workflow.target.hwnd == 101
    assert workflow.recipe.steps[0].target_selector == "extensions_tab"


def test_no_workflow_specific_production_python_was_added() -> None:
    offenders = []
    for path in (ROOT / "ghostcursor").rglob("*.py"):
        if "OPEN_EXTENSIONS" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
