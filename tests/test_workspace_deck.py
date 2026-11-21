"""Deck planning (D186): a goal -> a reviewable DeckSpec, grounded in the
owner's reviewed Company Brain facts, built from the first System-Two provider
that answers validly. Hermetic: an injected MockTransport plays the reply."""

from __future__ import annotations

import json

import httpx

from ghostcursor.providers import Gateway, SlideLayout
from ghostcursor.workspace.deck import plan_deck
from ghostcursor.workspace.knowledge import Knowledge

DECK = {
    "title": "Platform Review",
    "slides": [
        {"title": "Platform Review", "bullets": [], "layout": "title"},
        {
            "title": "Where we run",
            "bullets": ["Prod is in us-east-1"],
            "layout": "bullets",
        },
    ],
}


def _transport(capture):
    def handler(request):
        capture.append(request)
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [{"message": {"content": json.dumps(DECK)}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 7},
            },
        )

    return httpx.MockTransport(handler)


def _gateway(capture, **kw):
    return Gateway(
        system_two=("openrouter",),
        transport=_transport(capture),
        key_lookup=lambda name: "k" if name == "openrouter" else None,
        **kw,
    )


def test_plan_deck_returns_a_closed_deck_spec(tmp_path):
    calls = []
    gw = _gateway(calls, log_path=tmp_path / "l")
    deck = plan_deck(gw, "review the platform")
    assert deck.title == "Platform Review" and len(deck.slides) == 2
    assert deck.slides[0].layout is SlideLayout.TITLE


def test_plan_deck_grounds_in_reviewed_brain_facts(tmp_path):
    kb = Knowledge(tmp_path / "k.sqlite")
    f = kb.add_candidate("Prod runs in us-east-1.", source="runbook", scope="acme")
    kb.approve(f.fid)
    secret = kb.add_candidate(
        "Root password is hunter2.",
        source="vault",
        scope="acme",
        sensitivity="sensitive",
    )
    kb.approve(secret.fid)

    calls = []
    gw = _gateway(calls, log_path=tmp_path / "l")
    # goal shares a stem with the fact so BM25 recall surfaces it as grounding
    plan_deck(gw, "where does prod run", scope="acme", knowledge=kb)

    body = calls[0].content.decode()
    assert "us-east-1" in body  # reviewed fact is grounding
    # DLP leaves this sentence intact, so the assertion tests recall's exclusion.
    assert "hunter2" not in body  # sensitive fact never reaches the model path
    kb.close()


def test_plan_deck_rejects_an_empty_goal(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        plan_deck(_gateway([], log_path=tmp_path / "l"), "   ")


def test_research_deck_grounds_the_deck_in_cited_research_claims(tmp_path):
    """#5 chain: research the topic -> plan a deck grounded on the cited claims
    (not recall, so a fresh run needs no prior review), and file the claims to
    the Brain as candidates. The gateway answers three schemas: plan, claims,
    deck."""
    from ghostcursor.workspace.deck import research_deck
    from ghostcursor.workspace.knowledge import Knowledge

    CLAIMS = {
        "claims": [
            {
                "text": "Prod runs in us-east-1.",
                "status": "supported",
                "evidence": ["p1"],
            }
        ]
    }
    HITS = [
        {
            "url": "https://docs.example.com/a",
            "title": "A",
            "passages": ["Prod runs in us-east-1 with three replicas."],
        }
    ]

    class ThreeSchemaGateway:
        def __init__(self):
            self.grounding_seen = None

        def complete(self, envelope, system, schema, parse, **kw):
            props = schema.get("properties", {})
            if "subquestions" in props:
                return parse(json.dumps({"subquestions": ["where does prod run"]}))
            if "claims" in props:
                return parse(json.dumps(CLAIMS))
            # deck schema: capture the grounding the deck was given
            assert "grounding" not in envelope.trusted  # web-derived: data, not instruction
            self.grounding_seen = [c.text for c in envelope.tainted.get("grounding", [])]
            return parse(json.dumps(DECK))

    kb = Knowledge(tmp_path / "k.sqlite")
    gw = ThreeSchemaGateway()
    deck, report = research_deck(
        gw,
        "how does prod run",
        knowledge=kb,
        scope="acme",
        search=lambda q: HITS,
        key_lookup=lambda n: None,
        trace_path=tmp_path / "t.jsonl",
    )
    assert deck.title == "Platform Review"  # a deck came back
    # the deck was grounded on the cited research claim, sourced to the page
    assert gw.grounding_seen and "Prod runs in us-east-1." in gw.grounding_seen[0]
    assert "docs.example.com" in gw.grounding_seen[0]
    # and the claim was filed into the Brain as a reviewable candidate
    assert report.filed_to_brain == 1
    assert (
        kb.list(scope="acme", status="candidate")[0].text == "Prod runs in us-east-1."
    )
    kb.close()


def test_build_brief_renders_every_slide_in_order():
    """The DeckSpec -> Act bridge: a plain-string build goal the existing Teach/
    Act loop runs. Data only -- it names what to build, not which control."""

    from ghostcursor.providers import DeckSpec, Slide, SlideLayout
    from ghostcursor.workspace.deck import build_brief

    spec = DeckSpec(
        title="Q3 Review",
        slides=(
            Slide("Q3 Review", (), SlideLayout.TITLE),
            Slide("Wins", ("Shipped DLP", "3 accounts"), SlideLayout.BULLETS),
        ),
    )
    brief = build_brief(spec)
    assert "Q3 Review" in brief
    assert "Slide 1 [title]: Q3 Review" in brief
    assert "Slide 2 [bullets]: Wins" in brief
    # bullets kept, in order, under their slide
    assert brief.index("Shipped DLP") < brief.index("3 accounts")
    assert "- Shipped DLP" in brief


def test_stop_reaches_the_deck_step_not_only_the_research(monkeypatch):
    from types import SimpleNamespace

    from ghostcursor.workspace import deck, research

    stop = lambda: True  # noqa: E731
    seen = {}
    monkeypatch.setattr(
        research, "deep_research", lambda *a, **k: SimpleNamespace(graphs=())
    )
    monkeypatch.setattr(
        deck, "plan_deck", lambda *a, **k: seen.setdefault("cancelled", k.get("cancelled"))
    )
    deck.research_deck(object(), "topic", cancelled=stop)
    assert seen["cancelled"] is stop
