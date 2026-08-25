"""Deterministic Ollama request construction for bounded inference.

The model receives a JSON Schema and small generation budget.  Callers still
validate every returned field and never treat schema conformance as execution
authority.
"""
from __future__ import annotations

from typing import Any


DEFAULT_MODEL = "qwen3:4b-instruct"
DEFAULT_KEEP_ALIVE = "15m"
DEFAULT_NUM_CTX = 4096
DEFAULT_NUM_PREDICT = 96
DEFAULT_SEED = 42


def generate_body(
    *,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    num_predict: int = DEFAULT_NUM_PREDICT,
) -> dict[str, Any]:
    """Return the single supported, non-streaming bounded request shape."""
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
