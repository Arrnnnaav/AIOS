"""Task 9 production-authority checks over the installed schema-v2 catalog."""

from pathlib import Path

from ghostcursor.packs.activation import IntentAvailability, load_catalog
from ghostcursor.packs.compile import compile_matcher, compile_planner
from ghostcursor.reasoning.planner import plan_compiled_goal


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_installed_catalog_is_the_complete_cutover_graph() -> None:
    catalog = load_catalog(PROJECT_ROOT)
    assert catalog.root_valid
    assert set(catalog.packs) == {"common", "notepad", "synthetic", "vscode"}
    assert catalog.packs["synthetic"].intents["EXPORT_DATA"].availability is IntentAvailability.ACTIVE
    assert catalog.packs["vscode"].intents["OPEN_FOLDER"].availability is IntentAvailability.ACTIVE
    assert catalog.packs["vscode"].intents["OPEN_TERMINAL"].availability is IntentAvailability.ACTIVE
    assert catalog.packs["common"].intents["CREATE_DOCUMENT"].active_adoption is None


def test_installed_matcher_and_planner_have_one_v2_authority() -> None:
    catalog = load_catalog(PROJECT_ROOT)
    matcher = compile_matcher(catalog)
    specs = {spec.intent_id: spec for spec in compile_planner(catalog)}
    assert matcher.classify("Open a folder in VS Code").intent_id == "OPEN_FOLDER"
    assert matcher.classify("Open the integrated terminal in VS Code").intent_id == "OPEN_TERMINAL"
    assert specs["OPEN_FOLDER"].recipe_path is not None
    assert specs["CREATE_DOCUMENT"].recipe_path is None


def test_compiled_goal_requires_a_real_target_before_execution() -> None:
    result = plan_compiled_goal(
        "Open a folder in VS Code",
        use_model=False,
        target_title_re="^no-such-window$",
    )
    assert result.intent_id == "OPEN_FOLDER"
    assert result.plan is None
    assert result.status.value == "KNOWN_INTENT_RECIPE_UNAVAILABLE"
