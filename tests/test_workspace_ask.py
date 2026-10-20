"""Attach-context Q&A (D186, Highlight AI's core): answer a question grounded
on attached material, recording nothing.

Pins: the material rides the TAINTED channel (external content, scrubbed before
egress), the question rides trusted, and ask() writes nothing to the brief or
Brain -- it is a one-off query.
"""

from __future__ import annotations

import json

from ghostcursor.providers.errors import FailureKind, ProviderError
from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.session import Workspace


class AskGateway:
    def __init__(self, fail=False):
        self.fail = fail
        self.envelopes = []

    def complete(self, envelope, system, schema, parse, **kw):
        self.envelopes.append(envelope)
        if self.fail:
            raise ProviderError(FailureKind.UNAVAILABLE, "no model")
        return parse(json.dumps({"reply": "The doc says us-east-1.", "memories": []}))


def _ws(tmp_path, gw):
    brain = Brain(tmp_path / "b.sqlite")
    return Workspace("ask", gw, brain, root=tmp_path / "briefs"), brain


def test_ask_grounds_on_material_and_records_nothing(tmp_path):
    gw = AskGateway()
    ws, brain = _ws(tmp_path, gw)
    reply = ws.ask("where does prod run?", "Prod runs in us-east-1.")
    assert "us-east-1" in reply

    env = gw.envelopes[0]
    assert env.trusted.get("question")  # question is trusted (user's own)
    assert "material" in env.tainted  # attached content is tainted (scrubbed)
    assert env.trusted.get("question") == "where does prod run?"
    # nothing recorded: no brief turns, no brain memories
    assert ws.turns == ()
    assert brain.list() == []
    brain.close()


def test_ask_without_material_sends_no_tainted(tmp_path):
    gw = AskGateway()
    ws, brain = _ws(tmp_path, gw)
    ws.ask("just a question", "")
    assert gw.envelopes[0].tainted == {}
    brain.close()


def test_ask_empty_question_and_no_model(tmp_path):
    ws, brain = _ws(tmp_path, AskGateway())
    assert "ask what" in ws.ask("   ", "material")
    brain.close()

    ws2, brain2 = _ws(tmp_path, AskGateway(fail=True))
    assert "not available" in ws2.ask("q", "m")
    brain2.close()
