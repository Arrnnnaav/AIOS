from ghostcursor.reasoning.schema import VerificationKind
from ghostcursor.reasoning.verification import Snapshot
from ghostcursor.reasoning.vscode import (
    folder_reference_from_goal,
    is_valid_vscode_workspace_title,
    normalize_title_text,
    verify_open_folder,
)


def test_title_normalization_is_case_insensitive_and_collapses_whitespace():
    assert normalize_title_text("  My   VSCode-Project  ") == "my vscode-project"


def test_full_path_goal_uses_final_folder_segment():
    assert folder_reference_from_goal(r"Open C:\Projects\VSCode-Project in VS Code") == "vscode-project"
    assert folder_reference_from_goal("Open /home/user/my app in VS Code") == "my app"


def test_degenerate_folder_reference_is_safe():
    assert folder_reference_from_goal("Open . in VS Code") == "."
    assert len(folder_reference_from_goal("Open . in VS Code")) < 2


def test_vscode_title_verification_matches_folder_and_title_variant():
    before = Snapshot("Visual Studio Code", ())
    after = Snapshot("  vscode-project  -  Visual Studio Code", ())

    assert is_valid_vscode_workspace_title(after.title)
    assert verify_open_folder(before, after, r"Open C:\Projects\VSCode-Project in VS Code")


def test_vscode_title_verification_uses_transition_fallback_for_degenerate_reference():
    before = Snapshot("Visual Studio Code", ())
    after = Snapshot("Workspace - Visual Studio Code", ())

    assert verify_open_folder(before, after, "Open . in VS Code")


def test_vscode_title_verification_rejects_wrong_folder():
    before = Snapshot("Visual Studio Code", ())
    after = Snapshot("other-project - Visual Studio Code", ())

    assert not verify_open_folder(before, after, "Open vscode-project in VS Code")


def test_vscode_recipe_uses_title_verification_rule():
    from ghostcursor.reasoning.schema import Recipe

    recipe = Recipe.load("ghostcursor/packs/recipes/vscode/open_folder.json")
    assert recipe.steps[0].target_descriptor.claimed.name == "Open Folder..."
    rule = recipe.steps[0].verification_rule
    assert rule.kind is VerificationKind.WINDOW_TITLE_MATCHES
    assert rule.timeout_s == 20.0
    assert rule.args["vscode_workspace_title"] is True
    assert rule.args["fail_after_timeout"] is True
