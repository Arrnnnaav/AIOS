"""Bring your own account (D182): Anthropic/OpenAI/Gemini keys, tried after
Sign in with ChatGPT and before shared fallbacks; the app stores and removes
keys but never returns one."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from ghostcursor.providers import Gateway, clients, keys
from ghostcursor.providers.envelope import Envelope
from ghostcursor.providers.schemas import parse_teach_plan

PLAN = {"steps": [{"instruction": "Click Insert", "expected_change": "title_changes",
                   "action": "click", "text": ""}]}  # fmt: skip


def test_anthropic_messages_call_sends_the_key_header_and_reads_the_json():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        text = "Here you go:\n" + json.dumps(PLAN)
        return httpx.Response(200, json={"content": [{"type": "text", "text": text}],
                                         "model": "claude-x", "usage": {}})  # fmt: skip

    content, reply = clients.anthropic_json_call(
        clients.SYSTEM_TWO["anthropic"],
        "sk-ant-test",
        [{"role": "system", "content": "plan"}, {"role": "user", "content": "go"}],
        {},
        transport=httpx.MockTransport(handler),
        deadline_s=5,
        cancelled=lambda: False,
    )
    assert seen["url"].endswith("/v1/messages")
    assert seen["headers"]["x-api-key"] == "sk-ant-test"
    assert "authorization" not in seen["headers"]
    assert seen["body"]["messages"] == [{"role": "user", "content": "go"}]
    assert parse_teach_plan(content).steps[0].instruction == "Click Insert"


def test_own_accounts_come_before_shared_fallbacks(tmp_path):
    order = Gateway(log_path=tmp_path / "l").system_two
    assert order.index("chatgpt") < order.index("anthropic") < order.index("nvidia")
    assert set(clients.BYOK) <= set(order) and order[-1] == "ollama"


def test_the_gateway_plans_with_an_anthropic_key_alone(tmp_path):
    def handler(request):
        assert request.url.host == "api.anthropic.com"
        return httpx.Response(200, json={"content": [{"type": "text",
                              "text": json.dumps(PLAN)}]})  # fmt: skip

    gateway = Gateway(
        transport=httpx.MockTransport(handler),
        key_lookup=lambda name: "k" if name == "anthropic" else None,
        log_path=tmp_path / "l",
    )
    gateway.system_two = ("chatgpt", "anthropic")
    plan = gateway.plan(Envelope(task="teach", trusted={"goal": "g"}, tainted={}))
    assert plan.steps[0].action == "click"


@pytest.fixture
def vault(monkeypatch):
    store = {}
    monkeypatch.setattr(keys, "set_key", lambda n, v: store.__setitem__(n, v))
    monkeypatch.setattr(keys, "delete_key", lambda n: store.pop(n, None))
    monkeypatch.setattr(keys, "get_key", lambda n: store.get(n))
    return store


def test_the_app_saves_and_removes_keys_and_never_returns_one(vault, tmp_path):
    from ghostcursor.workspace.app import App
    from tests.test_workspace_handoff import _ws

    app = App("keys", make_workspace=lambda: _ws(tmp_path, "keys"))
    try:
        app.handle("key_set", {"name": "anthropic", "key": "sk-ant-abc123456"})
        listed = app.handle("accounts", {})
        assert listed["keys"]["anthropic"] is True
        assert "sk-ant" not in json.dumps(listed)
        for bad in ({"name": "anthropic", "key": "short"},
                    {"name": "anthropic", "key": "has space inside"},
                    {"name": "typesafe", "key": "sk-whatever-123"}):  # fmt: skip
            with pytest.raises(ValueError):
                app.handle("key_set", bad)
        app.handle("key_clear", {"name": "anthropic"})
        assert vault == {}
    finally:
        app.close()


def test_gateway_remembers_which_provider_answered(tmp_path):
    """BYOK transparency: the gateway records who answered the last request,
    and a failure does not overwrite it (so 'who powers me' stays truthful)."""

    from ghostcursor.providers.envelope import Envelope
    from ghostcursor.providers.errors import FailureKind
    from ghostcursor.providers.gateway import Gateway

    g = Gateway(log_path=tmp_path / "log.jsonl")
    env = Envelope(task="t", trusted={}, tainted={})
    assert g.last_provider is None
    reply = SimpleNamespace(
        latency_ms=1, input_tokens=1, output_tokens=1, model="m"
    )
    g._record("openai", "m", 0.0, env, reply, None)
    assert g.last_provider == "openai"
    g._record("chatgpt", "m", 0.0, env, None, FailureKind.RATE_LIMITED)
    assert g.last_provider == "openai"  # a decline must not claim it answered


def test_providers_status_shows_who_powers_the_harness():
    from ghostcursor.workspace.__main__ import providers_status

    class GW:
        last_provider = "chatgpt"

        def available(self):
            return {"chatgpt": True, "anthropic": False, "openai": True}

    out = providers_status(GW(), [])
    assert "not signed in" in out  # no real credentials in a test
    ready_line = [ln for ln in out.splitlines() if ln.startswith("Could answer")][0]
    assert "chatgpt" in ready_line and "openai" in ready_line
    assert "anthropic" not in ready_line  # not configured -> not listed
    assert "Last answered by: chatgpt" in out
