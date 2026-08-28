"""Planner policy tests for the schema-v2 authority."""
import json
import pytest
from ghostcursor.reasoning import planner
from ghostcursor.reasoning.planner import IntentDecision, PlanStatus

class _Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return json.dumps(self.payload).encode()

def test_ollama_request_is_schema_constrained(monkeypatch):
    captured = {}
    def urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return _Response({"response": json.dumps({"intent_id":"OPEN_FOLDER", "confidence":0.98, "explanation":"matched"})})
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = planner._model_intent("Open a folder in VS Code", "http://test", "m", 7.0)
    assert result.intent_id == "OPEN_FOLDER"
    body = captured["body"]
    assert body["stream"] is False and body["think"] is False
    assert body["options"]["temperature"] == 0
    assert body["format"]["additionalProperties"] is False
    assert set(body["format"]["properties"]["intent_id"]["enum"]) == {None, *planner.compiled_registry()}
    assert captured["timeout"] == 7.0

def test_model_rejects_out_of_range_confidence(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Response({"response": json.dumps({"intent_id":"OPEN_FOLDER", "confidence":1.2, "explanation":"bad"})}))
    with pytest.raises(ValueError, match="confidence"):
        planner._model_intent("Open a folder in VS Code", "http://test", "m", 7.0)

def test_oversized_goal_never_contacts_model(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("model called"))
    with pytest.raises(ValueError, match="1024"):
        planner.infer_intent("x" * 1025, "http://test", "m", 7.0)

def test_exact_goal_is_classified_without_recipe_loading():
    result = planner.resolve_model_decision("Export this table as CSV", IntentDecision("EXPORT_DATA", .95, "exact"))
    assert result.status is PlanStatus.SUPPORTED and result.intent_id == "EXPORT_DATA"

def test_unavailable_registered_intent_is_fail_closed():
    result = planner.resolve_model_decision("open settings", IntentDecision("OPEN_SETTINGS", .9, "settings"))
    assert result.status is PlanStatus.KNOWN_INTENT_RECIPE_UNAVAILABLE

def test_model_abstention_uses_trusted_fallback():
    result = planner.resolve_model_decision("open a folder in VS Code", IntentDecision(None, .8, "uncertain"))
    assert result.status is PlanStatus.MODEL_ABSTAINED_FALLBACK and result.intent_id == "OPEN_FOLDER"

def test_model_cannot_ground_an_unrelated_goal():
    result = planner.resolve_model_decision("Deploy this project", IntentDecision("EXPORT_DATA", .98, "wrong"))
    assert result.status is PlanStatus.UNSUPPORTED_GOAL and result.intent_id is None

def test_unmatched_goal_is_unsupported():
    result = planner.resolve_model_decision("rearrange my desktop wallpaper", IntentDecision(None, .8, "none"))
    assert result.status is PlanStatus.UNSUPPORTED_GOAL and result.intent_id is None

def test_compiled_registry_contains_v2_specs():
    specs = planner.compiled_registry()
    assert {"EXPORT_DATA", "OPEN_FOLDER", "OPEN_TERMINAL"} <= set(specs)
    assert specs["CREATE_DOCUMENT"].recipe_path is None
    assert specs["OPEN_SETTINGS"].recipe_path is None
    assert specs["EXPORT_DATA"].recipe_path is not None
