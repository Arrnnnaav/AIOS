import json

import pytest

from ghostcursor.inference.ollama import generate_body, generate_structured


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _schema():
    return {"type": "object", "properties": {}, "additionalProperties": False}


def test_generate_body_has_one_bounded_request_contract():
    body = generate_body(model="m", prompt="p", schema=_schema(), num_predict=128)
    assert body == {
        "model": "m", "prompt": "p", "stream": False, "think": False,
        "keep_alive": "15m", "format": _schema(),
        "options": {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 128},
    }


@pytest.mark.parametrize("num_predict", [0, -1, True, 1.5])
def test_generate_body_rejects_invalid_generation_budgets(num_predict):
    with pytest.raises(ValueError, match="positive integer"):
        generate_body(model="m", prompt="p", schema=_schema(), num_predict=num_predict)


def test_generate_structured_preserves_limit_and_timing_metadata(monkeypatch):
    captured = {}

    def urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _Response({
            "response": {"ok": True}, "done_reason": "length",
            "prompt_eval_count": 10, "eval_count": 96, "total_duration": 1000,
            "load_duration": 200, "prompt_eval_duration": 300, "eval_duration": 500,
        })

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    result = generate_structured(
        endpoint="http://127.0.0.1:11434/", model="m", prompt="p",
        schema=_schema(), timeout=7.0,
    )
    assert result.payload == {"ok": True}
    assert result.hit_generation_limit is True
    assert result.eval_count == 96
    assert result.total_duration == 1000
    assert captured["timeout"] == 7.0
    assert captured["body"]["stream"] is False


def test_generate_structured_rejects_non_object_envelope(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *args, **kwargs: _Response(["not", "an", "object"])
    )
    with pytest.raises(ValueError, match="envelope"):
        generate_structured(
            endpoint="http://127.0.0.1:11434", model="m", prompt="p",
            schema=_schema(), timeout=7.0,
        )
