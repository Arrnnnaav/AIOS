import json

from ghostcursor.inference.screen_hint import decide_next_hint
from ghostcursor.perception.uia import Element


ELEMENTS = [
    Element("Export", "Button", "1005", (0, 0, 1, 1)),
    Element("Wrong control", "Button", "1006", (0, 0, 1, 1)),
]


def test_hint_request_schema_contains_only_observed_recipe_approved_ids(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"response": json.dumps({
                "automation_id": "1005",
                "confidence": 0.91,
                "explanation": "Export advances the goal",
            })}).encode()

    def urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    result = decide_next_hint(
        "Export this table as CSV", ELEMENTS, ("Export",), model="test-model", timeout=8.0
    )

    assert result.source == "model"
    body = captured["body"]
    assert body["think"] is False
    assert body["keep_alive"] == "15m"
    assert body["options"] == {
        "temperature": 0,
        "seed": 42,
        "num_ctx": 4096,
        "num_predict": 96,
    }
    assert body["format"]["properties"]["automation_id"]["enum"] == ["1005"]
    assert "1006" not in body["format"]["properties"]["automation_id"]["enum"]
    assert captured["timeout"] == 8.0


def test_hint_skips_model_when_no_observed_recipe_approved_id(monkeypatch):
    def unexpected_call(*args, **kwargs):
        raise AssertionError("Ollama should not be called without an eligible observed ID")

    monkeypatch.setattr("urllib.request.urlopen", unexpected_call)

    result = decide_next_hint(
        "Export this table as CSV", ELEMENTS, ("Missing trusted target",)
    )

    assert result.automation_id is None
    assert result.source == "fallback"


def test_fallback_selects_only_the_trusted_observed_target():
    result = decide_next_hint("Export this table as CSV", ELEMENTS, ("Export",), use_model=False)
    assert result.automation_id == "1005"
    assert result.source == "fallback"


def test_model_selection_is_bounded_to_allowed_names(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"response": json.dumps({
                "automation_id": "1005",
                "confidence": 0.91,
                "explanation": "Export advances the goal",
            })}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    result = decide_next_hint("Export this table as CSV", ELEMENTS, ("Export",))
    assert result.automation_id == "1005"
    assert result.source == "model"


def test_model_cannot_select_an_observed_but_untrusted_control(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"response": json.dumps({
                "automation_id": "1006",
                "confidence": 0.99,
                "explanation": "wrong",
            })}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    result = decide_next_hint("Export this table as CSV", ELEMENTS, ("Export",))
    assert result.automation_id == "1005"
    assert result.source == "invalid-model"


def test_qwen_aliases_and_string_confidence_are_normalized(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"response": "<think>choose export</think>" + json.dumps({
                "target_automation_id": 1005,
                "confidence": "0.9",
                "reason": "the export control advances the goal",
            })}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    result = decide_next_hint("Export this table as CSV", ELEMENTS, ("Export",))
    assert result.automation_id == "1005"


def test_qwen_reasoning_object_does_not_get_joined_to_final_object(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "response": (
                    '<think>The example is {"automation_id":"1006"}. '
                    "The observed Export button advances the goal.</think>\n"
                    '{"automation_id":"1005","confidence":0.91,'
                    '"explanation":"selected the Export button"}'
                )
            }).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    result = decide_next_hint("export the table", ELEMENTS, ("Export",))

    assert result.source == "model"
    assert result.automation_id == "1005"


def test_qwen_qualitative_confidence_is_normalized(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "response": json.dumps({
                    "automation_id": "1005",
                    "confidence": "high",
                    "explanation": "the Export button matches the goal",
                })
            }).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    result = decide_next_hint("export the table", ELEMENTS, ("Export",))

    assert result.source == "model"
    assert result.automation_id == "1005"
    assert result.confidence == 0.95
