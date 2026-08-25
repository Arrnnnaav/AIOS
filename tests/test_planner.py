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
        return _Response({
            "response": json.dumps({
                "intent_id": "OPEN_FOLDER",
                "confidence": 0.98,
                "explanation": "matched the folder goal",
            })
        })

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    result = planner._model_intent(
        "Open a folder in VS Code", "http://127.0.0.1:11434", "test-model", 7.0
    )

    assert result.intent_id == "OPEN_FOLDER"
    body = captured["body"]
    assert body["model"] == "test-model"
    assert body["stream"] is False
    assert body["think"] is False
    assert body["keep_alive"] == "15m"
    assert body["options"] == {
        "temperature": 0,
        "seed": 42,
        "num_ctx": 4096,
        "num_predict": 128,
    }
    assert set(body["format"]["properties"]["intent_id"]["enum"]) == {
        None, *planner.registry()
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
        lambda *args: IntentDecision("OPEN_SETTINGS", 0.9, "settings"),
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


def test_model_intent_mismatch_uses_distinguishable_trusted_fallback(monkeypatch):
    monkeypatch.setattr(
        "ghostcursor.reasoning.planner._model_intent",
        lambda *args: IntentDecision("EXPORT_DATA", 0.98, "incorrect model route"),
    )

    result = plan_goal("Open a folder in VS Code")

    assert result.status is PlanStatus.INVALID_MODEL_OUTPUT
    assert result.intent_id == "OPEN_FOLDER"
    assert result.plan is not None
    assert result.plan.app_id == "code.exe"


def test_valid_model_abstention_uses_explicit_trusted_fallback_status(monkeypatch):
    monkeypatch.setattr(
        "ghostcursor.reasoning.planner._model_intent",
        lambda *args: IntentDecision(None, 0.8, "uncertain"),
    )

    result = plan_goal("Open a folder in VS Code")

    assert result.status is PlanStatus.MODEL_ABSTAINED_FALLBACK
    assert result.intent_id == "OPEN_FOLDER"
    assert result.plan is not None


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
    monkeypatch, goal, intent_id, recipe_intent
):
    monkeypatch.setattr(
        "ghostcursor.reasoning.planner._model_intent",
        lambda *args: IntentDecision(intent_id, 0.98, "matching model route"),
    )

    result = plan_goal(goal)

    assert result.status is PlanStatus.SUPPORTED
    assert result.intent_id == intent_id
    assert result.confidence == 0.98
    assert result.plan is not None
    assert result.plan.intent == recipe_intent


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
