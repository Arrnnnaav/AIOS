"""Bring your own account (D182): Anthropic/OpenAI/Gemini keys, tried after
Sign in with ChatGPT and before shared fallbacks; the app stores and removes
keys but never returns one."""

from __future__ import annotations

import json

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
