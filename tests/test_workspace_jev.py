"""Jev in the workspace (owner build order 3): one request per message gives a
suggestion (never acted on) and a verdict per memory candidate that can only
lower it; without Jev nothing changes."""

from __future__ import annotations

import pytest

from ghostcursor.providers.errors import FailureKind, ProviderError
from ghostcursor.providers.schemas import Choice
from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.session import Workspace
from tests.test_workspace_session import FakeGateway

STATED = [
    {"kind": "preference", "text": "prefers dark slides", "confidence": 0.9},
    {"kind": "goal", "text": "wants the deck by Friday", "confidence": 0.9},
    {"kind": "fact", "text": "bank login is hunter2", "confidence": 0.9},
]
MESSAGE = "I prefer dark slides and want the deck by Friday; my bank login is hunter2"


class JevGateway(FakeGateway):
    def __init__(self, verdicts, **kw):
        super().__init__(memories=STATED, **kw)
        self.verdicts, self.judged = verdicts, []

    def judge(self, envelope, questions, **kw):
        self.judged.append((envelope, questions))
        if isinstance(self.verdicts, Exception):
            raise self.verdicts
        return {
            q: Choice(*self.verdicts.get(q, ("lasting", {"lasting": 0.5})))
            for q in questions
        }


def _ws(tmp_path, gateway):
    return Workspace("deck", gateway, Brain(tmp_path / "b.sqlite"), root=tmp_path / "r")


def test_one_request_suggests_and_only_lowers_memories(tmp_path):
    gateway = JevGateway(
        {
            "route": ("research", {"research": 0.9}),
            "memory_0": ("lasting", {"lasting": 0.95}),
            "memory_1": ("temporary", {"temporary": 0.85}),
            "memory_2": ("secret", {"secret": 0.9}),
        }
    )
    ws = _ws(tmp_path, gateway)
    ws.discuss(MESSAGE)
    # The suggestion is asked alongside the reply; the memories after it.
    assert ws.suggestion == "research" and len(gateway.judged) == 2
    asked = {frozenset(q): envelope for envelope, q in gateway.judged}
    assert set(asked) == {frozenset({"route"}), frozenset({"memory_0", "memory_1", "memory_2"})}
    assert all(e.trusted == {"message": MESSAGE} for e in asked.values())
    scopes = {m.text: m.scope for m in ws.brain.list()}
    assert scopes == {
        "prefers dark slides": "durable",
        "wants the deck by Friday": "session",
    }


def test_unsure_verdicts_change_nothing_and_chat_is_no_suggestion(tmp_path):
    gateway = JevGateway(
        {
            "route": ("chat", {"chat": 0.99}),
            "memory_1": ("temporary", {"temporary": 0.6}),
            "memory_2": ("secret", {"secret": 0.7}),
        }
    )
    ws = _ws(tmp_path, gateway)
    ws.discuss(MESSAGE)
    assert ws.suggestion == ""
    # the deterministic rule alone refuses the login; the rest stays
    assert {m.text for m in ws.brain.list()} == {
        "prefers dark slides",
        "wants the deck by Friday",
    }


@pytest.mark.parametrize(
    "gateway",
    [
        FakeGateway(memories=STATED),
        JevGateway(ProviderError(FailureKind.NOT_CONFIGURED)),
    ],
)
def test_without_jev_the_rule_alone_decides(tmp_path, gateway):
    ws = _ws(tmp_path, gateway)
    ws.discuss(MESSAGE)
    assert ws.suggestion == ""
    assert {m.text: m.scope for m in ws.brain.list()}[
        "prefers dark slides"
    ] == "durable"


def test_a_message_with_nothing_to_remember_asks_jev_once(tmp_path):
    gateway = JevGateway({"route": ("plan", {"plan": 0.9})})
    gateway.memories = []
    ws = _ws(tmp_path, gateway)
    ws.discuss("how do I add a slide?")
    assert ws.suggestion == "plan" and [set(q) for _, q in gateway.judged] == [{"route"}]


def test_the_suggestion_is_asked_while_the_reply_is_written(tmp_path):
    import threading

    started = threading.Event()

    class Slow(JevGateway):
        def complete(self, *a, **kw):
            assert started.wait(2), "Jev was not asked before the reply finished"
            return super().complete(*a, **kw)

        def judge(self, envelope, questions, **kw):
            started.set()
            return super().judge(envelope, questions, **kw)

    gateway = Slow({"route": ("research", {"research": 0.9})})
    gateway.memories = []
    ws = _ws(tmp_path, gateway)
    ws.discuss("find me the latest numbers")
    assert ws.suggestion == "research"
