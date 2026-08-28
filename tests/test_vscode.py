from ghostcursor.reasoning.schema import VerificationKind
from ghostcursor.perception.uia import Element
from ghostcursor.reasoning.verification import Snapshot, verify
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

    recipe = Recipe.load("tests/fixtures/v1/packs/recipes/vscode/open_folder.json")
    assert recipe.steps[0].target_descriptor.claimed.name == "Open Folder..."
    rule = recipe.steps[0].verification_rule
    assert rule.kind is VerificationKind.WINDOW_TITLE_MATCHES
    assert rule.timeout_s == 20.0
    assert rule.args["vscode_workspace_title"] is True
    assert rule.args["fail_after_timeout"] is True


def test_vscode_terminal_recipe_uses_application_state_verification():
    from ghostcursor.reasoning.schema import Recipe, UserAction

    recipe = Recipe.load("tests/fixtures/v1/packs/recipes/vscode/open_terminal.json")
    step = recipe.steps[0]

    assert step.target_descriptor.claimed.name == "Toggle Panel (Ctrl+J)"
    assert step.user_action is UserAction.PRESS_KEYS
    assert step.verification_rule.kind is VerificationKind.ELEMENT_APPEARS
    assert step.verification_rule.args["target_descriptor"] == {
        "name": "Terminal Section"
    }
    assert step.verification_rule.args["fail_after_timeout"] is True
    assert step.verification_rule.args["timeout_from_hint"] is True
    assert step.verification_rule.args["accept_if_already_present"] is True
    assert step.verification_rule.timeout_s == 20.0


def test_vscode_terminal_completion_requires_terminal_section_to_appear():
    from ghostcursor.reasoning.schema import Recipe

    recipe = Recipe.load("tests/fixtures/v1/packs/recipes/vscode/open_terminal.json")
    rule = recipe.steps[0].verification_rule
    toggle = Element("Toggle Panel (Ctrl+J)", "Button", "", (10, 10, 30, 30))
    terminal = Element("Terminal Section", "Button", "", (10, 40, 90, 70))

    before = Snapshot("Welcome - Visual Studio Code", (toggle,))
    unchanged = Snapshot("Welcome - Visual Studio Code", (toggle,))
    after = Snapshot("Welcome - Visual Studio Code", (toggle, terminal))

    assert not verify(rule, before, unchanged)
    assert verify(rule, before, after)
