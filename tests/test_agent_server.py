"""ghostcursor.agent_server: read-only, opt-in, scrubbed, audited (rule 6)."""

import io
import json

import pytest

from ghostcursor import agent_server, audit, policy, settings
from ghostcursor.providers import parse_teach_plan
from ghostcursor.workspace import task_skills
from ghostcursor.workspace.knowledge import Knowledge


@pytest.fixture
def stores(tmp_path):
    k = Knowledge(tmp_path / "k.sqlite")
    fact = k.add_candidate("Refunds over 500 need Priya Nair, mail ada@acme.io", source="handbook", scope="default")
    k.approve(fact.fid)
    secret = k.add_candidate("Refunds for Zeus are waived", source="memo", scope="default")
    k.approve(secret.fid)
    k.classify(secret.fid, "sensitive")
    k.add_candidate("Refunds are unreviewed gossip", source="chat", scope="default")
    other = k.add_candidate("Refunds elsewhere", source="x", scope="team-b")
    k.approve(other.fid)
    plan = parse_teach_plan(
        json.dumps({"steps": [{"instruction": "Open Billing", "expected_change": "chosen_disappears"},
                              {"instruction": "Click Refund", "expected_change": "chosen_disappears"}]})
    )
    task_skills.save_skill("Issue refund", plan, dest_dir=tmp_path / "skills")
    yield {"knowledge": k, "skills_dir": tmp_path / "skills"}
    k.close()


def ask(stores, name, arguments=None, mid=1):
    reply = agent_server.handle(
        {"jsonrpc": "2.0", "id": mid, "method": "tools/call",
         "params": {"name": name, "arguments": arguments or {}}},
        **stores,
    )
    return reply["result"]["content"][0]["text"], reply["result"]["isError"]


def events():
    audit.flush()
    try:
        lines = audit.default_path().read_text().splitlines()
    except FileNotFoundError:
        return []
    return [(json.loads(x)["provider"], json.loads(x)["failure"]) for x in lines]


def test_nothing_is_shared_until_the_person_switches_it_on(stores):
    text, failed = ask(stores, "recall", {"query": "refunds"})
    assert failed and "Refunds" not in text and "off" in text
    assert events() == []  # nothing left, so nothing to record


def test_recall_shares_only_reviewed_non_sensitive_facts_of_this_scope_scrubbed(stores):
    settings.set_agent_access(True)
    settings.set_private_terms(["Priya Nair"])
    text, failed = ask(stores, "recall", {"query": "refunds"})
    assert not failed
    assert text == "- Refunds over 500 need [NAME_1], mail [EMAIL_1] (source: handbook)"
    assert events() == [("agents", None)]
    assert "refund" not in audit.default_path().read_text().casefold()  # never the question


def test_keys_never_ride_along_even_with_hiding_off(stores, monkeypatch):
    settings.set_agent_access(True)
    settings.set_redact_egress(False)
    key = "sk-" + "B" * 24
    monkeypatch.setattr(agent_server, "call", lambda *a, **k: f"mail a@b.example key {key}")
    text, _ = ask(stores, "recall", {"query": "x"})
    assert key not in text and "a@b.example" in text


def test_workflows_are_listed_and_read_never_run(stores):
    settings.set_agent_access(True)
    assert ask(stores, "list_workflows") == ("issue-refund", False)
    assert ask(stores, "get_workflow", {"name": "Issue refund"}) == (
        "1. Open Billing\n2. Click Refund", False)
    assert [t["name"] for t in agent_server.TOOLS] == ["recall", "list_workflows", "get_workflow"]
    for name, args in (("get_workflow", {"name": "missing"}), ("get_workflow", {"name": "../x"}),
                       ("get_workflow", {"name": 5}), ("recall", {"query": ""}),
                       ("recall", {"query": "a" * 501}), ("recall", {}), ("act", {}),
                       ("save_workflow", {"name": "x"}), (None, {})):
        assert ask(stores, name, args)[1] is True, (name, args)


def test_local_only_and_an_allow_list_block_it(stores, monkeypatch):
    settings.set_agent_access(True)
    settings.set_local_only(True)
    assert ask(stores, "recall", {"query": "refunds"})[1] is True
    settings.set_local_only(False)
    monkeypatch.setattr(policy, "_value", lambda name: {"AllowedProviders": "openrouter"}.get(name))
    text, failed = ask(stores, "recall", {"query": "refunds"})
    assert failed and "Refunds" not in text
    monkeypatch.setattr(policy, "_value", lambda name: {"AllowedProviders": "agents"}.get(name))
    assert ask(stores, "recall", {"query": "refunds"})[1] is False


def test_the_protocol_handshake_and_a_stream_of_lines(stores, monkeypatch):
    init = agent_server.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
    assert init["result"]["capabilities"] == {"tools": {}}
    assert agent_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert agent_server.handle({"jsonrpc": "2.0", "id": 2, "method": "nope"})["error"]["code"] == -32601
    assert agent_server.handle([1])["error"]["code"] == -32600
    out = io.StringIO()
    lines = ['{"jsonrpc":"2.0","id":1,"method":"tools/list"}', "", "not json",
             '{"jsonrpc":"2.0","id":3,"method":"ping"}']
    assert agent_server.main([], stdin=io.StringIO("\n".join(lines) + "\n"), stdout=out) == 0
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert len(replies[0]["result"]["tools"]) == 3
    assert replies[1]["error"]["code"] == -32700 and replies[2] == {"jsonrpc": "2.0", "id": 3, "result": {}}


def test_a_refused_request_is_recorded_as_refused(stores):
    settings.set_agent_access(True)
    assert ask(stores, "get_workflow", {"name": "missing"})[1] is True
    assert ask(stores, "list_workflows")[1] is False
    assert events() == [("agents", "refused"), ("agents", None)]
