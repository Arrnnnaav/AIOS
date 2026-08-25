import pytest

from ghostcursor.reasoning.planner import PlanStatus, plan_goal


def test_exact_export_goal_is_supported_without_model():
    result = plan_goal("Export this table as CSV", use_model=False)
    assert result.status is PlanStatus.SUPPORTED
    assert result.confidence == 0.95
    assert result.plan is not None


def test_synonym_uses_deterministic_fallback():
    result = plan_goal("save the table as a spreadsheet", use_model=False)
    assert result.confidence == 0.85
    assert result.plan is not None


def test_unmatched_goal_is_explicitly_unsupported():
    result = plan_goal("rearrange my desktop wallpaper", use_model=False)
    assert result.status is PlanStatus.UNSUPPORTED_GOAL
    assert result.plan is None


def test_valid_unavailable_model_intent_is_not_fallback(monkeypatch):
    monkeypatch.setattr(
        "ghostcursor.reasoning.planner._model_intent",
        lambda *args: ("OPEN_SETTINGS", 0.9, "settings"),
    )
    result = plan_goal("open settings")
    assert result.status is PlanStatus.KNOWN_INTENT_RECIPE_UNAVAILABLE
    assert result.plan is None


def test_malformed_model_output_keeps_a_valid_fallback(monkeypatch):
    def malformed(*args):
        raise ValueError("bad JSON")

    monkeypatch.setattr("ghostcursor.reasoning.planner._model_intent", malformed)
    result = plan_goal("Export this table as CSV")
    assert result.status is PlanStatus.INVALID_MODEL_OUTPUT
    assert result.plan is not None


def test_fallback_recognizes_vscode_open_folder_goal():
    result = plan_goal(
        r"Open C:\Projects\Customer-Portal in VS Code",
        use_model=False,
    )

    assert result.intent_id == "OPEN_FOLDER"
    assert result.plan is not None
    assert result.plan.app_id == "code.exe"


def test_exact_cli_vscode_goal_is_a_strong_deterministic_match():
    result = plan_goal("Open a folder in VS Code", use_model=False)

    assert result.status is PlanStatus.SUPPORTED
    assert result.intent_id == "OPEN_FOLDER"
    assert result.confidence == 0.95
    assert result.plan is not None


def test_exact_cli_vscode_goal_survives_unavailable_model(monkeypatch):
    def unavailable(*args):
        raise TimeoutError("Ollama unavailable")

    monkeypatch.setattr("ghostcursor.reasoning.planner._model_intent", unavailable)
    result = plan_goal("Open a folder in VS Code")

    assert result.status is PlanStatus.MODEL_UNAVAILABLE_FALLBACK
    assert result.intent_id == "OPEN_FOLDER"
    assert result.confidence == 0.95
    assert result.plan is not None


def test_exact_vscode_terminal_goal_is_supported_without_model():
    result = plan_goal("Open the integrated terminal in VS Code", use_model=False)

    assert result.status is PlanStatus.SUPPORTED
    assert result.intent_id == "OPEN_TERMINAL"
    assert result.confidence == 0.95
    assert result.plan is not None
    assert result.plan.app_id == "code.exe"


def test_vscode_terminal_goal_survives_unavailable_model(monkeypatch):
    monkeypatch.setattr(
        "ghostcursor.reasoning.planner._model_intent",
        lambda *args: (_ for _ in ()).throw(TimeoutError("Ollama unavailable")),
    )

    result = plan_goal("Open the integrated terminal in VS Code")

    assert result.status is PlanStatus.MODEL_UNAVAILABLE_FALLBACK
    assert result.intent_id == "OPEN_TERMINAL"
    assert result.plan is not None


def test_goal_planner_rejects_a_registered_recipe_outside_trusted_roots(
    monkeypatch, tmp_path
):
    from ghostcursor.reasoning import planner

    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    spec = planner.IntentSpec(
        "OPEN_TERMINAL",
        ("open the integrated terminal in vs code",),
        outside,
    )
    monkeypatch.setattr(planner, "registry", lambda: {"OPEN_TERMINAL": spec})

    with pytest.raises(ValueError, match="outside the trusted recipe directory"):
        planner.recipe_path_for("OPEN_TERMINAL")
