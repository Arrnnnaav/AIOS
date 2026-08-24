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
