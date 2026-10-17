"""Transports: TypeSafe Jev (System One) and OpenAI-compatible chat (System Two).

Patterns ported, with attribution, from the separate Spatial project
(`D:\\PROJECTS\\Spatial\\server\\app\\system_one.py`): one kept-alive client per
provider, a hard time budget, at most one retry on 429/5xx inside that budget.
Only the transport is ported -- no prompt building, and no fallback to the
model's free text when a structured answer is missing.

Every call takes an injectable ``httpx`` transport so tests run on recorded
cassettes without a network or a key.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import httpx

from ghostcursor.providers.errors import FailureKind, ProviderError


@dataclass(frozen=True)
class ProviderConfig:
    name: str  # "jev", "nvidia", "openrouter", "ollama"
    base_url: str
    model: str
    key_name: str | None  # Credential Manager name; None for local Ollama
    timeout_s: float
    #: Provider-specific request fields, e.g. turning a reasoning model's
    #: thinking off: with it on, one NIM plan was noticeably slower (not benchmarked).
    extra: tuple[tuple[str, object], ...] = ()
    #: "chat" (OpenAI-compatible /chat/completions), "responses" (the
    #: streamed Responses API that Sign in with ChatGPT requires) or
    #: "anthropic" (the Messages API).
    api: str = "chat"


SYSTEM_ONE = ProviderConfig(
    "jev",
    "https://api.typesafe.ai",
    # jev-latest is the stable alias; jev-preview (1.14) is for replay comparison.
    os.environ.get("ORBYN_JEV_MODEL", "jev-latest"),
    "typesafe",
    3.0,
)
SYSTEM_TWO = {
    "nvidia": ProviderConfig(
        "nvidia",
        "https://integrate.api.nvidia.com/v1",
        "nvidia/nemotron-3-super-120b-a12b",
        "nvidia",
        45.0,
        (("chat_template_kwargs", {"enable_thinking": False}),),
    ),
    "openrouter": ProviderConfig(
        "openrouter",
        "https://openrouter.ai/api/v1",
        "qwen/qwen3-4b:free",
        "openrouter",
        45.0,
    ),
    "ollama": ProviderConfig(
        "ollama", "http://127.0.0.1:11434/v1", "qwen3:4b-instruct", None, 60.0
    ),
    # The user's own ChatGPT plan (Sign in with ChatGPT); the key is the
    # OAuth access token from ``chatgpt.access_token``. `python -m
    # ghostcursor.providers chatgpt models` lists what the account may pick.
    "chatgpt": ProviderConfig(
        "chatgpt",
        "https://api.openai.com/v1",
        os.environ.get("ORBYN_CHATGPT_MODEL", "gpt-6.1-sol"),
        "chatgpt",
        45.0,
        api="responses",
    ),
    # Bring your own key (D182): the person's own API account and credit.
    # Anthropic does not allow third-party apps to use Claude subscription
    # logins, so Anthropic is by API key. ORBYN_<NAME>_MODEL picks the model.
    "anthropic": ProviderConfig(
        "anthropic",
        "https://api.anthropic.com/v1",
        os.environ.get("ORBYN_ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        "anthropic",
        60.0,
        api="anthropic",
    ),
    "openai": ProviderConfig(
        "openai",
        "https://api.openai.com/v1",
        os.environ.get("ORBYN_OPENAI_MODEL", "gpt-6.1-sol"),
        "openai",
        45.0,
    ),
    "gemini": ProviderConfig(
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        os.environ.get("ORBYN_GEMINI_MODEL", "gemini-2.5-flash"),
        "gemini",
        45.0,
    ),
}

#: Providers a person can bring an API key for, shown in the app (D182).
BYOK = ("anthropic", "openai", "gemini", "openrouter", "nvidia")

#: Responses errors meaning the user's plan allowance is spent or paused:
#: NEEDS_USER (rate limited), never a reason to guess.
PLAN_LIMIT_CODES = frozenset(
    {
        "subscription_sharing_usage_limit_exceeded",
        "subscription_sharing_usage_unavailable",
    }
)


@dataclass(frozen=True)
class Reply:
    body: dict
    model: str | None
    latency_ms: int
    input_tokens: int
    output_tokens: int


def _status_failure(config: ProviderConfig, code: int) -> ProviderError | None:
    if code in (401, 403):
        return ProviderError(FailureKind.AUTH_FAILED, config.name)
    if code == 429:
        return ProviderError(FailureKind.RATE_LIMITED, f"{config.name}: HTTP {code}")
    if code >= 400:
        return ProviderError(FailureKind.UNAVAILABLE, f"{config.name}: HTTP {code}")
    return None


def _post(
    config: ProviderConfig,
    key: str | None,
    path: str,
    payload: dict,
    *,
    transport: httpx.BaseTransport | None,
    deadline_s: float,
    cancelled,
    extra_headers: dict | None = None,
) -> Reply:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    headers |= extra_headers or {}
    started = time.monotonic()
    deadline = started + min(deadline_s, config.timeout_s)
    with httpx.Client(
        base_url=config.base_url, transport=transport, headers=headers
    ) as client:
        for attempt in (1, 2):
            if cancelled():
                raise ProviderError(FailureKind.CANCELLED)
            remaining = deadline - time.monotonic()
            if remaining <= 0.05:
                raise ProviderError(FailureKind.TIMEOUT, config.name)
            try:
                response = client.post(path, json=payload, timeout=remaining)
            except httpx.TimeoutException as exc:
                raise ProviderError(FailureKind.TIMEOUT, config.name) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(
                    FailureKind.UNAVAILABLE, f"{config.name}: {type(exc).__name__}"
                ) from exc
            code = response.status_code
            failure = _status_failure(config, code)
            if failure is not None:
                retryable = code == 429 or code >= 500
                if retryable and attempt == 1 and deadline - time.monotonic() > 0.5:
                    time.sleep(0.2)
                    continue
                raise failure
            try:
                body = response.json()
            except ValueError as exc:
                raise ProviderError(
                    FailureKind.INVALID_OUTPUT, f"{config.name}: body is not JSON"
                ) from exc
            if not isinstance(body, dict):
                raise ProviderError(
                    FailureKind.INVALID_OUTPUT, f"{config.name}: body is not an object"
                )
            usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
            return Reply(
                body,
                body.get("model") if isinstance(body.get("model"), str) else None,
                round((time.monotonic() - started) * 1000),
                int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
                int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
            )
    raise ProviderError(FailureKind.UNAVAILABLE, config.name)


def system_one_call(
    config, key, state: dict, questions: dict, *, assets: dict | None = None, **kw
) -> tuple[dict, Reply]:
    """POST /v1/systemone; returns the ``answers`` object and the reply.
    ``assets`` (images, D179) turn on TypeSafe's image header for this call."""

    payload = {"model": config.model, "state": state, "questions": questions}
    if assets:
        payload["assets"] = assets
        kw["extra_headers"] = {"TypeSafe-Danger-Zone-Images": "true"}
    reply = _post(config, key, "/v1/systemone", payload, **kw)
    answers = reply.body.get("answers")
    if not isinstance(answers, dict):
        raise ProviderError(FailureKind.INVALID_OUTPUT, "jev: no answers object")
    return answers, reply


def chat_json_call(
    config, key, messages: list[dict], schema: dict, **kw
) -> tuple[str, Reply]:
    """OpenAI-compatible chat completion asking for a JSON object.

    Returns the assistant message CONTENT only. If the content is empty the
    call is invalid -- the reasoning text some models also return is never
    used as an answer (spec review B4).
    """

    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        **dict(config.extra),
    }
    reply = _post(config, key, "/chat/completions", payload, **kw)
    choices = reply.body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProviderError(FailureKind.INVALID_OUTPUT, f"{config.name}: no choices")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ProviderError(FailureKind.INVALID_OUTPUT, f"{config.name}: empty content")
    return content, reply


def anthropic_json_call(
    config, key, messages: list[dict], schema: dict, **kw
) -> tuple[str, Reply]:
    """Anthropic Messages API asking for a JSON object; the text content only."""

    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    payload = {
        "model": config.model,
        "max_tokens": 4096,
        "system": system + " Reply with the JSON object only.",
        "messages": [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m["role"] != "system"
        ],
        "temperature": 0,
    }
    reply = _post(
        config,
        None,
        "/messages",
        payload,
        extra_headers={"x-api-key": key or "", "anthropic-version": "2023-06-01"},
        **kw,
    )
    blocks = reply.body.get("content")
    text = "".join(
        b.get("text", "")
        for b in blocks or []
        if isinstance(b, dict) and b.get("type") == "text"
    )
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ProviderError(FailureKind.INVALID_OUTPUT, f"{config.name}: no JSON object")
    return text[start : end + 1], reply


def responses_json_call(
    config, key, messages: list[dict], schema: dict, *, transport, deadline_s, cancelled
) -> tuple[str, Reply]:
    """One streamed Responses API request asking for a JSON object.

    Sign in with ChatGPT requires ``store: false`` (nothing kept server-side)
    and ``stream: true``, and rejects system-role items and ``temperature``.
    The answer counts only after ``response.completed``; a failed, incomplete
    or truncated stream is never parsed. No retry: a retried request would be
    charged to the user's plan twice.
    """

    instructions = "\n".join(m["content"] for m in messages if m["role"] == "system")
    payload = {
        "model": config.model,
        "instructions": instructions,
        "input": [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m["role"] != "system"
        ],
        **dict(config.extra),
        "store": False,
        "stream": True,
    }
    started = time.monotonic()
    deadline = started + min(deadline_s, config.timeout_s)
    parts: list[str] = []
    if cancelled():
        raise ProviderError(FailureKind.CANCELLED)
    with httpx.Client(
        base_url=config.base_url,
        transport=transport,
        headers={"Authorization": f"Bearer {key}"},
    ) as client:
        try:
            with client.stream(
                "POST", "/responses", json=payload, timeout=deadline - started
            ) as response:
                failure = _status_failure(config, response.status_code)
                if failure is not None:
                    response.read()
                    raise _plan_limit_in(config, response) or failure
                for line in response.iter_lines():
                    if cancelled():
                        raise ProviderError(FailureKind.CANCELLED)
                    if time.monotonic() > deadline:
                        raise ProviderError(FailureKind.TIMEOUT, config.name)
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except ValueError:
                        continue  # e.g. a "[DONE]" sentinel
                    if not isinstance(event, dict):
                        continue
                    kind = event.get("type")
                    if kind == "response.output_text.delta":
                        if isinstance(event.get("delta"), str):
                            parts.append(event["delta"])
                    elif kind == "response.completed":
                        body = event.get("response")
                        body = body if isinstance(body, dict) else {}
                        return _completed(config, body, "".join(parts), started)
                    elif kind in ("response.failed", "error"):
                        raise _stream_failure(config, event)
                    elif kind == "response.incomplete":
                        raise ProviderError(
                            FailureKind.INVALID_OUTPUT, f"{config.name}: incomplete"
                        )
        except httpx.TimeoutException as exc:
            raise ProviderError(FailureKind.TIMEOUT, config.name) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                FailureKind.UNAVAILABLE, f"{config.name}: {type(exc).__name__}"
            ) from exc
    raise ProviderError(FailureKind.INVALID_OUTPUT, f"{config.name}: stream ended early")


def _completed(config, body: dict, content: str, started: float) -> tuple[str, Reply]:
    if not content.strip():
        raise ProviderError(FailureKind.INVALID_OUTPUT, f"{config.name}: empty content")
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    return content, Reply(
        body,
        body.get("model") if isinstance(body.get("model"), str) else None,
        round((time.monotonic() - started) * 1000),
        int(usage.get("input_tokens") or 0),
        int(usage.get("output_tokens") or 0),
    )


def _plan_limit_in(config, response) -> ProviderError | None:
    """A spent plan reported as a plain HTTP error rather than in the stream."""

    try:
        body = response.json()
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and error.get("code") in PLAN_LIMIT_CODES:
        return ProviderError(FailureKind.RATE_LIMITED, f"{config.name}: {error['code']}")
    return None


def _stream_failure(config, event: dict) -> ProviderError:
    response = event.get("response") if isinstance(event.get("response"), dict) else {}
    error = response.get("error") or event.get("error") or event
    code = error.get("code") if isinstance(error, dict) else None
    if code in PLAN_LIMIT_CODES:
        return ProviderError(FailureKind.RATE_LIMITED, f"{config.name}: {code}")
    return ProviderError(
        FailureKind.UNAVAILABLE, f"{config.name}: {code or 'response failed'}"
    )
