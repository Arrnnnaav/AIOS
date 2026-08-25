"""One bounded Ollama transport for every GhostCursor inference path.

The model receives a JSON Schema and small generation budget.  Callers still
validate every returned field and never treat schema conformance as execution
authority.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_MODEL = "qwen3:4b-instruct"
DEFAULT_KEEP_ALIVE = "15m"
DEFAULT_NUM_CTX = 4096
DEFAULT_NUM_PREDICT = 96
DEFAULT_SEED = 42


@dataclass(frozen=True)
class GenerateResponse:
    """Model payload plus generation metadata needed by evaluation."""

    payload: object
    done_reason: str | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None
    total_duration: int | None = None
    load_duration: int | None = None
    prompt_eval_duration: int | None = None
    eval_duration: int | None = None

    @property
    def hit_generation_limit(self) -> bool:
        return self.done_reason == "length"


def generate_body(
    *,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    num_predict: int = DEFAULT_NUM_PREDICT,
) -> dict[str, Any]:
    """Return the single supported, non-streaming bounded request shape."""
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("prompt must be a non-empty string")
    if not isinstance(schema, dict) or not schema:
        raise ValueError("schema must be a non-empty object")
    if isinstance(num_predict, bool) or not isinstance(num_predict, int) or num_predict <= 0:
        raise ValueError("num_predict must be a positive integer")
    return {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "keep_alive": DEFAULT_KEEP_ALIVE,
        "format": schema,
        "options": {
            "temperature": 0,
            "seed": DEFAULT_SEED,
            "num_ctx": DEFAULT_NUM_CTX,
            "num_predict": num_predict,
        },
    }


def generate_structured(
    *,
    endpoint: str,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    timeout: float,
    num_predict: int = DEFAULT_NUM_PREDICT,
) -> GenerateResponse:
    """Make the one supported Ollama request; never retry or interpret fields."""
    body = generate_body(model=model, prompt=prompt, schema=schema, num_predict=num_predict)
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/api/generate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        outer = json.loads(response.read().decode("utf-8"))
    if not isinstance(outer, dict):
        raise ValueError("Ollama response envelope was not an object")
    return GenerateResponse(
        payload=outer.get("response", outer),
        done_reason=_optional_str(outer.get("done_reason")),
        prompt_eval_count=_optional_int(outer.get("prompt_eval_count")),
        eval_count=_optional_int(outer.get("eval_count")),
        total_duration=_optional_int(outer.get("total_duration")),
        load_duration=_optional_int(outer.get("load_duration")),
        prompt_eval_duration=_optional_int(outer.get("prompt_eval_duration")),
        eval_duration=_optional_int(outer.get("eval_duration")),
    )


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None
