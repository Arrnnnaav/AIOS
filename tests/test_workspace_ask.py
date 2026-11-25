"""Attach-context Q&A (D186, Highlight AI's core): answer a question grounded
on attached material, recording nothing.

Pins: the material rides the TAINTED channel (external content, scrubbed before
egress), the question rides trusted, and ask() writes nothing to the brief or
Brain -- it is a one-off query.
"""

from __future__ import annotations

import json

from ghostcursor import policy
from ghostcursor.providers.errors import FailureKind, ProviderError
from ghostcursor.providers.gateway import Gateway
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


def test_ask_sends_later_file_text_in_bounded_scrubbed_chunks(tmp_path):
    gw = AskGateway()
    ws, brain = _ws(tmp_path, gw)
    ws.ask("where is the marker?", "prefix " * 41 + "alice@example.com " + "middle " * 60 + "MARKER_AT_END")
    chunks = gw.envelopes[0].tainted["material"]
    combined = "".join(chunk.text for chunk in chunks)
    assert len(chunks) > 1
    assert all(len(chunk.text) <= 300 for chunk in chunks)
    assert "MARKER_AT_END" in combined
    assert "alice@example.com" not in combined
    assert "[EMAIL_1]" in combined
    assert "[EMAIL_1]" in ws.last_sent and "alice@" not in ws.last_sent  # the shown copy is scrubbed too
    brain.close()


def test_ask_redacts_enterprise_key_before_a_chunk_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "redact_egress", lambda: True)
    gw = AskGateway()
    ws, brain = _ws(tmp_path, gw)
    ws.ask("what is after the key?", "." * 295 + "sk-abcdefghijklmnop later text")
    envelope = gw.envelopes[0]
    outbound = Gateway(system_two=())._outbound(envelope.messages("system"), "openai")
    sent = json.dumps(outbound)
    assert "sk-ab" not in sent
    assert "cdefghijklmnop" not in sent
    assert "[KEY_1]" in "".join(chunk.text for chunk in envelope.tainted["material"])
    brain.close()


def test_ask_empty_question_and_no_model(tmp_path):
    ws, brain = _ws(tmp_path, AskGateway())
    assert "ask what" in ws.ask("   ", "material")
    brain.close()

    ws2, brain2 = _ws(tmp_path, AskGateway(fail=True))
    assert "no model answered" in ws2.ask("q", "m")
    brain2.close()


def test_a_long_file_sends_only_the_passages_that_match(tmp_path):
    from ghostcursor.workspace.session import relevant

    filler = "\n\n".join(f"Paragraph {i} talks about lunch menus and parking." for i in range(400))
    text = filler + "\n\nThe production database runs in eu-west-2 since March.\n\n" + filler
    picked = relevant(text, "Where does the production database run?", 8000)
    assert len(picked) <= 8000 and "eu-west-2" in picked
    assert relevant("short", "q", 8000) == "short"
    assert len(relevant("x" * 9000, "q", 8000)) <= 8000  # no spaces: hard cuts

    gw = AskGateway()
    ws, brain = _ws(tmp_path, gw)
    ws.ask("Where does the production database run?", text)
    sent = "".join(chunk.text for chunk in gw.envelopes[0].tainted["material"])
    assert "eu-west-2" in sent and len(sent) <= 8000  # same egress bound as a short file
    assert ws.last_sent.split() == " ".join(c.text for c in gw.envelopes[0].tainted["material"]).split()  # shown == sent
    brain.close()
