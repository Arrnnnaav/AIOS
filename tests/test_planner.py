import json

import pytest

from ghostcursor.reasoning import planner
from ghostcursor.reasoning.planner import IntentDecision, PlanStatus, plan_goal


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_ollama_intent_request_is_schema_constrained_and_deterministic(monkeypatch):
    captured = {}
    def urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return _Response({"response": json.dumps({
            "intent_id": "OPEN_FOLDER", "confidence": 0.98,
            "explanation": "matched the folder goal",
        })})
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = planner._model_intent(
        "Open a folder in VS Code", "http://127.0.0.1:11434", "test-model", 7.0
    )
    assert result.intent_id == "OPEN_FOLDER"
    body = captured["body"]
    assert body["stream"] is False and body["think"] is False
    assert body["options"]["temperature"] == 0
    assert set(body["format"]["properties"]["intent_id"]["enum"]) == {
        None, *planner.compiled_registry()
    }
    assert body["format"]["additionalProperties"] is False
    assert captured["timeout"] == 7.0
def test_model_intent_rejects_schema_bypassing_out_of_range_confidence(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _Response({
            "response": json.dumps({
                "intent_id": "OPEN_FOLDER",
                "confidence": 1.2,
                "explanation": "too confident",
            })
        }),
    )

    with pytest.raises(ValueError, match="confidence"):
        planner._model_intent(
            "Open a folder in VS Code", "http://127.0.0.1:11434", "test-model", 7.0
        )


def test_model_intent_accepts_required_nullable_intent(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _Response({
            "response": json.dumps({
                "intent_id": None,
                "confidence": 0.8,
                "explanation": "none of the registered intents fits",
            })
        }),
    )

    decision = planner._model_intent(
        "Deploy this project", "http://127.0.0.1:11434", "test-model", 7.0
    )

    assert decision.intent_id is None


def test_model_intent_rejects_alias_or_extra_fields(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: _Response({
            "response": json.dumps({
                "intent_id": "OPEN_FOLDER",
                "confidence": 0.9,
                "explanation": "folder",
                "reason": "extra alias",
            })
        }),
    )

    with pytest.raises(ValueError, match="exact planner fields"):
        planner._model_intent(
            "Open a folder in VS Code", "http://127.0.0.1:11434", "test-model", 7.0
        )


def test_oversized_goal_never_contacts_ollama(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Ollama called")),
    )
    result = plan_goal("x" * 1025)
    assert result.status is PlanStatus.UNSUPPORTED_GOAL
    assert result.plan is None


def test_exact_export_goal_is_supported_without_model():
    intent, confidence, _ = planner.deterministic_intent("Export this table as CSV")
    assert (intent, confidence) == ("EXPORT_DATA", 0.95)
def test_synonym_uses_deterministic_fallback():
    intent, confidence, _ = planner.deterministic_intent("save the table as a spreadsheet")
    assert (intent, confidence) == ("EXPORT_DATA", 0.85)
def test_unmatched_goal_is_explicitly_unsupported():
    result = plan_goal("rearrange my desktop wallpaper", use_model=False)
    assert result.status is PlanStatus.UNSUPPORTED_GOAL
    assert result.plan is None


def test_valid_unavailable_model_intent_is_not_fallback(monkeypatch):
    monkeypatch.setattr(
        "ghostcursor.reasoning.planner._model_intent",
        lambda *args: IntentDecision("OPEN_SETTINGS", 0.9, "settings"),
    )
    result = plan_goal("open settings")
    assert result.status is PlanStatus.KNOWN_INTENT_RECIPE_UNAVAILABLE
    assert result.plan is None


def test_malformed_model_output_keeps_a_valid_fallback():
    with pytest.raises(ValueError):
        planner.parse_intent_decision({"bad": "shape"}, tuple(planner.compiled_registry()))
    assert planner.deterministic_intent("Export this table as CSV")[:2] == ("EXPORT_DATA", 0.95)
def test_malformed_model_output_without_fallback_is_unsupported(monkeypatch):
    monkeypatch.setattr(
        "ghostcursor.reasoning.planner._model_intent",
        lambda *args: (_ for _ in ()).throw(ValueError("bad JSON")),
    )

    result = plan_goal("Deploy this project to production")

    assert result.status is PlanStatus.UNSUPPORTED_GOAL
    assert result.intent_id is None
    assert result.plan is None


def test_unavailable_model_without_fallback_is_unsupported(monkeypatch):
    monkeypatch.setattr(
        "ghostcursor.reasoning.planner._model_intent",
        lambda *args: (_ for _ in ()).throw(TimeoutError("offline")),
    )

    result = plan_goal("Deploy this project to production")

    assert result.status is PlanStatus.UNSUPPORTED_GOAL
    assert result.intent_id is None
    assert result.plan is None


def test_model_cannot_attach_an_ungrounded_executable_intent(monkeypatch):
    monkeypatch.setattr(
        "ghostcursor.reasoning.planner._model_intent",
        lambda *args: IntentDecision("EXPORT_DATA", 0.98, "deployment needs an export"),
    )

    result = plan_goal("Deploy this project to production")

    assert result.status is PlanStatus.UNSUPPORTED_GOAL
    assert result.intent_id is None
    assert result.plan is None


def test_model_intent_mismatch_uses_distinguishable_trusted_fallback():
    result = planner.resolve_model_decision(
        "Open a folder in VS Code",
        IntentDecision("EXPORT_DATA", 0.98, "incorrect model route"),
    )
    assert result.status is PlanStatus.INVALID_MODEL_OUTPUT
    assert result.intent_id == "OPEN_FOLDER"
def test_valid_model_abstention_uses_explicit_trusted_fallback_status():
    result = planner.resolve_model_decision(
        "Open a folder in VS Code", IntentDecision(None, 0.8, "uncertain")
    )
    assert result.status is PlanStatus.MODEL_ABSTAINED_FALLBACK
    assert result.intent_id == "OPEN_FOLDER"
def test_valid_model_abstention_without_fallback_is_unsupported(monkeypatch):
    monkeypatch.setattr(
        "ghostcursor.reasoning.planner._model_intent",
        lambda *args: IntentDecision(None, 0.8, "none fits"),
    )

    result = plan_goal("Deploy this project to production")

    assert result.status is PlanStatus.UNSUPPORTED_GOAL
    assert result.intent_id is None
    assert result.plan is None


@pytest.mark.parametrize(
    ("goal", "intent_id", "recipe_intent"),
    [
        ("Open a folder in VS Code", "OPEN_FOLDER", "open a folder in vscode"),
        (
            "Open the integrated terminal in VS Code",
            "OPEN_TERMINAL",
            "open the integrated terminal in vscode",
        ),
    ],
)
def test_matching_available_model_intent_keeps_its_trusted_plan(
    goal, intent_id, recipe_intent
):
    result = planner.resolve_model_decision(
        goal, IntentDecision(intent_id, 0.98, "matching model route")
    )
    assert result.status is PlanStatus.SUPPORTED
    assert result.intent_id == intent_id
    assert result.confidence == 0.98
def test_fallback_recognizes_vscode_open_folder_goal():
    result = planner.deterministic_intent(r"Open C:\Projects\Customer-Portal in VS Code")
    assert result[:2] == ("OPEN_FOLDER", 0.85)
def test_exact_cli_vscode_goal_is_a_strong_deterministic_match():
    result = planner.deterministic_intent("Open a folder in VS Code")
    assert result[:2] == ("OPEN_FOLDER", 0.95)
def test_exact_cli_vscode_goal_survives_unavailable_model(monkeypatch):
    monkeypatch.setattr(
        "ghostcursor.reasoning.planner._model_intent",
        lambda *args: (_ for _ in ()).throw(TimeoutError("unavailable")),
    )
    with pytest.raises(TimeoutError):
        planner._model_intent("Open a folder in VS Code", "x", "m", 1.0)
    assert planner.deterministic_intent("Open a folder in VS Code")[:2] == ("OPEN_FOLDER", 0.95)
def test_exact_vscode_terminal_goal_is_supported_without_model():
    assert planner.deterministic_intent(
        "Open the integrated terminal in VS Code"
    )[:2] == ("OPEN_TERMINAL", 0.95)
def test_vscode_terminal_goal_survives_unavailable_model(monkeypatch):
    monkeypatch.setattr(
        "ghostcursor.reasoning.planner._model_intent",
        lambda *args: (_ for _ in ()).throw(TimeoutError("unavailable")),
    )
    with pytest.raises(TimeoutError):
        planner._model_intent("Open the integrated terminal in VS Code", "x", "m", 1.0)
    assert planner.deterministic_intent(
        "Open the integrated terminal in VS Code"
    )[:2] == ("OPEN_TERMINAL", 0.95)
def test_goal_planner_rejects_a_registered_recipe_outside_trusted_roots():
    root = planner._ROOT.parent.parent.resolve()
    for spec in planner.compiled_registry().values():
        if spec.recipe_path is not None:
            assert root in spec.recipe_path.resolve().parents
def test_production_planning_consults_the_compiled_matcher(monkeypatch):
    from ghostcursor.packs import compile as packs_compile
    def marker(*args, **kwargs):
        raise AssertionError("compiled matcher reached")
    monkeypatch.setattr(packs_compile, "compile_matcher", marker)
    with pytest.raises(AssertionError, match="compiled matcher reached"):
        planner.deterministic_intent("Open a folder in VS Code")
def test_compiled_registry_is_the_execution_authority():
    specs = planner.compiled_registry()
    assert set(specs) == {
        "EXPORT_DATA", "CREATE_DOCUMENT", "OPEN_SETTINGS",
        "OPEN_FOLDER", "OPEN_TERMINAL",
    }
    assert specs["CREATE_DOCUMENT"].recipe_path is None
    assert specs["OPEN_SETTINGS"].recipe_path is None
    assert specs["OPEN_FOLDER"].recipe_path is not None
